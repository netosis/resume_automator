import os
import re
import json
from typing import Optional, Dict, List, Any, Type
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
        self.browser: Optional[Any] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.browser_type: str = os.getenv("BROWSER_TYPE", "brave").lower()
        self.incognito: bool = os.getenv("BROWSER_INCOGNITO", "false").lower() == "true"

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
            if self.incognito:
                if self.browser_type == "firefox":
                    print(f"[PersistentBrowserManager] Launching Firefox in INCOGNITO/NON-PERSISTENT mode...")
                    self.browser = self.playwright.firefox.launch(
                        headless=False,
                        args=["-width", "1920", "-height", "1080"]
                    )
                    self.context = self.browser.new_context(no_viewport=True)
                else:
                    brave_path = self._find_brave_path()
                    print(f"[PersistentBrowserManager] Launching Brave in INCOGNITO/NON-PERSISTENT mode from: {brave_path}")
                    self.browser = self.playwright.chromium.launch(
                        executable_path=brave_path,
                        headless=False,
                        args=[
                            "--no-first-run",
                            "--start-maximized"
                        ]
                    )
                    self.context = self.browser.new_context(no_viewport=True)
            elif self.browser_type == "firefox":
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
                    no_viewport=True,
                    args=["-width", "1920", "-height", "1080"]
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
                    no_viewport=True,
                    args=[
                        "--no-first-run",
                        f"--profile-directory={profile_name}",
                        "--start-maximized"
                    ]
                )

            # Register a page event listener to auto-switch tabs when a new page is opened
            def on_page_created(new_page: Page):
                print(f"[PersistentBrowserManager] New tab detected: {new_page.url}. Switching active page.")
                self.page = new_page
                
            self.context.on("page", on_page_created)

        # Retrieve all unclosed pages
        active_pages = [p for p in self.context.pages if not p.is_closed()]
        if active_pages:
            self.page = active_pages[-1]
        else:
            self.page = self.context.new_page()

        # Set default timeout to 15 seconds to avoid hanging indefinitely on slower loads
        self.page.set_default_timeout(15000)
        return self.page

    def close(self):
        """
        Closes each individual tab, context, and stops Playwright.
        """
        if self.context:
            try:
                # Close each tab individually first
                for p in list(self.context.pages):
                    try:
                        if not p.is_closed():
                            p.close()
                    except Exception as pe:
                        if "closed" not in str(pe).lower():
                            print(f"[PersistentBrowserManager] Error closing individual tab: {pe}")
                
                # Close context
                self.context.close()
            except Exception as e:
                # If target page, context or browser has been closed, that's expected and normal
                # when closing all tabs closes the browser context.
                if "closed" not in str(e).lower():
                    print(f"[PersistentBrowserManager] Error closing context: {e}")
            self.context = None
            self.page = None

        if hasattr(self, "browser") and self.browser:
            try:
                self.browser.close()
            except Exception as e:
                if "closed" not in str(e).lower():
                    print(f"[PersistentBrowserManager] Error closing browser: {e}")
            self.browser = None

        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:
                if "closed" not in str(e).lower():
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


def get_accessibility_snapshot_sync(page: Page) -> Optional[dict]:
    """
    CDP helper to retrieve the accessibility tree as a hierarchical dict synchronously.
    """
    try:
        client = page.context.new_cdp_session(page)
        ax_tree = client.send("Accessibility.getFullAXTree")
        
        nodes = ax_tree.get("nodes", [])
        if not nodes:
            return None
        
        node_map = {}
        for node in nodes:
            node_id = node.get("nodeId")
            if node_id:
                node_map[node_id] = node
                
        root_node = nodes[0]
        for node in nodes:
            role = node.get("role", {}).get("value", "")
            if role == "RootWebArea":
                root_node = node
                break
                
        def build_node(node_id: str, depth: int = 0) -> Any:
            if depth > 25:
                return None
            node = node_map.get(node_id)
            if not node:
                return None
                
            if node.get("ignored", False):
                children_nodes = []
                for child_id in node.get("childIds", []):
                    child_res = build_node(child_id, depth)
                    if child_res:
                        if isinstance(child_res, list):
                            children_nodes.extend(child_res)
                        else:
                            children_nodes.append(child_res)
                return children_nodes
                
            role = node.get("role", {}).get("value", "")
            name = node.get("name", {}).get("value", "")
            
            children_nodes = []
            for child_id in node.get("childIds", []):
                child_res = build_node(child_id, depth + 1)
                if child_res:
                    if isinstance(child_res, list):
                        children_nodes.extend(child_res)
                    else:
                        children_nodes.append(child_res)
                        
            res = {
                "role": role,
                "name": name,
            }
            if children_nodes:
                res["children"] = children_nodes
                
            # Copy relevant properties
            for prop in node.get("properties", []):
                prop_name = prop.get("name")
                prop_val = prop.get("value", {}).get("value")
                if prop_name in ["focused", "focusable", "pressed", "disabled", "checked", "expanded"]:
                    res[prop_name] = prop_val
                elif prop_name == "url":
                    res["value"] = prop_val
                    
            return res

        result = build_node(root_node.get("nodeId", ""))
        if isinstance(result, list):
            return result[0] if result else None
        return result
    except Exception as e:
        print(f"[PersistentBrowserManager] Error building accessibility snapshot via CDP: {e}")
        return None


def prune_accessibility_tree(node: dict, mode: str = "interactive", depth: int = 0) -> list:
    """
    Recursively prune the accessibility tree based on mode (synchronous).
    """
    if not node or depth > 25:
        return []
    
    results = []
    role = node.get('role', '').lower()
    name = node.get('name', '')
    
    is_relevant = False
    
    if mode == "interactive":
        interactive_roles = {
            'button', 'link', 'textbox', 'checkbox', 'radio', 
            'combobox', 'listbox', 'menuitem', 'tab', 'slider',
            'searchbox', 'spinbutton', 'switch'
        }
        is_relevant = role in interactive_roles
        
    elif mode == "reading":
        content_roles = {
            'heading', 'paragraph', 'article', 'main', 'navigation',
            'button', 'link', 'list', 'listitem', 'section', 'region',
            'document', 'banner', 'complementary', 'contentinfo'
        }
        is_relevant = role in content_roles
        
    else:  # full mode
        is_relevant = True
    
    if is_relevant and (name or role):
        compact_node = {
            'role': role,
            'name': name[:80] if name else '',
        }
        
        if role in ['textbox', 'searchbox']:
            if 'value' in node:
                compact_node['value'] = str(node['value'])[:50]
                
        elif role == 'link':
            if 'value' in node:
                compact_node['url'] = str(node['value'])[:100]
                
        elif role == 'button':
            if 'pressed' in node:
                compact_node['pressed'] = node['pressed']
        
        # Add basic boolean states if present
        for prop in ["focused", "focusable", "pressed", "disabled", "checked", "expanded"]:
            if prop in node and prop not in compact_node:
                compact_node[prop] = node[prop]
                
        results.append(compact_node)
    
    for child in node.get('children', []):
        results.extend(prune_accessibility_tree(child, mode, depth + 1))
    
    return results


ACCESSIBILITY_TREE_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accessibility_tree.json")


def get_accessibility_info(page: Page, mode: str = "interactive") -> str:
    """
    Retrieves the accessibility snapshot of the page, saves it to a json file, and returns a pruned/formatted version.
    """
    snapshot = get_accessibility_snapshot_sync(page)
    if not snapshot:
        return "No accessibility tree available."
    
    pruned = prune_accessibility_tree(snapshot, mode)
    
    # Save the pruned tree to accessibility_tree.json for other functions to access
    try:
        with open(ACCESSIBILITY_TREE_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[get_accessibility_info] Warning: failed to save accessibility tree JSON: {e}")
        
    total_elements = len(pruned)
    limited_pruned = pruned[:100]
    
    result = {
        "mode": mode,
        "total_elements": total_elements,
        "elements": limited_pruned
    }
    if total_elements > 100:
        result["message"] = f"Showing first 100 of {total_elements} elements."
        
    return json.dumps(result, indent=2)


# LangChain Tools definitions

@tool
def open_website(url: str, mode: str = "interactive") -> str:
    """
    Launches the configured browser (if not already open) and navigates to the specified URL.
    Use this to open job boards like naukri.com, glassdoor.com, linkedin.com, or general links.
    Returns page title, current URL, and the pruned accessibility tree of the page.
    """
    try:
        # Standardize URL
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("file://")):
            url = "https://" + url

        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        print(f"[Tool: open_website] Navigating to: {url}")
        page.goto(url, wait_until="load")
        
        # Wait a small moment for dynamic loads
        page.wait_for_timeout(1500)
        
        title = page.title()
        current_url = page.url
        
        a11y_info = get_accessibility_info(page, mode)
        return (
            f"Successfully opened {current_url}. Page Title: '{title}'.\n\n"
            f"Accessibility Tree ({mode} mode):\n{a11y_info}"
        )
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
def click_on_element(selector: str, mode: str = "interactive") -> str:
    """
    Clicks on a web element using a CSS selector or text pattern (e.g., 'button.search', 'text=Apply Now').
    Use this to interact with buttons, search buttons, links, or checkmarks.
    Returns confirmation and the updated pruned accessibility tree.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Locate the element
        locator = page.locator(selector).first
        # Scroll into view if needed
        locator.scroll_into_view_if_needed()
        
        # Keep track of the page before click
        old_page = page
        
        print(f"[Tool: click_on_element] Clicking element: {selector}")
        locator.click()
        
        # Wait for potential navigation or state change / tab creation
        page.wait_for_timeout(2000)
        
        # Backup check: if there are multiple pages, ensure we are on the latest one
        if len(manager.context.pages) > 1:
            latest_page = manager.context.pages[-1]
            if latest_page != manager.page:
                print(f"[PersistentBrowserManager] Backup check: Switching active page to the latest tab.")
                manager.page = latest_page
        
        current_page = manager.get_page()
        a11y_info = get_accessibility_info(current_page, mode)
        
        if current_page != old_page:
            return (
                f"Successfully clicked the element: '{selector}'.\n"
                f"NOTICE: A new tab was opened and the browser session automatically switched to it.\n"
                f"New Tab URL: '{current_page.url}'\n"
                f"New Tab Title: '{current_page.title()}'\n\n"
                f"Accessibility Tree of the NEW tab ({mode} mode):\n{a11y_info}"
            )
        else:
            return (
                f"Successfully clicked the element: '{selector}'.\n\n"
                f"Updated Accessibility Tree ({mode} mode):\n{a11y_info}"
            )
    except Exception as e:
        return f"Failed to click element '{selector}'. Error: {str(e)}"


@tool
def input_text_into_element(selector: str, text: str, mode: str = "interactive") -> str:
    """
    Inputs/types text into a web input field matching the CSS selector (e.g., 'input[name="q"]', 'input#search-box').
    Use this to fill in search terms, search boxes, usernames, or application details.
    Returns confirmation and the updated pruned accessibility tree.
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
        
        # Wait a moment for dynamic page updates after typing
        page.wait_for_timeout(1000)
        
        a11y_info = get_accessibility_info(page, mode)
        return (
            f"Successfully typed '{text}' into element: '{selector}'.\n\n"
            f"Updated Accessibility Tree ({mode} mode):\n{a11y_info}"
        )
    except Exception as e:
        return f"Failed to type into element '{selector}'. Error: {str(e)}"


@tool
def scroll_page(direction: str, mode: str = "interactive") -> str:
    """
    Scrolls the page 'down' or 'up' to trigger loading of dynamic content (like continuous scrolling on LinkedIn or Naukri).
    direction: Must be either 'down' or 'up'.
    Returns confirmation and the updated pruned accessibility tree.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        if direction.lower() == "down":
            page.evaluate("window.scrollBy(0, window.innerHeight);")
            page.wait_for_timeout(1500)
            status = "Successfully scrolled down the page."
        elif direction.lower() == "up":
            page.evaluate("window.scrollBy(0, -window.innerHeight);")
            page.wait_for_timeout(1500)
            status = "Successfully scrolled up the page."
        else:
            return "Invalid direction. Please specify 'down' or 'up'."
            
        a11y_info = get_accessibility_info(page, mode)
        return (
            f"{status}\n\n"
            f"Updated Accessibility Tree ({mode} mode):\n{a11y_info}"
        )
    except Exception as e:
        return f"Failed to scroll page. Error: {str(e)}"




@tool
def get_interactable_buttons() -> str:
    """
    Scans the current page for visible, interactable buttons and clickable elements.
    Uses the already created accessibility_tree.json. If the file is not present,
    it calls get_accessibility_info to generate it and then gathers interactive elements from there.
    Returns a formatted text list of the buttons.
    """
    try:
        if not os.path.exists(ACCESSIBILITY_TREE_JSON_PATH):
            print("[get_interactable_buttons] accessibility_tree.json not found. Generating it now...")
            manager = PersistentBrowserManager.get_instance()
            page = manager.get_page()
            # Generate the json in interactive mode
            get_accessibility_info(page, "interactive")
            
        if not os.path.exists(ACCESSIBILITY_TREE_JSON_PATH):
            return "No accessibility tree or interactable buttons available."
            
        with open(ACCESSIBILITY_TREE_JSON_PATH, "r", encoding="utf-8") as f:
            elements = json.load(f)
            
        # Filter buttons, links and other clickable roles
        clickable_roles = {
            'button', 'link', 'checkbox', 'radio', 'combobox', 
            'listbox', 'menuitem', 'tab', 'slider', 'switch'
        }
        
        buttons = []
        for elem in elements:
            role = elem.get("role", "").lower()
            if role in clickable_roles:
                name = elem.get("name", "")
                if not name:
                    continue
                name_escaped = name.replace('"', '\\"')
                selector = f'role={role}[name="{name_escaped}"]'
                buttons.append({
                    "role": role,
                    "name": name,
                    "selector": selector
                })
                
        if not buttons:
            return "No interactable buttons or clickable elements were found on the current page."
            
        result_lines = []
        result_lines.append(f"Found {len(buttons)} interactable elements:")
        for idx, btn in enumerate(buttons):
            result_lines.append(
                f"{idx + 1}. [{btn['role']}] \"{btn['name']}\" -> Selector: {btn['selector']}"
            )
            
        return "\n".join(result_lines)
    except Exception as e:
        return f"Failed to retrieve interactable buttons. Error: {str(e)}"


@tool
def get_accessibility_tree(mode: str = "interactive") -> str:
    """
    Retrieves the accessibility tree of the currently active page.
    mode: Can be 'interactive' (buttons, links, textboxes), 'reading' (headings, text), or 'full'.
    Returns the pruned accessibility tree of the current page.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        a11y_info = get_accessibility_info(page, mode)
        return a11y_info
    except Exception as e:
        return f"Failed to retrieve accessibility tree. Error: {str(e)}"


@tool
def fetch_job_details() -> str:
    """
    Retrieves key details from the currently open job page using general body text extraction (truncated to 3000 characters).
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Get page title and URL
        title = page.title()
        url = page.url
        
        # Extract all text on the page
        text_content = page.locator("body").inner_text()
        cleaned_text = clean_page_text(text_content)
        
        # We can extract first 3000 chars of text as part of details
        truncated_text = cleaned_text[:3000] + ("..." if len(cleaned_text) > 3000 else "")
        
        return (
            f"Job Page URL: {url}\n"
            f"Page Title: {title}\n\n"
            f"Job Page Content (truncated):\n{truncated_text}"
        )
    except Exception as e:
        return f"Failed to fetch job details. Error: {str(e)}"


@tool
def click_apply_button(mode: str = "interactive") -> str:
    """
    Searches the current page for visible 'Apply', 'Apply on Company Site', or similar buttons/links and clicks them.
    Automatically detects if a new tab was opened, switches the active browser session to the new tab, and returns its content.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Scan page for a visible apply button/link using JS
        target_info = page.evaluate(r'''
            () => {
                const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'));
                const patterns = [
                    /^apply$/i,
                    /^apply\s+now$/i,
                    /apply\s+on\s+(company\s+)?site/i,
                    /easy\s+apply/i,
                    /apply\s+on\s+company\s+website/i,
                    /apply/i
                ];
                
                const visible = candidates.filter(el => {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
                });
                
                for (const pattern of patterns) {
                    for (const el of visible) {
                        const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
                        if (pattern.test(text)) {
                            el.setAttribute('data-automation-click-target', 'true');
                            return { text: text, tagName: el.tagName.toLowerCase() };
                        }
                    }
                }
                return null;
            }
        ''')
        
        if not target_info:
            return "No matching 'Apply' button or link was found on the current page."
            
        selector = '[data-automation-click-target="true"]'
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        # Keep track of active page before click
        old_page = page
        
        print(f"[Tool: click_apply_button] Clicking apply element: <{target_info['tagName']}> with text '{target_info['text']}'")
        locator.click()
        
        # Clean up temporary attribute
        page.evaluate('''
            () => {
                const el = document.querySelector('[data-automation-click-target="true"]');
                if (el) el.removeAttribute('data-automation-click-target');
            }
        ''')
        
        # Wait for potential page navigation or tab opening
        page.wait_for_timeout(2000)
        
        # Backup check: if there are multiple pages, ensure we are on the latest one
        if len(manager.context.pages) > 1:
            latest_page = manager.context.pages[-1]
            if latest_page != manager.page:
                print(f"[PersistentBrowserManager] Backup check: Switching active page to the latest tab.")
                manager.page = latest_page
                
        current_page = manager.get_page()
        a11y_info = get_accessibility_info(current_page, mode)
        
        if current_page != old_page:
            return (
                f"Successfully clicked the Apply element: '{target_info['text']}'.\n"
                f"NOTICE: A new tab was opened and the browser session automatically switched to it.\n"
                f"New Tab URL: '{current_page.url}'\n"
                f"New Tab Title: '{current_page.title()}'\n\n"
                f"Accessibility Tree of the NEW tab ({mode} mode):\n{a11y_info}"
            )
        else:
            return (
                f"Successfully clicked the Apply element: '{target_info['text']}'.\n\n"
                f"Updated Accessibility Tree ({mode} mode):\n{a11y_info}"
            )
            
    except Exception as e:
        return f"Failed to locate or click the Apply button. Error: {str(e)}"


@tool
def naukri_job_fetch() -> str:
    """
    Retrieves job details from the current page by locating and cleaning elements with class 'srp-jobtuple-wrapper'.
    Only use this on naukri.com search result pages.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Get page URL and title
        url = page.url
        title = page.title()
        
        # Locate all job cards matching `.srp-jobtuple-wrapper`
        job_cards_locator = page.locator(".srp-jobtuple-wrapper")
        card_count = job_cards_locator.count()
        
        job_cards_details = []
        for i in range(card_count):
            card = job_cards_locator.nth(i)
            # Retrieve HTML, strip HTML tags, and clean whitespace
            card_html = card.inner_html()
            # Clean HTML by removing tags and normal whitespace cleaning
            clean_text = re.sub(r'<[^>]*>', ' ', card_html)
            clean_text = clean_page_text(clean_text)
            job_cards_details.append(f"Job Listing {i + 1}:\n{clean_text}")
            
        method_b_content = "\n\n".join(job_cards_details)
        if not method_b_content:
            method_b_content = "No elements with class 'srp-jobtuple-wrapper' found on this page."
            
        return (
            f"Job Page URL: {url}\n"
            f"Page Title: {title}\n\n"
            f"Job Details from job cards:\n{method_b_content}"
        )
    except Exception as e:
        return f"Failed to fetch naukri job details. Error: {str(e)}"


@tool
def search_naukri_via_url(job_title: str) -> str:
    """
    Searches for jobs on naukri.com by directly modifying the URL pattern (e.g. 'naukri.com/ai-engineer-jobs')
    instead of using search boxes and buttons.
    When calling this tool, the LLM should ONLY provide the job role name (e.g., 'AI Engineer') for the 'job_title' parameter.
    Returns the confirmation of navigation and the updated accessibility tree.
    """
    mode = "interactive"
    try:
        # Standardize job title: convert to lowercase, strip, replace spaces/special chars with hyphens
        sanitized_title = job_title.lower().strip()
        sanitized_title = re.sub(r'[^a-z0-9]+', '-', sanitized_title)
        sanitized_title = sanitized_title.strip('-')
        
        url = f"https://www.naukri.com/{sanitized_title}-jobs"
        
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        print(f"[Tool: search_naukri_via_url] Navigating to direct search URL: {url}")
        page.goto(url, wait_until="load")
        
        # Wait a small moment for dynamic loads
        page.wait_for_timeout(1500)
        
        title = page.title()
        current_url = page.url
        
        a11y_info = get_accessibility_info(page, mode)
        return (
            f"Successfully navigated to direct search URL: {current_url}. Page Title: '{title}'.\n\n"
            f"Accessibility Tree ({mode} mode):\n{a11y_info}"
        )
    except Exception as e:
        return f"Failed to search naukri via URL. Error: {str(e)}"


@tool
def get_form_fields() -> str:
    """
    Scans the current page and extracts details about all form fields (inputs, select dropdowns, textareas, checkboxes, radio buttons, file inputs).
    Returns a structured text description of the fields including their labels, IDs, types, values, and options.
    Use this when filling forms to understand what fields are present.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Evaluate Javascript to collect form details
        form_details = page.evaluate(r'''
            () => {
                const fields = Array.from(document.querySelectorAll('input, select, textarea, [role="checkbox"], [role="radio"]'));
                const result = [];
                
                fields.forEach((el, index) => {
                    // Skip hidden elements
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0) return;
                    if (window.getComputedStyle(el).display === 'none' || window.getComputedStyle(el).visibility === 'hidden') return;
                    
                    const tagName = el.tagName.toLowerCase();
                    const type = el.type || '';
                    const id = el.id || '';
                    const name = el.name || '';
                    const value = el.value || '';
                    const placeholder = el.placeholder || '';
                    const isChecked = el.checked || false;
                    const isRequired = el.required || false;
                    
                    // Find associated label text
                    let labelText = '';
                    if (id) {
                        const labelEl = document.querySelector(`label[for="${id}"]`);
                        if (labelEl) {
                            labelText = labelEl.innerText.trim();
                        }
                    }
                    if (!labelText) {
                        // Try surrounding label
                        const parentLabel = el.closest('label');
                        if (parentLabel) {
                            labelText = parentLabel.innerText.trim();
                        }
                    }
                    if (!labelText) {
                        // Try aria-label or title
                        labelText = el.getAttribute('aria-label') || el.getAttribute('title') || '';
                    }
                    labelText = labelText.replace(/\s+/g, ' ').trim();
                    
                    // Collect dropdown options
                    let options = [];
                    if (tagName === 'select') {
                        options = Array.from(el.options).map(opt => ({
                            text: opt.text.trim(),
                            value: opt.value
                        }));
                    }
                    
                    // Generate unique CSS selectors
                    let selector = '';
                    if (id) {
                        selector = `#${id}`;
                    } else if (name) {
                        selector = `${tagName}[name="${name}"]`;
                    } else if (type && type !== 'text') {
                        selector = `${tagName}[type="${type}"]`;
                    } else {
                        // Unique path-based selector logic
                        let path = [];
                        let curr = el;
                        while (curr && curr !== document.body) {
                            let sibIdx = Array.from(curr.parentElement?.children || []).indexOf(curr) + 1;
                            path.unshift(`${curr.tagName.toLowerCase()}:nth-child(${sibIdx})`);
                            curr = curr.parentElement;
                        }
                        selector = path.join(' > ');
                    }
                    
                    result.push({
                        index: index + 1,
                        tagName,
                        type,
                        id,
                        name,
                        labelText,
                        placeholder,
                        value,
                        isChecked,
                        isRequired,
                        options,
                        selector
                    });
                });
                
                return result;
            }
        ''')
        
        if not form_details:
            return "No visible form fields were found on the current page."
            
        lines = [f"Found {len(form_details)} visible form fields:"]
        for field in form_details:
            desc = f"Field {field['index']}: <{field['tagName']}"
            if field['type']:
                desc += f" type=\"{field['type']}\""
            desc += f"> | Label: \"{field['labelText']}\" | Selector: \"{field['selector']}\""
            
            if field['isRequired']:
                desc += " [REQUIRED]"
            if field['placeholder']:
                desc += f" | Placeholder: \"{field['placeholder']}\""
            if field['value'] and field['type'] not in ['checkbox', 'radio']:
                desc += f" | Value: \"{field['value']}\""
            if field['type'] in ['checkbox', 'radio']:
                desc += f" | Checked: {field['isChecked']}"
                
            if field['options']:
                opt_desc = ", ".join([f"\"{o['text']}\" (value: {o['value']})" for o in field['options']])
                desc += f"\n   Options: [{opt_desc}]"
                
            lines.append(desc)
            
        return "\n".join(lines)
    except Exception as e:
        return f"Failed to retrieve form fields. Error: {str(e)}"


@tool
def select_dropdown_option(selector: str, option_value_or_text: str, mode: str = "interactive") -> str:
    """
    Selects an option from a drop-down (<select>) element matching the CSS selector.
    The option can be selected by its value attribute or visible text.
    Returns confirmation and the updated pruned accessibility tree.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        print(f"[Tool: select_dropdown_option] Selecting option '{option_value_or_text}' in: {selector}")
        
        try:
            # First try selecting by option value attribute
            locator.select_option(value=option_value_or_text)
        except Exception:
            try:
                # If value match fails, try by option label/text
                locator.select_option(label=option_value_or_text)
            except Exception:
                # Fallback to passing it directly as string option
                locator.select_option(option_value_or_text)
            
        page.wait_for_timeout(1000)
        a11y_info = get_accessibility_info(page, mode)
        return (
            f"Successfully selected option '{option_value_or_text}' from element: '{selector}'.\n\n"
            f"Updated Accessibility Tree ({mode} mode):\n{a11y_info}"
        )
    except Exception as e:
        return f"Failed to select option from element '{selector}'. Error: {str(e)}"


@tool
def set_checkbox_state(selector: str, checked: bool, mode: str = "interactive") -> str:
    """
    Checks or unchecks a checkbox or radio button element matching the CSS selector.
    checked: True to check / select, False to uncheck / deselect.
    Returns confirmation and the updated pruned accessibility tree.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        print(f"[Tool: set_checkbox_state] Setting checkbox state of {selector} to {checked}")
        
        if checked:
            locator.check()
        else:
            locator.uncheck()
            
        page.wait_for_timeout(1000)
        a11y_info = get_accessibility_info(page, mode)
        return (
            f"Successfully set state of element '{selector}' to checked={checked}.\n\n"
            f"Updated Accessibility Tree ({mode} mode):\n{a11y_info}"
        )
    except Exception as e:
        return f"Failed to set state of element '{selector}'. Error: {str(e)}"


@tool
def upload_file(selector: str, file_path: str, mode: str = "interactive") -> str:
    """
    Uploads a local file to a file input element matching the CSS selector.
    file_path: Absolute or relative path to the file to upload.
    Returns confirmation and the updated pruned accessibility tree.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            return f"Error: Local file to upload not found at: {abs_path}"
            
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        print(f"[Tool: upload_file] Uploading file '{abs_path}' to: {selector}")
        locator.set_input_files(abs_path)
        
        page.wait_for_timeout(1500)
        a11y_info = get_accessibility_info(page, mode)
        return (
            f"Successfully uploaded file '{abs_path}' to element: '{selector}'.\n\n"
            f"Updated Accessibility Tree ({mode} mode):\n{a11y_info}"
        )
    except Exception as e:
        return f"Failed to upload file to element '{selector}'. Error: {str(e)}"


@tool
def generate_fill_values(fields_json: str) -> str:
    """
    Given a list or string of form fields (with labels, selectors, types), analyzes them and generates mock details to fill.
    It returns a JSON dictionary mapping selectors or field names to their target values.
    Use this to plan and get all the form values at once, then fill the form using the output.
    """
    try:
        # Clean markdown wraps if any
        cleaned_json = fields_json.strip()
        if cleaned_json.startswith("```json"):
            cleaned_json = cleaned_json[7:]
        if cleaned_json.startswith("```"):
            cleaned_json = cleaned_json[3:]
        if cleaned_json.endswith("```"):
            cleaned_json = cleaned_json[:-3]
        cleaned_json = cleaned_json.strip()

        # Simple pattern extraction if raw get_form_fields text is passed directly
        if "[" not in cleaned_json and "{" not in cleaned_json:
            fields = []
            matches = re.findall(r'Label:\s*"([^"]+)"\s*\|\s*Selector:\s*"([^"]+)"', cleaned_json)
            for label, selector in matches:
                fields.append({"labelText": label, "selector": selector})
        else:
            try:
                fields = json.loads(cleaned_json)
            except Exception:
                fields = []
                matches = re.findall(r'Label:\s*"([^"]+)"\s*\|\s*Selector:\s*"([^"]+)"', cleaned_json)
                for label, selector in matches:
                    fields.append({"labelText": label, "selector": selector})

        fill_values = {}
        if isinstance(fields, dict):
            return json.dumps(fields, indent=2)

        for field in fields:
            if not isinstance(field, dict):
                continue
            label = field.get("labelText", "").lower()
            selector = field.get("selector", "")
            type_ = field.get("type", "").lower()
            tag = field.get("tagName", "").lower()
            
            if not selector:
                continue

            # Heuristics for typical form fields
            if "first" in label or "given" in label:
                fill_values[selector] = "John"
            elif "last" in label or "family" in label:
                fill_values[selector] = "Doe"
            elif "name" in label:
                fill_values[selector] = "John Doe"
            elif "email" in label:
                fill_values[selector] = "johndoe@example.com"
            elif "phone" in label or "mobile" in label:
                if "code" in label or "country" in label:
                    fill_values[selector] = "+91"
                else:
                    fill_values[selector] = "9876543210"
            elif "hear" in label:
                fill_values[selector] = "LinkedIn"
            elif tag == "select" or "role" in label:
                options = field.get("options", [])
                if options:
                    target_opt = options[1] if len(options) > 1 else options[0]
                    fill_values[selector] = target_opt.get("value") or target_opt.get("text")
                else:
                    fill_values[selector] = "ai-engineer"
            elif type_ == "checkbox" or type_ == "radio" or "terms" in label:
                fill_values[selector] = True

        # Fallback values if none generated
        if not fill_values:
            fill_values = {
                "#name--legalName--firstName": "John",
                "#name--legalName--lastName": "Doe",
                "#emailAddress--emailAddress": "johndoe@example.com",
                "#phoneNumber--countryPhoneCode": "+91",
                "#phoneNumber--phoneNumber": "9876543210",
                "#source--source": "LinkedIn"
            }

        return json.dumps(fill_values, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to parse or generate values: {str(e)}"})


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
