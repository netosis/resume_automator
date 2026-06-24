import os
import re
import json
import time
import random
from typing import Optional, Dict, List, Any, Type, Union
from playwright.sync_api import sync_playwright, Playwright, BrowserContext, Page
from langchain_core.tools import tool
from js_templates import (
    GET_COMPRESSED_DOM_JS,
    SCROLL_DOWN_JS,
    SCROLL_UP_JS,
    FIND_APPLY_BUTTON_JS,
    REMOVE_CLICK_TARGET_ATTR_JS,
    GET_FORM_FIELDS_JS,
    GET_TAG_NAME_JS
)
from async_logger import log_api_call, log_api_call_async, save_chat_transcript, get_session_id

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
        self.browser_profile: str = os.getenv("BROWSER_PROFILE", "Default")
        self.incognito: bool = os.getenv("BROWSER_INCOGNITO", "false").lower() == "true"
        self.session_id: str = get_session_id()
        self.api_call_logs: List[Dict[str, Any]] = []

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

    def _find_chrome_path(self) -> str:
        possible_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        raise FileNotFoundError(
            "Google Chrome executable was not found. Please verify Google Chrome is installed."
        )

    def _get_chrome_user_data_dir(self) -> str:
        local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(os.environ["USERPROFILE"], r"AppData\Local")
        return os.path.join(local_appdata, r"Google\Chrome\User Data")

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
                    try:
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
                    except FileNotFoundError:
                        print(f"[PersistentBrowserManager] Brave not found. Gracefully falling back to Playwright's bundled Chromium...")
                        self.browser = self.playwright.chromium.launch(
                            headless=False,
                            args=[
                                "--no-first-run",
                                "--start-maximized"
                            ]
                        )
                    self.context = self.browser.new_context(no_viewport=True)
            elif self.browser_type == "firefox":
                try:
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
                except FileNotFoundError as e:
                    print(f"[PersistentBrowserManager] Firefox profile not resolved: {e}. Gracefully falling back to default persistent Firefox context...")
                    self.firefox_profile_copy_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), 
                        ".firefox_profile_copy"
                    )
                    self.context = self.playwright.firefox.launch_persistent_context(
                        user_data_dir=self.firefox_profile_copy_path,
                        headless=False,
                        no_viewport=True,
                        args=["-width", "1920", "-height", "1080"]
                    )
            elif self.browser_type == "chrome":
                # Launch Google Chrome
                try:
                    chrome_path = self._find_chrome_path()
                    user_data_dir = self._get_chrome_user_data_dir()
                    profile_name = self.browser_profile
                    print(f"[PersistentBrowserManager] Launching Google Chrome from: {chrome_path}")
                    print(f"[PersistentBrowserManager] Using user data dir: {user_data_dir} with profile: {profile_name}")
                    print("IMPORTANT: Ensure all instances of Google Chrome are closed before running this script.")
                    
                    self.context = self.playwright.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        executable_path=chrome_path,
                        headless=False,
                        no_viewport=True,
                        args=[
                            "--no-first-run",
                            f"--profile-directory={profile_name}",
                            "--start-maximized"
                        ]
                    )
                except FileNotFoundError as e:
                    print(f"[PersistentBrowserManager] Chrome browser/profile not found: {e}. Gracefully falling back to Playwright's bundled Chromium default context...")
                    fallback_user_dir = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        ".chromium_profile"
                    )
                    self.context = self.playwright.chromium.launch_persistent_context(
                        user_data_dir=fallback_user_dir,
                        headless=False,
                        no_viewport=True,
                        args=[
                            "--no-first-run",
                            "--start-maximized"
                        ]
                    )
            else:
                # Default to Brave
                try:
                    brave_path = self._find_brave_path()
                    user_data_dir = self._get_brave_user_data_dir()
                    profile_name = self.browser_profile
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
                except FileNotFoundError as e:
                    print(f"[PersistentBrowserManager] Brave browser/profile not found: {e}. Gracefully falling back to Playwright's bundled Chromium default context...")
                    fallback_user_dir = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        ".chromium_profile"
                    )
                    self.context = self.playwright.chromium.launch_persistent_context(
                        user_data_dir=fallback_user_dir,
                        headless=False,
                        no_viewport=True,
                        args=[
                            "--no-first-run",
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
        # Reset accessibility state cache
        global _LAST_ACCESSIBILITY_STATE
        _LAST_ACCESSIBILITY_STATE = {
            "url": None,
            "mode": None,
            "json": None
        }

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
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Collapse multiple spaces and tabs per line, keeping newlines
    text = re.sub(r'[ \t]+', ' ', text)
    # Collapse multiple sequential newlines into a single newline
    text = re.sub(r'\n+', '\n', text)
    return text.strip()

def move_mouse_to_element_and_click(page: Page, locator) -> bool:
    """
    Moves the mouse cursor slowly from its current position to the center of the element,
    then clicks it, making the action visible to the user via PyAutoGUI if available.
    """
    try:
        # Scroll the element to the center of the viewport to prevent sticky headers/footers from obscuring it
        locator.evaluate("el => el.scrollIntoView({block: 'center', inline: 'center'})")
        page.wait_for_timeout(300) # Give smooth scrolling a moment to settle

        box = locator.bounding_box()
        if box:
            scroll_x = page.evaluate("window.scrollX")
            scroll_y = page.evaluate("window.scrollY")
            
            viewport_x = box['x'] + box['width'] / 2 - scroll_x
            viewport_y = box['y'] + box['height'] / 2 - scroll_y
            
            # Slow movement to target (x, y) using PyAutoGUI logic
            execute_human_pyautogui_action(page, "move_and_click", x=viewport_x, y=viewport_y)
            return True
        else:
            locator.click()
            return True
    except Exception as e:
        print(f"[move_mouse_to_element_and_click Warning] Failed to move mouse: {e}")
        try:
            locator.click()
            return True
        except Exception:
            return False



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


OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
ACCESSIBILITY_TREE_JSON_PATH = os.path.join(OUTPUTS_DIR, "accessibility_tree.json")

_LAST_ACCESSIBILITY_STATE = {
    "url": None,
    "mode": None,
    "json": None
}


def get_accessibility_info(page: Page, mode: str = "interactive") -> Union[str, bool]:
    """
    Retrieves the accessibility snapshot of the page, saves it to a json file, and returns a pruned/formatted version.
    Returns the JSON string if there is a change in the accessibility tree, otherwise returns False.
    """
    global _LAST_ACCESSIBILITY_STATE
    snapshot = get_accessibility_snapshot_sync(page)
    if not snapshot:
        url = page.url
        current_json = "No accessibility tree available."
        is_changed = (
            _LAST_ACCESSIBILITY_STATE.get("url") != url or
            _LAST_ACCESSIBILITY_STATE.get("mode") != mode or
            _LAST_ACCESSIBILITY_STATE.get("json") != current_json
        )
        if is_changed:
            _LAST_ACCESSIBILITY_STATE = {
                "url": url,
                "mode": mode,
                "json": current_json
            }
            return current_json
        return False
    
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
        
    current_json = json.dumps(result, indent=2)
    url = page.url
    
    is_changed = (
        _LAST_ACCESSIBILITY_STATE.get("url") != url or
        _LAST_ACCESSIBILITY_STATE.get("mode") != mode or
        _LAST_ACCESSIBILITY_STATE.get("json") != current_json
    )
    
    if is_changed:
        _LAST_ACCESSIBILITY_STATE = {
            "url": url,
            "mode": mode,
            "json": current_json
        }
        return current_json
    
    return False


COMPRESSED_DOM_JSON_PATH = os.path.join(OUTPUTS_DIR, "compressed_dom.json")

_LAST_DOM_STATE = {
    "url": None,
    "mode": None,
    "json": None
}

def get_compressed_dom_info(page: Page, mode: str = "interactive") -> Union[str, bool]:
    """
    Retrieves the compressed DOM of the page, saves it to a json file, and returns a formatted version.
    Returns the JSON string if there is a change in the compressed DOM, otherwise returns False.
    """
    global _LAST_DOM_STATE
    try:
        # Evaluate DOM compression in browser
        compressed_elements = page.evaluate(GET_COMPRESSED_DOM_JS, mode)
    except Exception as e:
        print(f"[PersistentBrowserManager] Error compressing DOM: {e}")
        return "Failed to compress DOM."

    if not compressed_elements:
        url = page.url
        current_json = "No compressed DOM elements available."
        is_changed = (
            _LAST_DOM_STATE.get("url") != url or
            _LAST_DOM_STATE.get("mode") != mode or
            _LAST_DOM_STATE.get("json") != current_json
        )
        if is_changed:
            _LAST_DOM_STATE = {
                "url": url,
                "mode": mode,
                "json": current_json
            }
            return current_json
        return False

    # Save the pruned tree to compressed_dom.json
    try:
        with open(COMPRESSED_DOM_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(compressed_elements, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[get_compressed_dom_info] Warning: failed to save compressed DOM JSON: {e}")

    total_elements = len(compressed_elements)
    limited_elements = compressed_elements[:100]

    result = {
        "mode": mode,
        "total_elements": total_elements,
        "elements": limited_elements
    }
    if total_elements > 100:
        result["message"] = f"Showing first 100 of {total_elements} elements."

    current_json = json.dumps(result, indent=2)
    url = page.url

    is_changed = (
        _LAST_DOM_STATE.get("url") != url or
        _LAST_DOM_STATE.get("mode") != mode or
        _LAST_DOM_STATE.get("json") != current_json
    )

    if is_changed:
        _LAST_DOM_STATE = {
            "url": url,
            "mode": mode,
            "json": current_json
        }
        return current_json
    return False

def get_representation_header_and_body(page: Page, mode: str) -> tuple:
    if mode.startswith("dom_"):
        dom_mode = mode.split("dom_", 1)[1]
        dom_info = get_compressed_dom_info(page, dom_mode)
        return f"Compressed DOM ({dom_mode} mode)", dom_info
    else:
        a11y_info = get_accessibility_info(page, mode)
        return f"Accessibility Tree ({mode} mode)", a11y_info

@tool
def get_compressed_dom(mode: str = "interactive", tool_summary: str = "") -> Union[str, bool]:
    """
    Retrieves a compressed, token-efficient DOM representation of the currently active page.
    mode: Can be 'interactive' (buttons, links, inputs), 'reading' (headings, paragraphs, text elements), or 'full'.
    Returns the compressed DOM of the current page if it has changed since the last retrieval, otherwise False.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        dom_info = get_compressed_dom_info(page, mode)
        return dom_info
    except Exception as e:
        return f"Failed to retrieve compressed DOM. Error: {str(e)}"


# LangChain Tools definitions

@tool
def open_website(url: str, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Launches the configured browser (if not already open) and navigates to the specified URL.
    Use this to open job boards like naukri.com, glassdoor.com, linkedin.com, or general links.
    Returns page title, current URL, and the pruned accessibility tree of the page if it has changed, otherwise False.
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
        page.wait_for_timeout(random.randint(1250, 1750))
        
        title = page.title()
        current_url = page.url
        
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"Successfully opened {current_url}. Page Title: '{title}'.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to navigate to {url}. Error: {str(e)}"


@tool
def get_page_text(tool_summary: str = "") -> str:
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
def click_on_element(selector: str, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Clicks on a web element using a CSS selector or text pattern (e.g., 'button.search', 'text=Apply Now').
    Use this to interact with buttons, search buttons, links, or checkmarks.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
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
        move_mouse_to_element_and_click(page, locator)
        
        # Wait for potential navigation or state change / tab creation
        page.wait_for_timeout(random.randint(1750, 2250))
        
        # Backup check: if there are multiple pages, ensure we are on the latest one
        if len(manager.context.pages) > 1:
            latest_page = manager.context.pages[-1]
            if latest_page != manager.page:
                print(f"[PersistentBrowserManager] Backup check: Switching active page to the latest tab.")
                manager.page = latest_page
        
        current_page = manager.get_page()
        rep_header, rep_body = get_representation_header_and_body(current_page, mode)
        
        if current_page != old_page:
            return (
                f"Successfully clicked the element: '{selector}'.\n"
                f"NOTICE: A new tab was opened and the browser session automatically switched to it.\n"
                f"New Tab URL: '{current_page.url}'\n"
                f"New Tab Title: '{current_page.title()}'\n\n"
                f"{rep_header} of the NEW tab:\n{rep_body}"
            )
        else:
            return (
                f"Successfully clicked the element: '{selector}'.\n\n"
                f"{rep_header}:\n{rep_body}"
            )
    except Exception as e:
        return f"Failed to click element '{selector}'. Error: {str(e)}"


@tool
def input_text_into_element(selector: str, text: str, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Inputs/types text into a web input field matching the CSS selector (e.g., 'input[name="q"]', 'input#search-box').
    Use this to fill in search terms, search boxes, usernames, or application details.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        # Clear field first
        locator.fill("")
        
        print(f"[Tool: input_text_into_element] Entering text into: {selector}")
        locator.type(text, delay=random.randint(40, 60)) # Type with a small realistic delay
        
        # Wait a moment for dynamic page updates after typing
        page.wait_for_timeout(random.randint(750, 1250))
        
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"Successfully typed '{text}' into element: '{selector}'.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to type into element '{selector}'. Error: {str(e)}"


@tool
def scroll_page(direction: str, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Scrolls the page 'down' or 'up' to trigger loading of dynamic content (like continuous scrolling on LinkedIn or Naukri).
    direction: Must be either 'down' or 'up'.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        if direction.lower() == "down":
            page.evaluate(SCROLL_DOWN_JS)
            page.wait_for_timeout(random.randint(1250, 1750))
            status = "Successfully scrolled down the page."
        elif direction.lower() == "up":
            page.evaluate(SCROLL_UP_JS)
            page.wait_for_timeout(random.randint(1250, 1750))
            status = "Successfully scrolled up the page."
        else:
            return "Invalid direction. Please specify 'down' or 'up'."
            
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"{status}\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to scroll page. Error: {str(e)}"




@tool
def get_interactable_buttons(tool_summary: str = "") -> str:
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
def get_accessibility_tree(mode: str = "interactive", tool_summary: str = "") -> Union[str, bool]:
    """
    Retrieves the accessibility tree of the currently active page.
    mode: Can be 'interactive' (buttons, links, textboxes), 'reading' (headings, text), or 'full'.
    Returns the pruned accessibility tree of the current page if it has changed since the last retrieval, otherwise False.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        a11y_info = get_accessibility_info(page, mode)
        return a11y_info
    except Exception as e:
        return f"Failed to retrieve accessibility tree. Error: {str(e)}"


@tool
def fetch_job_details(tool_summary: str = "") -> str:
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
def click_apply_button(mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Searches the current page for visible 'Apply', 'Apply on Company Site', 'Apply with Indeed',
    'Submit your application', 'Continue', 'Next', or similar buttons/links and clicks them.
    Automatically detects if a new tab was opened, switches the active browser session to the new tab, and returns its content.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Scan page for a visible apply button/link using JS
        target_info = page.evaluate(FIND_APPLY_BUTTON_JS)
        
        if not target_info:
            return "No matching 'Apply' button or link was found on the current page."
            
        selector = '[data-automation-click-target="true"]'
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        # Keep track of active page before click
        old_page = page
        
        print(f"[Tool: click_apply_button] Clicking apply element: <{target_info['tagName']}> with text '{target_info['text']}'")
        move_mouse_to_element_and_click(page, locator)
        
        # Clean up temporary attribute
        page.evaluate(REMOVE_CLICK_TARGET_ATTR_JS)
        
        # Wait for potential page navigation or tab opening
        page.wait_for_timeout(random.randint(1750, 2250))
        
        # Backup check: if there are multiple pages, ensure we are on the latest one
        if len(manager.context.pages) > 1:
            latest_page = manager.context.pages[-1]
            if latest_page != manager.page:
                print(f"[PersistentBrowserManager] Backup check: Switching active page to the latest tab.")
                manager.page = latest_page
                
        current_page = manager.get_page()
        rep_header, rep_body = get_representation_header_and_body(current_page, mode)
        
        if current_page != old_page:
            return (
                f"Successfully clicked the Apply element: '{target_info['text']}'.\n"
                f"NOTICE: A new tab was opened and the browser session automatically switched to it.\n"
                f"New Tab URL: '{current_page.url}'\n"
                f"New Tab Title: '{current_page.title()}'\n\n"
                f"{rep_header} of the NEW tab:\n{rep_body}"
            )
        else:
            return (
                f"Successfully clicked the Apply element: '{target_info['text']}'.\n\n"
                f"{rep_header}:\n{rep_body}"
            )
            
    except Exception as e:
        return f"Failed to locate or click the Apply button. Error: {str(e)}"


@tool
def get_form_fields(tool_summary: str = "") -> str:
    """
    Scans the current page and extracts details about all form fields (inputs, select dropdowns, textareas, checkboxes, radio buttons, file inputs).
    Returns a structured text description of the fields including their labels, IDs, types, values, and options.
    Use this when filling forms to understand what fields are present.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Evaluate Javascript to collect form details
        form_details = page.evaluate(GET_FORM_FIELDS_JS)
        
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
def select_dropdown_option(selector: str, option_value_or_text: str, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Selects an option from a drop-down (<select>) element matching the CSS selector.
    The option can be selected by its value attribute or visible text.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
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
            
        page.wait_for_timeout(random.randint(750, 1250))
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"Successfully selected option '{option_value_or_text}' from element: '{selector}'.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to select option from element '{selector}'. Error: {str(e)}"


@tool
def set_checkbox_state(selector: str, checked: bool, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Checks or unchecks a checkbox or radio button element matching the CSS selector.
    checked: True to check / select, False to uncheck / deselect.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
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
            
        page.wait_for_timeout(random.randint(750, 1250))
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"Successfully set state of element '{selector}' to checked={checked}.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to set state of element '{selector}'. Error: {str(e)}"


@tool
def upload_file(selector: str, file_path: str, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Uploads a local file to a file input element matching the CSS selector.
    file_path: Absolute or relative path to the file to upload.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
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
        
        page.wait_for_timeout(random.randint(1250, 1750))
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"Successfully uploaded file '{abs_path}' to element: '{selector}'.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to upload file to element '{selector}'. Error: {str(e)}"


def _evaluate_field_heuristics(field: dict) -> Optional[Union[str, bool]]:
    label = field.get("labelText", "").lower()
    type_ = field.get("type", "").lower()
    tag = field.get("tagName", "").lower()
    
    # Helper to resolve select options
    def get_select_option():
        options = field.get("options", [])
        if options:
            target_opt = options[1] if len(options) > 1 else options[0]
            return target_opt.get("value") or target_opt.get("text")
        return "ai-engineer"

    # Define a clean list of rule tuples: (predicate_fn, value_fn_or_literal)
    rules = [
        (lambda l, t, tg: "first" in l or "given" in l, "John"),
        (lambda l, t, tg: "last" in l or "family" in l, "Doe"),
        (lambda l, t, tg: "name" in l, "John Doe"),
        (lambda l, t, tg: "email" in l, "johndoe@example.com"),
        (lambda l, t, tg: "phone" in l or "mobile" in l, lambda l: "+91" if ("code" in l or "country" in l) else "9876543210"),
        (lambda l, t, tg: "hear" in l, "LinkedIn"),
        (lambda l, t, tg: tg == "select" or "role" in l, lambda l: get_select_option()),
        (lambda l, t, tg: t == "checkbox" or t == "radio" or "terms" in l, True)
    ]
    
    for predicate, val_provider in rules:
        if predicate(label, type_, tag):
            if callable(val_provider):
                try:
                    return val_provider(label)
                except TypeError:
                    return val_provider()
            return val_provider
    return None


@tool
def generate_fill_values(fields_json: str, tool_summary: str = "") -> str:
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
            selector = field.get("selector", "")
            if not selector:
                continue

            val = _evaluate_field_heuristics(field)
            if val is not None:
                fill_values[selector] = val


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


def _handle_form_text(locator, value, page) -> str:
    locator.fill("")
    locator.type(str(value), delay=random.randint(20, 40))
    page.wait_for_timeout(random.randint(50, 450))
    return f"Filled '{value}'"

def _handle_form_select(locator, value, page) -> str:
    val_str = str(value)
    try:
        locator.select_option(value=val_str)
    except Exception:
        try:
            locator.select_option(label=val_str)
        except Exception:
            locator.select_option(val_str)
    page.wait_for_timeout(random.randint(50, 550))
    return f"Selected option '{value}'"

def _handle_form_checkbox(locator, value, page) -> str:
    checked = bool(value)
    if checked:
        locator.check()
    else:
        locator.uncheck()
    page.wait_for_timeout(random.randint(50, 450))
    return f"Set checked={checked}"

def _handle_form_custom_combobox(locator, value, page) -> str:
    val_str = str(value)
    move_mouse_to_element_and_click(page, locator)
    page.wait_for_timeout(random.randint(350, 850))
    
    option_locator = page.locator('[role="option"]').filter(has_text=val_str).first
    if not option_locator.is_visible():
        option_locator = page.locator(f'text="{val_str}"').first
    if not option_locator.is_visible():
        option_locator = page.locator(f'[role="listbox"] >> text="{val_str}"').first
        
    if option_locator.is_visible():
        move_mouse_to_element_and_click(page, option_locator)
        page.wait_for_timeout(random.randint(150, 650))
        return f"Selected custom option '{val_str}'"
    else:
        tag_name = locator.evaluate(GET_TAG_NAME_JS)
        is_input = tag_name == "input" or locator.get_attribute("role") == "combobox"
        if is_input:
            locator.fill("")
            locator.type(val_str, delay=random.randint(40, 60))
            page.wait_for_timeout(random.randint(50, 550))
            page.keyboard.press("Enter")
            page.wait_for_timeout(random.randint(150, 650))
            return f"Typed and entered '{val_str}' into custom combobox"
        else:
            return f"Warning: Option '{val_str}' not found and custom selector is not input"

def _handle_form_file(locator, value, page) -> str:
    abs_path = os.path.abspath(str(value))
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"File to upload not found at {abs_path}")
    locator.set_input_files(abs_path)
    page.wait_for_timeout(random.randint(250, 750))
    return f"Uploaded '{abs_path}'"


@tool
def fill_entire_form(fields_data_json: str, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Fills out multiple form fields on the current page at once using Playwright.
    fields_data_json: A JSON string containing a list of objects representing fields to fill.
    Each field object MUST have:
      - 'selector': The CSS selector of the element to interact with.
      - 'value': The target text, option value, custom option text, or boolean checked state.
      - 'type': The interaction type. Must be one of:
         * 'text': For text inputs, textareas, etc. (uses fill and type).
         * 'select': For standard HTML <select> elements.
         * 'checkbox' (or 'radio'): For checkboxes or radio buttons (checked state is boolean).
         * 'custom_combobox': For custom dropdowns (clicks the combobox, then selects the option matching value).
         * 'file': For uploading a file (value is the local file path).
    
    Example format:
    [
      {"selector": "input[name='firstName']", "value": "John", "type": "text"},
      {"selector": "select[name='country']", "value": "US", "type": "select"},
      {"selector": "input[type='checkbox']", "value": true, "type": "checkbox"},
      {"selector": "#source--source", "value": "LinkedIn", "type": "custom_combobox"},
      {"selector": "input[type='file']", "value": "browser_agent/testcode/dummy_resume.pdf", "type": "file"}
    ]
    
    Returns confirmation and the updated pruned accessibility tree after all fields are filled.
    """
    try:
        cleaned_json = fields_data_json.strip()
        if cleaned_json.startswith("```json"):
            cleaned_json = cleaned_json[7:]
        if cleaned_json.startswith("```"):
            cleaned_json = cleaned_json[3:]
        if cleaned_json.endswith("```"):
            cleaned_json = cleaned_json[:-3]
        cleaned_json = cleaned_json.strip()
        
        fields = json.loads(cleaned_json)
        if not isinstance(fields, list):
            return "Error: Input fields_data_json must parse to a JSON list of dictionaries."
            
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Strategy mapping to reduce if-else branching
        handlers = {
            "text": _handle_form_text,
            "select": _handle_form_select,
            "checkbox": _handle_form_checkbox,
            "radio": _handle_form_checkbox,
            "custom_combobox": _handle_form_custom_combobox,
            "file": _handle_form_file,
        }
        
        results = []
        for idx, field in enumerate(fields):
            if not isinstance(field, dict):
                results.append(f"Field {idx}: skipped (not a dictionary)")
                continue
                
            selector = field.get("selector")
            value = field.get("value")
            field_type = field.get("type", "text").lower()
            
            if not selector:
                results.append(f"Field {idx}: skipped (missing selector)")
                continue
                
            try:
                locator = page.locator(selector).first
                locator.scroll_into_view_if_needed()
                
                handler = handlers.get(field_type)
                if handler:
                    msg = handler(locator, value, page)
                    results.append(f"{msg} for '{selector}'")
                else:
                    results.append(f"Field {idx}: skipped (unknown type '{field_type}')")
                    
            except Exception as e:
                results.append(f"Error executing field '{selector}': {str(e)}")
                
        page.wait_for_timeout(random.randint(750, 1250))
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        
        summary = "Form filling execution summary:\n" + "\n".join(f" - {res}" for res in results)
        return f"{summary}\n\n{rep_header}:\n{rep_body}"
        
    except Exception as e:
        return f"Failed to execute fill_entire_form. Error: {str(e)}"


@tool
def select_custom_combobox_option(selector: str, option_text: str, mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Selects an option from a custom combobox/dropdown button (like Workday's dropdowns)
    which is not a standard HTML <select> element.
    It clicks the combobox button/input, waits for the dropdown menu (e.g., listbox, list of options)
    to appear, finds the option containing the target option_text, and clicks it.
    Use this for selecting sources ("How did you hear about us?"), countries, or other custom Workday dropdowns.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Locate the combobox button and scroll to it
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        print(f"[Tool: select_custom_combobox_option] Clicking dropdown button/combobox: {selector}")
        move_mouse_to_element_and_click(page, locator)
        
        # Wait for potential dropdown menu/listbox/options to be visible
        page.wait_for_timeout(random.randint(750, 1250))
        
        # Look for option elements with role="option" or containing option_text
        option_locator = page.locator('[role="option"]').filter(has_text=option_text).first
        
        # Fallback 1: search elements with text match directly in case role isn't option
        if not option_locator.is_visible():
            option_locator = page.locator(f'text="{option_text}"').first
            
        # Fallback 2: search inside listbox
        if not option_locator.is_visible():
            option_locator = page.locator(f'[role="listbox"] >> text="{option_text}"').first
            
        if option_locator.is_visible():
            print(f"[Tool: select_custom_combobox_option] Clicking option containing: '{option_text}'")
            move_mouse_to_element_and_click(page, option_locator)
            page.wait_for_timeout(random.randint(750, 1250))
            rep_header, rep_body = get_representation_header_and_body(page, mode)
            return (
                f"Successfully selected option '{option_text}' from custom dropdown: '{selector}'.\n\n"
                f"{rep_header}:\n{rep_body}"
            )
        else:
            # Maybe the dropdown requires searching/typing first?
            # Let's try typing the option_text into the input/button if it is an input field
            tag_name = locator.evaluate(GET_TAG_NAME_JS)
            is_input = tag_name == "input" or locator.get_attribute("role") == "combobox"
            if is_input:
                print(f"[Tool: select_custom_combobox_option] Option list not visible. Attempting to type '{option_text}' and press Enter...")
                locator.fill("")
                locator.type(option_text, delay=random.randint(90, 110))
                page.wait_for_timeout(random.randint(250, 750))
                page.keyboard.press("Enter")
                page.wait_for_timeout(random.randint(750, 1250))
                rep_header, rep_body = get_representation_header_and_body(page, mode)
                return (
                    f"Attempted to type and enter option '{option_text}' into: '{selector}'.\n\n"
                    f"{rep_header}:\n{rep_body}"
                )
            
            return f"Failed to locate option '{option_text}' after clicking dropdown '{selector}'."
    except Exception as e:
        return f"Failed to select custom dropdown option. Error: {str(e)}"


@tool
def close_current_tab(tool_summary: str = "") -> str:
    """
    Closes the currently active browser tab and switches to the last remaining open tab.
    Use this when a new tab was opened (e.g., after clicking a link or Apply) and you are done with it.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        if not manager.context:
            return "No active browser context to close a tab from."
            
        pages = [p for p in manager.context.pages if not p.is_closed()]
        if len(pages) <= 1:
            return "Cannot close the current tab because it is the only tab open. Use close_browser_session if you want to close the browser."
            
        current_page = manager.page
        
        # Move mouse slowly to a simulated close area (e.g. x=900, y=0)
        try:
            current_page.wait_for_timeout(random.randint(150, 300))
        except Exception:
            pass
            
        current_page.close()

        
        # Switch to the last remaining page
        remaining_pages = [p for p in manager.context.pages if not p.is_closed()]
        manager.page = remaining_pages[-1]
        
        # Get representation of the new active page
        rep_header, rep_body = get_representation_header_and_body(manager.page, "interactive")
        return (
            f"Successfully closed the active tab. Active page switched to tab: '{manager.page.url}'.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to close current tab. Error: {str(e)}"


@tool
def go_back(mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Navigates the current page back one step in history.
    Returns confirmation, current URL, and the updated pruned accessibility tree of the page.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        page.go_back()
        page.wait_for_timeout(random.randint(1250, 1750))
        
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"Successfully went back in history. Current URL: '{page.url}'. Page Title: '{page.title()}'.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to go back. Error: {str(e)}"


@tool
def close_browser_session(tool_summary: str = "") -> str:
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



def parse_scratchpad(response_content):
    """
    Attempts to extract the JSON scratchpad content from the response content.
    Looks for <scratchpad>...</scratchpad> tags.
    """
    if not response_content:
        return None
    try:
        match = re.search(r"<scratchpad>(.*?)</scratchpad>", response_content, re.DOTALL)
        if match:
            content = match.group(1).strip()
            return json.loads(content)
    except Exception as e:
        print(f"[Scratchpad Parser Warning] Failed to parse scratchpad JSON: {e}")
    return None


def prune_old_tool_messages(messages, keep_last_n_tool_outputs=2):
    """
    Scans the message history and prunes the content of older ToolMessages
    to reduce token usage, keeping only the last N tool outputs fully intact.
    """
    tool_message_indices = [i for i, msg in enumerate(messages) if type(msg).__name__ == "ToolMessage"]
    
    if len(tool_message_indices) > keep_last_n_tool_outputs:
        prune_indices = tool_message_indices[:-keep_last_n_tool_outputs]
        for idx in prune_indices:
            msg = messages[idx]
            original_content = str(msg.content)
            if len(original_content) > 300:
                short_summary = original_content[:150].replace('\n', ' ') + "..."
                msg.content = f"[Detailed output of tool {getattr(msg, 'tool_call_id', 'unknown')} has been pruned to save context memory. Preview: {short_summary}]"


def update_agent_memory(messages, state_summary, response_content, keep_last_n_tool_outputs=2):
    """
    Updates the agent memory by:
    1. Parsing scratchpad from LLM response and merging it into state_summary.
    2. Keeping a single up-to-date SystemMessage for state_summary in the history.
    3. Pruning older ToolMessage outputs.
    """
    from langchain_core.messages import SystemMessage
    
    parsed = parse_scratchpad(response_content)
    if parsed:
        if "completed_steps" in parsed and isinstance(parsed["completed_steps"], list):
            for step_desc in parsed["completed_steps"]:
                if step_desc not in state_summary["completed_steps"]:
                    state_summary["completed_steps"].append(step_desc)
        if "extracted_data" in parsed and isinstance(parsed["extracted_data"], dict):
            state_summary["extracted_data"].update(parsed["extracted_data"])
        if "next_immediate_step" in parsed:
            state_summary["next_immediate_step"] = parsed["next_immediate_step"]

    scratchpad_content = f"### CURRENT AGENT STATE SUMMARY:\n{json.dumps(state_summary, indent=2)}"
    
    scratchpad_msg_idx = -1
    for i, msg in enumerate(messages):
        if type(msg).__name__ == "SystemMessage" and msg.content.startswith("### CURRENT AGENT STATE SUMMARY:"):
            scratchpad_msg_idx = i
            break
            
    if scratchpad_msg_idx != -1:
        messages[scratchpad_msg_idx] = SystemMessage(content=scratchpad_content)
    else:
        messages.insert(1, SystemMessage(content=scratchpad_content))

    prune_old_tool_messages(messages, keep_last_n_tool_outputs)


import math

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.01
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False


def execute_human_pyautogui_action(page: Page, action_type: str, **kwargs):
    """
    Executes a PyAutoGUI mouse, keyboard, or scroll action by converting Playwright viewport 
    coordinates to absolute monitor coordinates, using a Bezier curve for human-like 
    mouse movement, and realistic typing delays.
    """
    is_headless = os.environ.get("HEADLESS", "false").lower() == "true"
    
    if not _PYAUTOGUI_AVAILABLE or is_headless:
        print(f"[PyAutoGUI] Library not available or browser is headless. Falling back to Playwright native interactions.")
        if action_type == "move_and_click":
            x = kwargs.get("x")
            y = kwargs.get("y")
            if x is not None and y is not None:
                page_x = x + page.evaluate("window.scrollX")
                page_y = y + page.evaluate("window.scrollY")
                page.mouse.move(page_x, page_y)
                page.mouse.click(page_x, page_y)
        elif action_type == "type":
            page.keyboard.type(kwargs.get("text", ""))
        elif action_type == "press":
            page.keyboard.press(kwargs.get("key", ""))
        elif action_type == "scroll":
            clicks = kwargs.get("scroll_amount", 0)
            if clicks > 0:
                page.mouse.wheel(0, -clicks * 10) # approximate scroll up
            else:
                page.mouse.wheel(0, -clicks * 10) # approximate scroll down
        return

    if action_type == "move_and_click":
        viewport_x = kwargs.get("x")
        viewport_y = kwargs.get("y")
        
        # Convert viewport coordinates to absolute monitor coordinates
        coords = page.evaluate(f"""() => {{
                    const dpr = window.devicePixelRatio || 1;
                    const borderLeftWidth = window.outerWidth > window.innerWidth ? (window.outerWidth - window.innerWidth) / 2 : 0;
                    const topChromeHeight = window.outerHeight > window.innerHeight ? (window.outerHeight - window.innerHeight) - borderLeftWidth : 0;

                    const absoluteX = (window.screenX + borderLeftWidth + {viewport_x}) * dpr;
                    const absoluteY = (window.screenY + topChromeHeight + {viewport_y}) * dpr;
                    return [absoluteX, absoluteY, dpr];
                }}""")
        
        if coords:
            end_x, end_y, dpr = coords
            # Run Bezier curve logic
            start_x, start_y = pyautogui.position()
            dx = end_x - start_x
            dy = end_y - start_y
            dist = math.hypot(dx, dy)
            
            if dist < 5:
                pyautogui.moveTo(end_x, end_y)
            else:
                steps = max(20, min(100, int(dist / 8)))
                p0 = (start_x, start_y)
                p3 = (end_x, end_y)
                
                arc_magnitude = random.uniform(0.1, 0.3) * dist
                arc_direction = 1 if random.random() > 0.5 else -1
                
                perp_x = -dy / dist * arc_magnitude * arc_direction
                perp_y = dx / dist * arc_magnitude * arc_direction
                
                p1 = (
                    start_x + dx * 0.3 + perp_x + random.uniform(-dist*0.1, dist*0.1),
                    start_y + dy * 0.3 + perp_y + random.uniform(-dist*0.1, dist*0.1)
                )
                p2 = (
                    start_x + dx * 0.7 + perp_x * random.uniform(0.5, 1.5) + random.uniform(-dist*0.1, dist*0.1),
                    start_y + dy * 0.7 + perp_y * random.uniform(0.5, 1.5) + random.uniform(-dist*0.1, dist*0.1)
                )

                for i in range(1, steps + 1):
                    t = i / steps
                    t_eased = -(math.cos(math.pi * t) - 1) / 2
                    u = 1 - t_eased
                    x = (u**3 * p0[0] + 3 * u**2 * t_eased * p1[0] + 3 * u * t_eased**2 * p2[0] + t_eased**3 * p3[0])
                    y = (u**3 * p0[1] + 3 * u**2 * t_eased * p1[1] + 3 * u * t_eased**2 * p2[1] + t_eased**3 * p3[1])
                    
                    jitter_factor = math.sin(math.pi * t)
                    jitter_x = random.uniform(-2, 2) * jitter_factor
                    jitter_y = random.uniform(-2, 2) * jitter_factor
                    
                    pyautogui.moveTo(int(x + jitter_x), int(y + jitter_y))
                    time.sleep(random.uniform(0.005, 0.015))
                
                pyautogui.moveTo(end_x, end_y)
                time.sleep(random.uniform(0.001, 0.003))
            
            # Use Playwright's native click at the exact page coordinates for 100% precision
            # This ensures we never miss the button due to OS DPI/window border miscalculations,
            # while still benefiting from the PyAutoGUI human-like mouse movement to evade detection!
            page_x = viewport_x + page.evaluate("window.scrollX")
            page_y = viewport_y + page.evaluate("window.scrollY")
            page.mouse.click(page_x, page_y)
            
    elif action_type == "type":
        text = kwargs.get("text", "")
        for char in text:
            pyautogui.write(char)
            time.sleep(random.uniform(0.03, 0.1))
            
    elif action_type == "press":
        key = kwargs.get("key", "")
        key_map = {
            "Enter": "enter",
            "Backspace": "backspace",
            "Tab": "tab",
            "Control+A": "ctrl+a",
            "Escape": "esc"
        }
        pyautogui_key = key_map.get(key, key.lower())
        if "+" in pyautogui_key:
            keys = pyautogui_key.split("+")
            pyautogui.hotkey(*keys)
        else:
            pyautogui.press(pyautogui_key)
        time.sleep(random.uniform(0.1, 0.3))
        
    elif action_type == "scroll":
        clicks = kwargs.get("scroll_amount", 0)
        pyautogui.scroll(clicks)
        time.sleep(random.uniform(0.2, 0.4))


@tool
def os_level_mouse_keyboard_action(action_type: str, x: Optional[float] = None, y: Optional[float] = None, text: Optional[str] = None, key: Optional[str] = None, scroll_amount: Optional[int] = None, tool_summary: str = "") -> str:
    """
    Executes a PyAutoGUI OS-level mouse/keyboard action on the persistent browser.
    Useful to bypass bot-detection using human-like Bezier curves.
    'action_type' must be one of: 'move_and_click', 'type', 'press', 'scroll'.
    If 'move_and_click', provide 'x' and 'y' (viewport coordinates).
    If 'type', provide 'text'.
    If 'press', provide 'key' (e.g. 'Enter').
    If 'scroll', provide 'scroll_amount' (positive to scroll up, negative to scroll down).
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        print(f"[Tool: os_level_mouse_keyboard_action] Executing {action_type} via PyAutoGUI")
        execute_human_pyautogui_action(page, action_type, x=x, y=y, text=text, key=key, scroll_amount=scroll_amount)
        return f"Successfully executed OS-level PyAutoGUI action: {action_type}"
    except Exception as e:
        return f"Failed to execute OS-level action. Error: {str(e)}"

