import os
import re
from typing import Optional
from playwright.sync_api import sync_playwright, Playwright, BrowserContext, Page
from langchain_core.tools import tool

class PersistentBrowserManager:
    """
    Singleton manager for controlling Brave or Firefox Browsers via Playwright.
    Ensures that the same browser instance and context are reused across different tool calls.
    Configurable via the BROWSER_TYPE environment variable ('brave' or 'firefox').
    """
    _instance: Optional['PersistentBrowserManager'] = None

    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.browser_type: str = os.getenv("BROWSER_TYPE", "brave").lower()

    @classmethod
    def get_instance(cls) -> 'PersistentBrowserManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _find_brave_path(self) -> str:
        possible_paths = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), r"BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        raise FileNotFoundError(
            "Brave Browser executable was not found. Please verify Brave is installed."
        )

    def _get_brave_user_data_dir(self) -> str:
        local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(os.environ["USERPROFILE"], r"AppData\Local")
        return os.path.join(local_appdata, r"BraveSoftware\Brave-Browser\User Data")

    def _find_firefox_path(self) -> str:
        possible_paths = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Mozilla Firefox\firefox.exe"),
            os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Mozilla Firefox\firefox.exe"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        raise FileNotFoundError(
            "Firefox executable was not found. Please verify Firefox is installed."
        )

    def _find_firefox_profile_path(self) -> str:
        appdata = os.environ.get("APPDATA") or os.path.join(os.environ["USERPROFILE"], r"AppData\Roaming")
        profiles_dir = os.path.join(appdata, r"Mozilla\Firefox\Profiles")
        if not os.path.exists(profiles_dir):
            raise FileNotFoundError(f"Firefox profiles directory not found at: {profiles_dir}")
        
        entries = [
            os.path.join(profiles_dir, name)
            for name in os.listdir(profiles_dir)
            if os.path.isdir(os.path.join(profiles_dir, name))
        ]
        if not entries:
            raise FileNotFoundError(f"No profile folders found in Firefox profiles directory: {profiles_dir}")
        
        # Modern Firefox uses .default-release as the primary profile, fall back to .default
        for entry in entries:
            if entry.endswith(".default-release"):
                return entry
        for entry in entries:
            if entry.endswith(".default"):
                return entry
        return entries[0]
    def _copy_firefox_profile(self, src: str, dst: str):
        import shutil
        if os.path.exists(dst):
            try:
                shutil.rmtree(dst)
            except Exception as e:
                print(f"[PersistentBrowserManager] Warning: failed to clean previous profile copy: {e}")
                
        os.makedirs(dst, exist_ok=True)
        src_cookies = os.path.join(src, "cookies.sqlite")
        if os.path.exists(src_cookies):
            dst_cookies = os.path.join(dst, "cookies.sqlite")
            try:
                shutil.copy2(src_cookies, dst_cookies)
                print("[PersistentBrowserManager] Copied cookies.sqlite successfully.")
            except Exception as e:
                print(f"[PersistentBrowserManager] Warning: failed to copy cookies.sqlite: {e}")

    def get_page(self) -> Page:
        """
        Launches the browser context if not already active and returns the active page.
        """
        if self.page and not self.page.is_closed():
            return self.page

        if not self.playwright:
            self.playwright = sync_playwright().start()

        if not self.context:
            if self.browser_type == "firefox":
                original_profile_path = self._find_firefox_profile_path()
                self.firefox_profile_copy_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), 
                    ".firefox_profile_copy"
                )
                print(f"[PersistentBrowserManager] Copying Firefox profile from {original_profile_path} to {self.firefox_profile_copy_path}...")
                self._copy_firefox_profile(original_profile_path, self.firefox_profile_copy_path)
                
                print(f"[PersistentBrowserManager] Launching Playwright's bundled Firefox...")
                print(f"[PersistentBrowserManager] Using copied profile directory: {self.firefox_profile_copy_path}")
                
                self.context = self.playwright.firefox.launch_persistent_context(
                    user_data_dir=self.firefox_profile_copy_path,
                    headless=False,
                )
            else:
                # Default to Brave
                brave_path = self._find_brave_path()
                user_data_dir = self._get_brave_user_data_dir()
                profile_name = "Default"
                print(f"[PersistentBrowserManager] Launching Brave from: {brave_path}")
                print(f"[PersistentBrowserManager] Using user data dir: {user_data_dir} with profile: {profile_name}")
                print("IMPORTANT: Ensure all instances of Brave Browser are closed before running this script.")
                
                self.context = self.playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    executable_path=brave_path,
                    headless=False,
                    args=[
                        "--no-first-run",
                        f"--profile-directory={profile_name}"
                    ]
                )

        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()

        # Set default timeout to 15 seconds to avoid hanging indefinitely on slower loads
        self.page.set_default_timeout(15000)
        return self.page

    def close(self):
        """
        Closes current page, context, and stops Playwright.
        """
        if self.context:
            try:
                self.context.close()
            except Exception as e:
                print(f"[PersistentBrowserManager] Error closing context: {e}")
            self.context = None
            self.page = None
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:
                print(f"[PersistentBrowserManager] Error stopping Playwright: {e}")
            self.playwright = None

        # Clean up copied firefox profile directory
        if hasattr(self, "firefox_profile_copy_path") and self.firefox_profile_copy_path:
            import shutil
            if os.path.exists(self.firefox_profile_copy_path):
                try:
                    shutil.rmtree(self.firefox_profile_copy_path)
                    print(f"[PersistentBrowserManager] Cleaned up temporary profile copy: {self.firefox_profile_copy_path}")
                except Exception as e:
                    print(f"[PersistentBrowserManager] Warning: failed to remove temporary profile copy: {e}")


# Helpers for text cleaning
def clean_page_text(text: str) -> str:
    """
    Cleans up the text content from a web page by collapsing whitespace
    and stripping boilerplate.
    """
    # Collapse multiple spaces and newlines
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n+', '\n', text)
    return text.strip()


# LangChain Tools definitions

@tool
def open_website(url: str) -> str:
    """
    Launches the configured browser (if not already open) and navigates to the specified URL.
    Use this to open job boards like naukri.com, glassdoor.com, linkedin.com, or general links.
    """
    try:
        # Standardize URL
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        print(f"[Tool: open_website] Navigating to: {url}")
        page.goto(url, wait_until="load")
        
        # Wait a small moment for dynamic loads
        page.wait_for_timeout(1500)
        
        title = page.title()
        current_url = page.url
        return f"Successfully opened {current_url}. Page Title: '{title}'."
    except Exception as e:
        return f"Failed to navigate to {url}. Error: {str(e)}"


@tool
def get_page_text() -> str:
    """
    Extracts and returns the text content of the currently active web page.
    Use this to read job descriptions, search results, or profile data from the page.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Extract text from the body
        text_content = page.locator("body").inner_text()
        cleaned_text = clean_page_text(text_content)
        
        # Trim text to prevent huge LLM context usage (limit to approx 8000 chars)
        max_length = 8000
        if len(cleaned_text) > max_length:
            return cleaned_text[:max_length] + "... [TRUNCATED due to length limit]"
        
        return cleaned_text if cleaned_text else "The page appears to have no text content."
    except Exception as e:
        return f"Failed to retrieve page text. Error: {str(e)}"


@tool
def click_on_element(selector: str) -> str:
    """
    Clicks on a web element using a CSS selector or text pattern (e.g., 'button.search', 'text=Apply Now').
    Use this to interact with buttons, search buttons, links, or checkmarks.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Locate the element
        locator = page.locator(selector).first
        # Scroll into view if needed
        locator.scroll_into_view_if_needed()
        
        print(f"[Tool: click_on_element] Clicking element: {selector}")
        locator.click()
        
        # Wait for potential navigation or state change
        page.wait_for_timeout(1000)
        return f"Successfully clicked the element: '{selector}'."
    except Exception as e:
        return f"Failed to click element '{selector}'. Error: {str(e)}"


@tool
def input_text_into_element(selector: str, text: str) -> str:
    """
    Inputs/types text into a web input field matching the CSS selector (e.g., 'input[name="q"]', 'input#search-box').
    Use this to fill in search terms, search boxes, usernames, or application details.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        # Clear field first
        locator.fill("")
        
        print(f"[Tool: input_text_into_element] Entering text into: {selector}")
        locator.type(text, delay=50) # Type with a small realistic delay
        
        return f"Successfully typed '{text}' into element: '{selector}'."
    except Exception as e:
        return f"Failed to type into element '{selector}'. Error: {str(e)}"


@tool
def scroll_page(direction: str) -> str:
    """
    Scrolls the page 'down' or 'up' to trigger loading of dynamic content (like continuous scrolling on LinkedIn or Naukri).
    direction: Must be either 'down' or 'up'.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        if direction.lower() == "down":
            page.evaluate("window.scrollBy(0, window.innerHeight);")
            page.wait_for_timeout(1000)
            return "Successfully scrolled down the page."
        elif direction.lower() == "up":
            page.evaluate("window.scrollBy(0, -window.innerHeight);")
            page.wait_for_timeout(1000)
            return "Successfully scrolled up the page."
        else:
            return "Invalid direction. Please specify 'down' or 'up'."
    except Exception as e:
        return f"Failed to scroll page. Error: {str(e)}"


def get_interactable_buttons_raw(page: Page) -> list:
    """
    Evaluates JavaScript on the page to retrieve the raw list of interactable buttons.
    """
    js_code = """
    () => {
        const oldElements = document.querySelectorAll('[data-interactable-id]');
        oldElements.forEach(el => el.removeAttribute('data-interactable-id'));

        const candidates = Array.from(document.querySelectorAll(
            'button, input[type="button"], input[type="submit"], input[type="reset"], [role="button"], a, .btn, .button'
        ));
        
        const interactableButtons = [];
        let index = 0;
        
        for (const el of candidates) {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
            if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
            
            const id = `button-${index++}`;
            el.setAttribute('data-interactable-id', id);
            
            let text = el.innerText ? el.innerText.trim() : "";
            if (!text) {
                text = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || "";
                text = text.trim();
            }
            
            if (text.length > 100) {
                text = text.substring(0, 100) + "...";
            }
            
            let standardSelector = "";
            if (el.id) {
                standardSelector = `#${el.id}`;
            } else {
                const tagName = el.tagName.toLowerCase();
                const classes = Array.from(el.classList)
                    .filter(c => typeof c === 'string' && !c.startsWith('data-') && !c.includes('hover') && !c.includes('active'))
                    .join('.');
                if (classes) {
                    standardSelector = `${tagName}.${classes.substring(0, 50)}`;
                } else {
                    standardSelector = tagName;
                }
            }
            
            interactableButtons.push({
                "id": id,
                "tag": el.tagName.toLowerCase(),
                "text": text || "[No text/label]",
                "temp_selector": `[data-interactable-id="${id}"]`,
                "standard_selector": standardSelector
            });
        }
        return interactableButtons;
    }
    """
    return page.evaluate(js_code)


@tool
def get_interactable_buttons() -> str:
    """
    Scans the current page for visible, interactable buttons and clickable elements.
    Assigns temporary `data-interactable-id` selectors to these elements and returns
    a formatted text list of the buttons.
    Use this list to decide which button to click. You can click any element in the list
    by passing its 'temp_selector' (e.g., '[data-interactable-id="button-0"]') to the `click_on_element` tool.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        buttons = get_interactable_buttons_raw(page)
        
        if not buttons:
            return "No interactable buttons or clickable elements were found on the current page."
            
        result_lines = []
        result_lines.append(f"Found {len(buttons)} interactable elements:")
        for idx, btn in enumerate(buttons):
            result_lines.append(
                f"{idx + 1}. [{btn['tag']}] \"{btn['text']}\" -> Selector: {btn['temp_selector']} (Approx: {btn['standard_selector']})"
            )
            
        return "\n".join(result_lines)
    except Exception as e:
        return f"Failed to retrieve interactable buttons. Error: {str(e)}"


@tool
def close_browser_session() -> str:
    """
    Closes the active Browser window and stops the automation session.
    Call this when the browsing task is completely done.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        browser_type_name = manager.browser_type.capitalize()
        manager.close()
        return f"{browser_type_name} Browser session successfully closed."
    except Exception as e:
        return f"Failed to close browser session. Error: {str(e)}"
