"""
Browser Automation Tools for Token-Efficient Web Navigation
Implements 5 strategies to reduce LLM token usage when navigating websites
Compatible with LangChain 1.0+
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Type, Union
from dataclasses import dataclass
from enum import Enum

# Corrected LangChain imports for modern versions
from langchain.tools import BaseTool
from langchain_core.tools import tool
from langchain_core.callbacks import CallbackManagerForToolRun
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

# ============== Logging Setup ==============

def setup_logging(name: str = "browser_agent", level: int = logging.INFO) -> logging.Logger:
    """Setup comprehensive logging for browser tools"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    
    # Create file handler
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log")
    file_handler.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()


# ============== Brave Browser Helper Utilities ==============

def find_brave_path() -> Optional[str]:
    """Locate the Brave Browser executable on Windows"""
    possible_paths = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

def get_brave_user_data_dir() -> str:
    """Retrieve default Brave Browser user data directory"""
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(os.environ["USERPROFILE"], r"AppData\Local")
    return os.path.join(local_appdata, r"BraveSoftware\Brave-Browser\User Data")

async def async_launch_browser(playwright, tool_name: str) -> tuple:
    """
    Launches browser context based on environment settings.
    Respects BROWSER_TYPE (defaults to brave).
    Handles persistent and non-persistent launches gracefully.
    """
    browser_type = os.getenv("BROWSER_TYPE", "brave").lower()
    use_persistent = os.getenv("USE_PERSISTENT_CONTEXT", "true").lower() == "true"
    headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
    
    if browser_type == "firefox":
        if use_persistent:
            try:
                appdata = os.environ.get("APPDATA") or os.path.join(os.environ["USERPROFILE"], r"AppData\Roaming")
                profiles_dir = os.path.join(appdata, r"Mozilla\Firefox\Profiles")
                original_profile_path = None
                if os.path.exists(profiles_dir):
                    for name in os.listdir(profiles_dir):
                        if name.endswith(".default-release") or name.endswith(".default"):
                            original_profile_path = os.path.join(profiles_dir, name)
                            break
                    if not original_profile_path and os.listdir(profiles_dir):
                        original_profile_path = os.path.join(profiles_dir, os.listdir(profiles_dir)[0])
                
                if original_profile_path:
                    temp_profile_dir = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), 
                        f".firefox_profile_copy_{tool_name}"
                    )
                    import shutil
                    if os.path.exists(temp_profile_dir):
                        shutil.rmtree(temp_profile_dir, ignore_errors=True)
                    os.makedirs(temp_profile_dir, exist_ok=True)
                    src_cookies = os.path.join(original_profile_path, "cookies.sqlite")
                    if os.path.exists(src_cookies):
                        shutil.copy2(src_cookies, os.path.join(temp_profile_dir, "cookies.sqlite"))
                    
                    logger.info(f"Launching persistent Firefox context using copied profile: {temp_profile_dir}")
                    context = await playwright.firefox.launch_persistent_context(
                        user_data_dir=temp_profile_dir,
                        headless=headless,
                    )
                    return None, context
            except Exception as e:
                logger.error(f"Failed to launch persistent Firefox: {e}. Falling back to default.")
            
            temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), f".firefox_temp_{tool_name}")
            context = await playwright.firefox.launch_persistent_context(
                user_data_dir=temp_dir,
                headless=headless
            )
            return None, context
        else:
            logger.info("Launching non-persistent Firefox browser")
            browser = await playwright.firefox.launch(headless=headless)
            context = await browser.new_context()
            return browser, context
            
    else:  # default to Brave (Chromium-based)
        brave_path = find_brave_path()
        if not brave_path:
            logger.warning("Brave Browser not found. Falling back to default Playwright Chromium.")
            if use_persistent:
                temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), f".chrome_temp_{tool_name}")
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=temp_dir,
                    headless=headless
                )
                return None, context
            else:
                browser = await playwright.chromium.launch(headless=headless)
                context = await browser.new_context()
                return browser, context
                
        if use_persistent:
            user_data_dir = get_brave_user_data_dir()
            profile_name = "Default"
            logger.info(f"Launching persistent Brave from: {brave_path}")
            logger.info(f"Using user data dir: {user_data_dir} with profile: {profile_name}")
            logger.info("IMPORTANT: Ensure all instances of Brave Browser are closed before running this script.")
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                executable_path=brave_path,
                headless=headless,
                args=[
                    "--no-first-run",
                    f"--profile-directory={profile_name}"
                ]
            )
            return None, context
        else:
            logger.info(f"Launching non-persistent Brave browser from: {brave_path}")
            browser = await playwright.chromium.launch(
                executable_path=brave_path,
                headless=headless
            )
            context = await browser.new_context()
            return browser, context


async def get_accessibility_snapshot(page: Page) -> Optional[dict]:
    """
    CDP fallback helper to retrieve the accessibility tree as a hierarchical dict.
    Replaces the deprecated page.accessibility.snapshot() method.
    """
    try:
        client = await page.context.new_cdp_session(page)
        ax_tree = await client.send("Accessibility.getFullAXTree")
        
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
        logger.error(f"Error building accessibility snapshot via CDP: {e}", exc_info=True)
        return None


# ============== Data Models ==============

class BrowserAction(BaseModel):
    """Model for browser actions"""
    action_type: str = Field(description="Type of action: click, type, select, scroll, wait")
    target_id: Optional[str] = Field(None, description="Stable ID or selector of target element")
    value: Optional[str] = Field(None, description="Value to type or select")
    wait_ms: Optional[int] = Field(1000, description="Wait time in milliseconds")

class PageSnapshot(BaseModel):
    """Model for page snapshot data"""
    timestamp: str
    url: str
    title: str
    elements: List[Dict]
    stats: Dict[str, Any]

# ============== Strategy 1: Semantic Snapshots Tool ==============

class SemanticSnapshotInput(BaseModel):
    """Input for semantic snapshot tool"""
    url: str = Field(description="URL to navigate to and capture")

class SemanticSnapshotTool(BaseTool):
    """Extracts only meaningful interactive elements with stable IDs (70-90% token reduction)"""
    
    name: str = "semantic_snapshot"
    description: str = """
    Captures a semantic snapshot of the page with only interactive elements.
    Returns a compact representation with stable IDs for each element.
    Use this for general web navigation when you need to find clickable elements.
    Token reduction: 70-90% compared to raw HTML.
    """
    args_schema: Type[BaseModel] = SemanticSnapshotInput
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._element_counter = 0
        self._element_map = {}
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False
    
    async def _ensure_browser(self):
        """Ensure browser is initialized"""
        if not self._initialized:
            logger.info("Initializing browser for semantic snapshot tool")
            self._playwright = await async_playwright().start()
            self._browser, self._context = await async_launch_browser(self._playwright, "semantic")
            self._page = await self._context.new_page()
            self._initialized = True
            logger.info("Browser initialized successfully")
    
    async def _get_semantic_snapshot(self) -> List[Dict]:
        """Extract semantic snapshot from current page"""
        logger.debug("Extracting semantic snapshot from page")
        
        snapshot = await self._page.evaluate('''
            () => {
                const interactiveSelectors = [
                    'button', 'a[href]', 'input', 'select', 'textarea',
                    '[role="button"]', '[onclick]', 'details', 'summary'
                ];
                
                const elements = document.querySelectorAll(interactiveSelectors.join(','));
                const results = [];
                
                for (let i = 0; i < elements.length; i++) {
                    const el = elements[i];
                    
                    // Skip hidden elements
                    if (el.offsetParent === null) continue;
                    
                    // Generate a stable selector
                    let selector = '';
                    if (el.id) {
                        selector = `#${el.id}`;
                    } else if (el.getAttribute('data-testid')) {
                        selector = `[data-testid="${el.getAttribute('data-testid')}"]`;
                    } else {
                        // Build a unique path
                        let path = [];
                        let current = el;
                        while (current && current !== document.body) {
                            let index = Array.from(current.parentElement?.children || [])
                                .indexOf(current) + 1;
                            path.unshift(`${current.tagName.toLowerCase()}:nth-child(${index})`);
                            current = current.parentElement;
                        }
                        selector = path.join(' > ');
                    }
                    
                    // Get element info
                    const info = {
                        type: el.tagName.toLowerCase(),
                        role: el.getAttribute('role') || el.tagName.toLowerCase(),
                        text: (el.innerText || el.value || el.placeholder || '').trim().slice(0, 100),
                        selector: selector,
                        isVisible: el.offsetParent !== null,
                        ariaLabel: el.getAttribute('aria-label') || '',
                        href: el.href || '',
                        inputType: el.type || ''
                    };
                    
                    results.push(info);
                }
                
                return results;
            }
        ''')
        
        # Assign stable IDs
        for item in snapshot:
            stable_id = f"elem_{self._element_counter}"
            self._element_counter += 1
            self._element_map[stable_id] = item['selector']
            item['stable_id'] = stable_id
            # Remove the long selector from LLM context
            del item['selector']
        
        logger.info(f"Extracted {len(snapshot)} interactive elements with stable IDs")
        return snapshot
    
    def _run(self, url: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Synchronous run - not used, we use async version"""
        # Create a new event loop for sync execution
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._arun(url, run_manager))
        finally:
            loop.close()
    
    async def _arun(self, url: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Execute the tool"""
        try:
            logger.info(f"SemanticSnapshotTool called with URL: {url}")
            
            await self._ensure_browser()
            
            # Navigate to URL
            logger.debug(f"Navigating to {url}")
            await self._page.goto(url, wait_until="load")
            await self._page.wait_for_timeout(2000)
            
            # Get snapshot
            snapshot = await self._get_semantic_snapshot()
            
            # Create result (excluding the private element_map from LLM context)
            result = {
                "url": url,
                "title": await self._page.title(),
                "timestamp": datetime.now().isoformat(),
                "total_elements": len(snapshot),
                "elements": snapshot[:50],  # Limit to 50 elements
                "action": "Use the stable_id field to reference elements in future actions"
            }
            
            logger.info(f"Successfully captured {len(snapshot)} elements from {url}")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error in SemanticSnapshotTool: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e), "url": url})
    
    async def execute_action(self, stable_id: str, action: str, value: str = None) -> str:
        """Execute action using stable ID"""
        logger.info(f"Executing action '{action}' on element {stable_id}")
        
        selector = self._element_map.get(stable_id)
        if not selector:
            error_msg = f"Unknown stable ID: {stable_id}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})
        
        try:
            if action == "click":
                logger.debug(f"Clicking element with selector: {selector}")
                await self._page.click(selector)
                await self._page.wait_for_load_state("networkidle")
                result = {"status": "success", "action": "click", "element": stable_id}
                
            elif action == "type":
                logger.debug(f"Typing '{value}' into element with selector: {selector}")
                await self._page.fill(selector, value)
                result = {"status": "success", "action": "type", "element": stable_id, "value": value}
                
            elif action == "select":
                logger.debug(f"Selecting '{value}' from element with selector: {selector}")
                await self._page.select_option(selector, value)
                result = {"status": "success", "action": "select", "element": stable_id, "value": value}
                
            else:
                error_msg = f"Unknown action: {action}"
                logger.error(error_msg)
                return json.dumps({"error": error_msg})
            
            logger.info(f"Action '{action}' completed successfully")
            return json.dumps(result)
            
        except Exception as e:
            logger.error(f"Error executing action: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e), "action": action, "element": stable_id})
    
    async def cleanup(self):
        """Clean up browser resources"""
        logger.info("Cleaning up browser resources")
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
            self._browser = None
        elif self._context:
            try:
                await self._context.close()
            except Exception as e:
                logger.error(f"Error closing context: {e}")
            self._context = None
            
        if getattr(self, "_playwright", None):
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.error(f"Error stopping playwright: {e}")
            self._playwright = None
            
        self._page = None
        self._initialized = False

# ============== Strategy 2: Incremental Diffing Tool ==============

class DiffingInput(BaseModel):
    """Input for diffing tool"""
    url: str = Field(description="URL to navigate to")
    reset: bool = Field(False, description="Reset previous snapshot and capture full state")

class IncrementalDiffingTool(BaseTool):
    """Captures only elements that changed since last snapshot (90-95% reduction after first action)"""
    
    name: str = "incremental_diff"
    description: str = """
    Captures only the elements that changed since the last snapshot.
    First call returns full page state. Subsequent calls return only differences.
    Perfect for multi-step workflows where the page updates frequently.
    Token reduction: 90-95% after the first action.
    """
    args_schema: Type[BaseModel] = DiffingInput
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._previous_snapshot = None
        self._previous_url = None
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False
    
    def _hash_element(self, element: Dict) -> str:
        """Create a hash of element for change detection"""
        content = f"{element['type']}{element['text']}{element.get('value', '')}{element.get('checked', '')}"
        return hashlib.md5(content.encode()).hexdigest()
    
    async def _ensure_browser(self):
        """Ensure browser is initialized"""
        if not self._initialized:
            logger.info("Initializing browser for incremental diffing tool")
            self._playwright = await async_playwright().start()
            self._browser, self._context = await async_launch_browser(self._playwright, "diff")
            self._page = await self._context.new_page()
            self._initialized = True
            logger.info("Browser initialized successfully")
    
    async def _get_page_snapshot(self) -> List[Dict]:
        """Get current page snapshot"""
        logger.debug("Taking page snapshot")
        
        snapshot = await self._page.evaluate('''
            () => {
                const elements = document.querySelectorAll('button, a[href], input, select, textarea, [role="button"]');
                const results = [];
                
                for (const el of elements) {
                    if (el.offsetParent === null) continue;
                    
                    const rect = el.getBoundingClientRect();
                    results.push({
                        type: el.tagName.toLowerCase(),
                        text: (el.innerText || el.value || '').trim().slice(0, 50),
                        value: el.value || '',
                        id: el.id || '',
                        className: el.className || '',
                        visible: true,
                        x: Math.round(rect.x),
                        y: Math.round(rect.y),
                        checked: el.checked || false,
                        disabled: el.disabled || false
                    });
                }
                
                return results;
            }
        ''')
        
        # Calculate hashes for each element
        for elem in snapshot:
            elem['hash'] = self._hash_element(elem)
        
        logger.info(f"Captured snapshot with {len(snapshot)} elements")
        return snapshot
    
    def _run(self, url: str, reset: bool = False, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Synchronous run - not used"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._arun(url, reset, run_manager))
        finally:
            loop.close()
    
    async def _arun(self, url: str, reset: bool = False, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Execute the tool"""
        try:
            logger.info(f"IncrementalDiffingTool called with URL: {url}, reset: {reset}")
            
            await self._ensure_browser()
            
            # Navigate if URL changed or reset requested
            if self._previous_url != url or reset:
                logger.debug(f"Navigating to {url}")
                await self._page.goto(url, wait_until="load")
                await self._page.wait_for_timeout(2000)
                self._previous_snapshot = None
                self._previous_url = url
            
            current_snapshot = await self._get_page_snapshot()
            current_url = self._page.url
            
            # First snapshot or reset - return everything
            if self._previous_snapshot is None or reset:
                logger.info("First snapshot - returning full page state")
                self._previous_snapshot = current_snapshot
                self._previous_url = current_url
                
                result = {
                    "type": "full_snapshot",
                    "url": current_url,
                    "title": await self._page.title(),
                    "total_elements": len(current_snapshot),
                    "elements": current_snapshot[:100],
                    "timestamp": datetime.now().isoformat(),
                    "message": "This is the initial full snapshot. Future calls will return only differences."
                }
                
                logger.info(f"Returning full snapshot with {len(current_snapshot)} elements")
                return json.dumps(result, indent=2)
            
            # Calculate differences
            previous_hashes = {e['hash']: e for e in self._previous_snapshot}
            current_hashes = {e['hash']: e for e in current_snapshot}
            
            # Find added elements
            added = [e for e in current_snapshot if e['hash'] not in previous_hashes]
            
            # Find removed elements
            removed = [e for e in self._previous_snapshot if e['hash'] not in current_hashes]
            
            # Find modified elements
            modified = []
            min_len = min(len(self._previous_snapshot), len(current_snapshot))
            for i in range(min_len):
                prev = self._previous_snapshot[i]
                curr = current_snapshot[i]
                if prev['hash'] != curr['hash']:
                    modified.append({
                        'index': i,
                        'old_text': prev['text'],
                        'new_text': curr['text'],
                        'changes': {
                            'text_changed': prev['text'] != curr['text'],
                            'value_changed': prev.get('value') != curr.get('value')
                        }
                    })
            
            # Update previous snapshot
            self._previous_snapshot = current_snapshot
            
            result = {
                "type": "diff",
                "url": current_url,
                "title": await self._page.title(),
                "timestamp": datetime.now().isoformat(),
                "stats": {
                    "total_elements": len(current_snapshot),
                    "elements_added": len(added),
                    "elements_removed": len(removed),
                    "elements_modified": len(modified)
                },
                "added_elements": added[:20],
                "removed_elements_count": len(removed),
                "modified_elements": modified[:10],
                "message": f"Only {len(added) + len(modified)} elements changed out of {len(current_snapshot)} total"
            }
            
            logger.info(f"Diff calculated: {len(added)} added, {len(removed)} removed, {len(modified)} modified")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error in IncrementalDiffingTool: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e), "url": url})
    
    async def cleanup(self):
        """Clean up browser resources"""
        logger.info("Cleaning up browser resources")
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
            self._browser = None
        elif self._context:
            try:
                await self._context.close()
            except Exception as e:
                logger.error(f"Error closing context: {e}")
            self._context = None
            
        if getattr(self, "_playwright", None):
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.error(f"Error stopping playwright: {e}")
            self._playwright = None
            
        self._page = None
        self._initialized = False

# ============== Strategy 3: Accessibility Tree Tool ==============

class AccessibilityMode(str, Enum):
    INTERACTIVE = "interactive"
    READING = "reading"
    FULL = "full"

class AccessibilityInput(BaseModel):
    """Input for accessibility tree tool"""
    url: str = Field(description="URL to navigate to")
    mode: AccessibilityMode = Field(AccessibilityMode.INTERACTIVE, description="Mode: interactive, reading, or full")

class AccessibilityTreeTool(BaseTool):
    """Pruned accessibility tree optimized for token usage (75-85% reduction)"""
    
    name: str = "accessibility_tree"
    description: str = """
    Returns an optimized accessibility tree with mode-specific pruning.
    - 'interactive': Only buttons, links, form elements (best for navigation)
    - 'reading': Content elements like headings and paragraphs (best for content extraction)
    - 'full': Complete tree but still optimized (use sparingly)
    Token reduction: 75-85% compared to raw accessibility tree.
    """
    args_schema: Type[BaseModel] = AccessibilityInput
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False
    
    async def _ensure_browser(self):
        """Ensure browser is initialized"""
        if not self._initialized:
            logger.info("Initializing browser for accessibility tree tool")
            self._playwright = await async_playwright().start()
            self._browser, self._context = await async_launch_browser(self._playwright, "a11y")
            self._page = await self._context.new_page()
            self._initialized = True
            logger.info("Browser initialized successfully")
    
    def _prune_tree(self, node: Dict, mode: str, depth: int = 0) -> List[Dict]:
        """Recursively prune the accessibility tree based on mode"""
        if not node or depth > 25:
            return []
        
        results = []
        role = node.get('role', '').lower()
        name = node.get('name', '')
        
        # Determine relevance based on mode
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
        
        # Create compact node if relevant
        if is_relevant and (name or role):
            compact_node = {
                'role': role,
                'name': name[:80] if name else '',
            }
            
            # Add additional attributes based on role
            if role in ['textbox', 'searchbox']:
                if 'value' in node:
                    compact_node['value'] = str(node['value'])[:50]
                    
            elif role == 'link':
                if 'value' in node:
                    compact_node['url'] = str(node['value'])[:100]
                    
            elif role == 'button':
                if 'pressed' in node:
                    compact_node['pressed'] = node['pressed']
            
            results.append(compact_node)
        
        # Process children
        for child in node.get('children', []):
            results.extend(self._prune_tree(child, mode, depth + 1))
        
        return results
    
    def _run(self, url: str, mode: AccessibilityMode = AccessibilityMode.INTERACTIVE, 
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Synchronous run - not used"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._arun(url, mode, run_manager))
        finally:
            loop.close()
    
    async def _arun(self, url: str, mode: AccessibilityMode = AccessibilityMode.INTERACTIVE, 
                    run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Execute the tool"""
        mode_val = mode.value if hasattr(mode, "value") else mode
        try:
            logger.info(f"AccessibilityTreeTool called with URL: {url}, mode: {mode_val}")
            
            await self._ensure_browser()
            
            # Navigate to URL
            logger.debug(f"Navigating to {url}")
            await self._page.goto(url, wait_until="load")
            await self._page.wait_for_timeout(2000)
            
            # Get accessibility snapshot
            logger.debug("Getting accessibility snapshot")
            snapshot = await get_accessibility_snapshot(self._page)
            
            if not snapshot:
                logger.warning("No accessibility tree available for this page")
                return json.dumps({"error": "No accessibility tree available", "url": url})
            
            # Prune the tree
            logger.debug(f"Pruning accessibility tree with mode: {mode_val}")
            pruned_tree = self._prune_tree(snapshot, mode_val)
            
            # Calculate statistics
            unique_roles = list(set(item['role'] for item in pruned_tree))
            
            result = {
                "url": url,
                "title": await self._page.title(),
                "mode": mode_val,
                "timestamp": datetime.now().isoformat(),
                "stats": {
                    "total_elements": len(pruned_tree),
                    "unique_roles": unique_roles[:10],
                    "role_count": len(unique_roles)
                },
                "elements": pruned_tree[:50],
                "usage_note": f"Use mode='interactive' for navigation, 'reading' for content extraction"
            }
            
            logger.info(f"Successfully extracted {len(pruned_tree)} elements from accessibility tree")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error in AccessibilityTreeTool: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e), "url": url, "mode": mode_val})
    
    async def find_element_by_name(self, name: str) -> List[Dict]:
        """Helper to find elements by name in current tree"""
        logger.debug(f"Searching for element with name containing: {name}")
        
        if not self._page:
            return []
        
        snapshot = await get_accessibility_snapshot(self._page)
        if not snapshot:
            return []
        
        def search_tree(node: Dict) -> List[Dict]:
            results = []
            if node.get('name') and name.lower() in node.get('name', '').lower():
                results.append({
                    'role': node.get('role'),
                    'name': node.get('name'),
                })
            for child in node.get('children', []):
                results.extend(search_tree(child))
            return results
        
        found = search_tree(snapshot)
        logger.info(f"Found {len(found)} elements matching '{name}'")
        return found
    
    async def cleanup(self):
        """Clean up browser resources"""
        logger.info("Cleaning up browser resources")
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
            self._browser = None
        elif self._context:
            try:
                await self._context.close()
            except Exception as e:
                logger.error(f"Error closing context: {e}")
            self._context = None
            
        if getattr(self, "_playwright", None):
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.error(f"Error stopping playwright: {e}")
            self._playwright = None
            
        self._page = None
        self._initialized = False

# ============== Strategy 4: File Output Tool ==============

class FileOutputInput(BaseModel):
    """Input for file output tool"""
    url: str = Field(description="URL to navigate to")
    action_name: str = Field("capture", description="Name for this capture session")

class FileOutputTool(BaseTool):
    """Saves page state to files, returns only file paths (95%+ token reduction)"""
    
    name: str = "file_output"
    description: str = """
    Saves page state (screenshot, structure, accessibility) to disk files.
    Returns ONLY file paths (~150 tokens total) instead of full page data.
    LLM can choose to read specific files if needed.
    Maximum token reduction: 95%+ per action.
    """
    args_schema: Type[BaseModel] = FileOutputInput
    
    def __init__(self, output_dir: str = "./browser_snapshots", **kwargs):
        super().__init__(**kwargs)
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(exist_ok=True)
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False
        logger.info(f"FileOutputTool initialized with output directory: {self._output_dir}")
    
    async def _ensure_browser(self):
        """Ensure browser is initialized"""
        if not self._initialized:
            logger.info("Initializing browser for file output tool")
            self._playwright = await async_playwright().start()
            self._browser, self._context = await async_launch_browser(self._playwright, "fileout")
            self._page = await self._context.new_page()
            self._initialized = True
            logger.info("Browser initialized successfully")
    
    async def _capture_page_state(self, action_name: str) -> Dict:
        """Save page state to files and return file paths"""
        timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
        base_name = f"{self._session_id}_{action_name}_{timestamp}"
        
        logger.debug(f"Capturing page state with base name: {base_name}")
        
        # 1. Save screenshot
        screenshot_path = self._output_dir / f"{base_name}.png"
        await self._page.screenshot(path=str(screenshot_path), full_page=True)
        logger.debug(f"Screenshot saved to {screenshot_path}")
        
        # 2. Save compact structure
        structure_data = await self._page.evaluate('''
            () => {
                const interactive = Array.from(document.querySelectorAll(
                    'button, a[href], input, select, textarea'
                )).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || el.value || '').trim().slice(0, 100),
                    id: el.id || '',
                    class: el.className || '',
                    visible: el.offsetParent !== null
                }));
                
                return {
                    interactive_count: interactive.length,
                    elements: interactive.slice(0, 50),
                    title: document.title,
                    url: window.location.href,
                    timestamp: new Date().toISOString()
                };
            }
        ''')
        
        structure_path = self._output_dir / f"{base_name}_structure.json"
        with open(structure_path, 'w') as f:
            json.dump(structure_data, f, indent=2)
        logger.debug(f"Structure saved to {structure_path}")
        
        # 3. Save compact accessibility tree
        accessibility = await get_accessibility_snapshot(self._page)
        
        def compact_tree(node, depth=0):
            if not node or depth > 15:
                return None
            return {
                'role': node.get('role'),
                'name': node.get('name', '')[:60],
                'children': [compact_tree(c, depth+1) for c in node.get('children', [])[:20] if compact_tree(c, depth+1)]
            }
        
        compact_a11y = compact_tree(accessibility)
        a11y_path = self._output_dir / f"{base_name}_accessibility.json"
        with open(a11y_path, 'w') as f:
            json.dump(compact_a11y, f, indent=2) if compact_a11y else f.write("{}")
        logger.debug(f"Accessibility tree saved to {a11y_path}")
        
        return {
            'action': action_name,
            'timestamp': timestamp,
            'screenshot': str(screenshot_path),
            'structure_file': str(structure_path),
            'accessibility_file': str(a11y_path),
            'summary': {
                'title': structure_data['title'],
                'interactive_elements': structure_data['interactive_count'],
                'url': structure_data['url']
            }
        }
    
    def _run(self, url: str, action_name: str = "capture", 
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Synchronous run - not used"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._arun(url, action_name, run_manager))
        finally:
            loop.close()
    
    async def _arun(self, url: str, action_name: str = "capture", 
                    run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Execute the tool"""
        try:
            logger.info(f"FileOutputTool called with URL: {url}, action: {action_name}")
            
            await self._ensure_browser()
            
            # Navigate to URL
            logger.debug(f"Navigating to {url}")
            await self._page.goto(url, wait_until="load")
            await self._page.wait_for_timeout(2000)
            
            # Capture state
            state = await self._capture_page_state(action_name)
            
            # Create result with file paths (very low token count)
            result = {
                "status": "success",
                "message": "Page state saved to files. Use file paths to access data if needed.",
                "files": {
                    "screenshot": state['screenshot'],
                    "structure": state['structure_file'],
                    "accessibility": state['accessibility_file']
                },
                "summary": state['summary'],
                "token_savings": "You received ~150 tokens instead of ~3000-5000 tokens of raw data",
                "next_steps": "You can now decide on an action without loading all the data"
            }
            
            logger.info(f"Successfully captured page state to {state['screenshot']}")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error in FileOutputTool: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e), "url": url})
    
    async def read_file(self, file_path: str) -> str:
        """Helper to read a captured file when needed"""
        try:
            logger.debug(f"Reading file: {file_path}")
            with open(file_path, 'r') as f:
                if file_path.endswith('.json'):
                    data = json.load(f)
                    return json.dumps(data, indent=2)
                else:
                    return f"Binary file saved at: {file_path}"
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {str(e)}")
            return json.dumps({"error": f"Cannot read file: {str(e)}"})
    
    async def cleanup(self):
        """Clean up browser resources"""
        logger.info("Cleaning up browser resources")
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
            self._browser = None
        elif self._context:
            try:
                await self._context.close()
            except Exception as e:
                logger.error(f"Error closing context: {e}")
            self._context = None
            
        if getattr(self, "_playwright", None):
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.error(f"Error stopping playwright: {e}")
            self._playwright = None
            
        self._page = None
        self._initialized = False

# ============== Strategy 5: Alternative Representation Tool ==============

class RepresentationInput(BaseModel):
    """Input for alternative representation tool"""
    url: str = Field(description="URL to navigate to")
    format: str = Field("markdown", description="Output format: markdown, compact, or json")

class AlternativeRepresentationTool(BaseTool):
    """Converts pages to Markdown or compact structural notation (80-95% reduction)"""
    
    name: str = "alt_representation"
    description: str = """
    Converts page content to alternative compact formats:
    - 'markdown': Clean Markdown format - best for reading comprehension (80-90% reduction)
    - 'compact': Emmet-like notation - best for structure understanding (90-95% reduction)
    - 'json': Structured JSON with only essential info - balanced approach (85-90% reduction)
    """
    args_schema: Type[BaseModel] = RepresentationInput
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False
    
    async def _ensure_browser(self):
        """Ensure browser is initialized"""
        if not self._initialized:
            logger.info("Initializing browser for alternative representation tool")
            self._playwright = await async_playwright().start()
            self._browser, self._context = await async_launch_browser(self._playwright, "altrep")
            self._page = await self._context.new_page()
            self._initialized = True
            logger.info("Browser initialized successfully")
    
    async def _to_markdown(self) -> str:
        """Convert page to Markdown"""
        logger.debug("Converting page to Markdown")
        
        markdown = await self._page.evaluate('''
            () => {
                const clone = document.body.cloneNode(true);
                const removeSelectors = ['script', 'style', 'nav', 'footer', 'aside', 'iframe', 'noscript'];
                removeSelectors.forEach(selector => {
                    clone.querySelectorAll(selector).forEach(el => el.remove());
                });
                
                function elementToMarkdown(el, depth = 0) {
                    const tag = el.tagName?.toLowerCase();
                    const text = (el.innerText || '').trim();
                    
                    if (!text || text.length === 0) return '';
                    
                    if (tag === 'h1') return `# ${text}\\n\\n`;
                    if (tag === 'h2') return `## ${text}\\n\\n`;
                    if (tag === 'h3') return `### ${text}\\n\\n`;
                    if (tag === 'h4') return `#### ${text}\\n\\n`;
                    
                    if (tag === 'a' && el.href && !el.href.startsWith('javascript:')) {
                        return `[${text.slice(0, 50)}](${el.href}) `;
                    }
                    
                    if (tag === 'button') {
                        const btnText = text.slice(0, 40);
                        return `**[BUTTON: ${btnText}]** `;
                    }
                    
                    if (tag === 'input') {
                        const type = el.type || 'text';
                        const placeholder = el.placeholder || '';
                        const value = el.value || '';
                        const display = value || placeholder;
                        return `[INPUT ${type}: ${display.slice(0, 30)}] `;
                    }
                    
                    if (tag === 'p' || tag === 'div') {
                        if (text.length > 200) {
                            return `${text.slice(0, 200)}...\\n\\n`;
                        }
                        return `${text}\\n\\n`;
                    }
                    
                    if (tag === 'li') {
                        return `- ${text.slice(0, 100)}\\n`;
                    }
                    
                    let result = '';
                    for (const child of el.children) {
                        result += elementToMarkdown(child, depth + 1);
                    }
                    
                    return result || text.slice(0, 100);
                }
                
                return elementToMarkdown(clone);
            }
        ''')
        
        # Clean up extra whitespace
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)
        markdown = re.sub(r' {2,}', ' ', markdown)
        
        # Limit length
        if len(markdown) > 4000:
            markdown = markdown[:4000] + "\n\n...[Content truncated due to length]..."
        
        logger.info(f"Converted page to Markdown ({len(markdown)} characters)")
        return markdown
    
    async def _to_compact_notation(self) -> str:
        """Convert to Emmet-like compact notation"""
        logger.debug("Converting page to compact notation")
        
        compact = await self._page.evaluate('''
            () => {
                function getCompactRepresentation(el, depth = 0, maxDepth = 3) {
                    if (depth > maxDepth) return '';
                    
                    const tag = el.tagName?.toLowerCase();
                    if (!tag || el.offsetParent === null) return '';
                    
                    const keepTags = ['div', 'section', 'article', 'main', 'nav', 
                                     'header', 'footer', 'button', 'a', 'input', 
                                     'form', 'ul', 'ol', 'table', 'h1', 'h2', 'h3'];
                    
                    if (!keepTags.includes(tag)) return '';
                    
                    let result = tag;
                    
                    if (el.id) {
                        result += `#${el.id}`;
                    } else if (el.className && typeof el.className === 'string') {
                        const classes = el.className.split(' ').filter(c => c && c.length < 20).slice(0, 2);
                        if (classes.length) {
                            result += `.${classes.join('.')}`;
                        }
                    }
                    
                    if (tag === 'button') {
                        const text = (el.innerText || '').trim().slice(0, 20);
                        if (text) result += `{${text}}`;
                    } else if (tag === 'a' && el.href && !el.href.startsWith('javascript:')) {
                        const text = (el.innerText || '').trim().slice(0, 20);
                        if (text) result += `[${text}]`;
                    } else if (tag === 'input') {
                        const type = el.type || 'text';
                        const placeholder = el.placeholder || '';
                        result += `[${type}:${placeholder.slice(0, 15)}]`;
                    } else if (tag === 'h1' || tag === 'h2' || tag === 'h3') {
                        const text = (el.innerText || '').trim().slice(0, 30);
                        if (text) result += `{${text}}`;
                    }
                    
                    const children = [];
                    let childCount = 0;
                    for (const child of el.children) {
                        if (childCount >= 10) break;
                        const childRep = getCompactRepresentation(child, depth + 1, maxDepth);
                        if (childRep) {
                            children.push(childRep);
                            childCount++;
                        }
                    }
                    
                    if (children.length) {
                        result += `>(${children.join(' + ')})`;
                    }
                    
                    return result;
                }
                
                return getCompactRepresentation(document.body, 0, 2);
            }
        ''')
        
        if len(compact) > 2000:
            compact = compact[:2000] + "...[truncated]"
        
        logger.info(f"Converted page to compact notation ({len(compact)} characters)")
        return compact
    
    async def _to_json_structure(self) -> Dict:
        """Convert to minimal JSON structure"""
        logger.debug("Converting page to JSON structure")
        
        structure = await self._page.evaluate('''
            () => {
                function getStructure(el, maxChildren = 15) {
                    const tag = el.tagName?.toLowerCase();
                    if (!tag || el.offsetParent === null) return null;
                    
                    const relevantTags = ['button', 'a', 'input', 'select', 'textarea', 
                                         'h1', 'h2', 'h3', 'p', 'form', 'nav', 'main'];
                    
                    if (!relevantTags.includes(tag) && !el.id && !el.getAttribute('role')) {
                        const children = [];
                        for (const child of el.children) {
                            const childStruct = getStructure(child);
                            if (childStruct) {
                                children.push(childStruct);
                                if (children.length >= maxChildren) break;
                            }
                        }
                        if (children.length === 1) return children[0];
                        if (children.length > 0) return { _fragment: children };
                        return null;
                    }
                    
                    const node = {
                        t: tag,
                    };
                    
                    const text = (el.innerText || '').trim();
                    if (text && text.length < 100 && !el.children.length) {
                        node.txt = text.slice(0, 60);
                    }
                    
                    if (tag === 'button' || tag === 'a' || tag === 'input' || tag === 'select') {
                        node.int = true;
                        if (tag === 'input') {
                            node.inType = el.type || 'text';
                            if (el.placeholder) node.placeholder = el.placeholder.slice(0, 30);
                        }
                        if (el.id) node.id = el.id;
                    }
                    
                    if (tag === 'h1' || tag === 'h2' || tag === 'h3') {
                        node.heading = text.slice(0, 50);
                    }
                    
                    const children = [];
                    for (const child of el.children) {
                        const childStruct = getStructure(child);
                        if (childStruct) {
                            children.push(childStruct);
                            if (children.length >= maxChildren) break;
                        }
                    }
                    
                    if (children.length) {
                        node.c = children;
                    }
                    
                    return node;
                }
                
                const result = getStructure(document.body);
                return result || { error: "No structure found" };
            }
        ''')
        
        logger.info(f"Converted page to JSON structure")
        return structure
    
    def _run(self, url: str, format: str = "markdown", 
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Synchronous run - not used"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._arun(url, format, run_manager))
        finally:
            loop.close()
    
    async def _arun(self, url: str, format: str = "markdown", 
                    run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Execute the tool"""
        try:
            logger.info(f"AlternativeRepresentationTool called with URL: {url}, format: {format}")
            
            await self._ensure_browser()
            
            # Navigate to URL
            logger.debug(f"Navigating to {url}")
            await self._page.goto(url, wait_until="load")
            await self._page.wait_for_timeout(2000)
            
            # Convert based on format
            if format == "markdown":
                content = await self._to_markdown()
                result = {
                    "format": "markdown",
                    "url": url,
                    "title": await self._page.title(),
                    "content": content,
                    "token_estimate": f"~{len(content) // 4} tokens",
                    "note": "Markdown format is best for reading and understanding content"
                }
                
            elif format == "compact":
                content = await self._to_compact_notation()
                result = {
                    "format": "compact_notation",
                    "url": url,
                    "title": await self._page.title(),
                    "content": content,
                    "token_estimate": f"~{len(content) // 4} tokens",
                    "note": "Compact notation shows page structure with minimal tokens"
                }
                
            elif format == "json":
                content = await self._to_json_structure()
                content_str = json.dumps(content, indent=2)
                result = {
                    "format": "json_structure",
                    "url": url,
                    "title": await self._page.title(),
                    "content": content,
                    "token_estimate": f"~{len(content_str) // 4} tokens",
                    "note": "JSON structure provides a balanced representation"
                }
                
            else:
                error_msg = f"Unknown format: {format}. Use 'markdown', 'compact', or 'json'"
                logger.error(error_msg)
                return json.dumps({"error": error_msg})
            
            logger.info(f"Successfully converted page to {format} format")
            return json.dumps(result, indent=2)
            
        except Exception as e:
            logger.error(f"Error in AlternativeRepresentationTool: {str(e)}", exc_info=True)
            return json.dumps({"error": str(e), "url": url, "format": format})
    
    async def cleanup(self):
        """Clean up browser resources"""
        logger.info("Cleaning up browser resources")
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.error(f"Error closing browser: {e}")
            self._browser = None
        elif self._context:
            try:
                await self._context.close()
            except Exception as e:
                logger.error(f"Error closing context: {e}")
            self._context = None
            
        if getattr(self, "_playwright", None):
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.error(f"Error stopping playwright: {e}")
            self._playwright = None
            
        self._page = None
        self._initialized = False

# ============== Combined Browser Manager ==============

class BrowserAgentManager:
    """Manages all browser tools and provides unified interface"""
    
    def __init__(self):
        self.tools = []
        self.semantic_tool = None
        self.diffing_tool = None
        self.accessibility_tool = None
        self.file_output_tool = None
        self.alt_representation_tool = None
        
        logger.info("Initializing BrowserAgentManager")
        self._initialize_tools()
    
    def _initialize_tools(self):
        """Initialize all tools"""
        self.semantic_tool = SemanticSnapshotTool()
        self.diffing_tool = IncrementalDiffingTool()
        self.accessibility_tool = AccessibilityTreeTool()
        self.file_output_tool = FileOutputTool()
        self.alt_representation_tool = AlternativeRepresentationTool()
        
        self.tools = [
            self.semantic_tool,
            self.diffing_tool,
            self.accessibility_tool,
            self.file_output_tool,
            self.alt_representation_tool
        ]
        
        logger.info(f"Initialized {len(self.tools)} browser tools")
    
    def get_tools(self) -> List[BaseTool]:
        """Get all tools for use with LangChain agent"""
        return self.tools
    
    async def cleanup_all(self):
        """Clean up all browser resources"""
        logger.info("Cleaning up all browser resources")
        for tool in self.tools:
            if hasattr(tool, 'cleanup'):
                await tool.cleanup()
        logger.info("All browser resources cleaned up")
    
    async def execute_semantic_action(self, stable_id: str, action: str, value: str = None) -> str:
        """Execute action using semantic snapshot tool"""
        return await self.semantic_tool.execute_action(stable_id, action, value)
    
    async def read_file_output(self, file_path: str) -> str:
        """Read a file from file output tool"""
        return await self.file_output_tool.read_file(file_path)
    
    async def find_accessibility_element(self, name: str) -> List[Dict]:
        """Find element by name in accessibility tree"""
        return await self.accessibility_tool.find_element_by_name(name)

# ============== Example Usage ==============

async def example_usage():
    """Example showing how to use all tools with LangChain"""
    
    # Load env for API keys to count tokens accurately
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.env"))
    
    # Initialize model to get exact token counts from API
    provider = os.getenv("LLM_PROVIDER")
    if not provider:
        provider = "deepseek" if os.getenv("DEEPSEEK_API_KEY") else "google"
    provider = provider.lower()

    model = None
    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            try:
                from langchain_deepseek import ChatDeepSeek
                model = ChatDeepSeek(
                    model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                    api_key=api_key,
                    api_base=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
                    temperature=0.0
                )
                logger.info("Initialized DeepSeek model for token counting")
            except Exception as e:
                logger.warning(f"Could not initialize DeepSeek model for token counting: {e}")
    elif provider == "local":
        api_base = os.getenv("LOCAL_API_BASE", "http://localhost:11434/v1")
        model_name = os.getenv("LOCAL_MODEL", "qwen2.5")
        api_key = os.getenv("LOCAL_API_KEY", "local")
        try:
            from langchain_openai import ChatOpenAI
            model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=api_base,
                temperature=0.0
            )
            logger.info("Initialized Local model for token counting")
        except Exception as e:
            logger.warning(f"Could not initialize Local model for token counting: {e}")
    else:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if api_key:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=api_key)
                logger.info("Initialized Gemini model for token counting")
            except Exception as e:
                logger.warning(f"Could not initialize Gemini model for token counting: {e}")
            
    def get_token_count(content: str) -> int:
        if model:
            try:
                return model.get_num_tokens(content)
            except Exception:
                pass
        # Fallback estimation: approx 4 chars per token
        return len(content) // 4

    def save_and_log_implementation(name: str, raw_result: str, elements_count: int, count_label: str = "interactive elements"):
        # Format JSON nicely
        try:
            parsed = json.loads(raw_result)
            formatted_json = json.dumps(parsed, indent=4)
        except Exception:
            parsed = None
            formatted_json = raw_result
            
        # Define output path
        output_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(output_dir, f"{name}.json")
        
        # Save to file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(formatted_json)
            
        # Calculate tokens
        tokens_full = get_token_count(formatted_json)
        
        # Log details
        print(f"  - Gathered/processed: {elements_count} {count_label}")
        print(f"  - Saved JSON output to: {output_path}")
        
        if parsed and "element_map" in parsed:
            # For demonstration, show token cost with and without the private element map
            parsed_clean = parsed.copy()
            del parsed_clean["element_map"]
            formatted_clean = json.dumps(parsed_clean, indent=4)
            tokens_clean = get_token_count(formatted_clean)
            print(f"  - Estimated API input token cost (saved file with element map): {tokens_full} tokens")
            print(f"  - ACTUAL API input token cost sent to LLM (omitting element map): {tokens_clean} tokens")
        else:
            print(f"  - Estimated API input token cost: {tokens_full} tokens")
        print("-" * 50)

    # Initialize manager
    manager = BrowserAgentManager()
    
    print("=" * 80)
    print("BROWSER AGENT TOOLS DEMONSTRATION")
    print("=" * 80)
    
    try:
        # Example 1: Semantic Snapshot (best for navigation)
        print("\n1. Using Semantic Snapshot Tool (70-90% token reduction)")
        print("-" * 50)
        result = await manager.semantic_tool._arun("https://naukri.com")
        data = json.loads(result)
        # Inject the element map for the saved file on disk so the user has the mappings
        data['element_map'] = manager.semantic_tool._element_map
        save_and_log_implementation(
            name="semantic_snapshot",
            raw_result=json.dumps(data),
            elements_count=data.get('total_elements', 0),
            count_label="interactive elements"
        )
        
        # Example 6: Original JS-based Extraction (from browser_tools.py)
        # Evaluated while semantic_tool browser is still active to avoid multiple open contexts
        print("\n6. Using Original JS-based Buttons Tool (from browser_tools.py)")
        print("-" * 50)
        js_code = """
        () => {
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
                let text = el.innerText ? el.innerText.trim() : "";
                if (!text) {
                    text = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('placeholder') || "";
                    text = text.trim();
                }
                if (text.length > 100) {
                    text = text.substring(0, 100) + "...";
                }
                let standardSelector = el.id ? `#${el.id}` : el.tagName.toLowerCase();
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
        raw_buttons = await manager.semantic_tool._page.evaluate(js_code)
        save_and_log_implementation(
            name="original_js_buttons",
            raw_result=json.dumps(raw_buttons, indent=4),
            elements_count=len(raw_buttons),
            count_label="interactable buttons"
        )
        await manager.semantic_tool.cleanup()  # Cleanup first browser context
        
        # Example 2: Incremental Diffing (great for multi-step workflows)
        print("\n2. Using Incremental Diffing Tool (90-95% reduction after first call)")
        print("-" * 50)
        diff1 = await manager.diffing_tool._arun("https://naukri.com")
        print("First call: Full snapshot taken and cached.")
        diff2 = await manager.diffing_tool._arun("https://naukri.com", reset=False)
        diff_data = json.loads(diff2)
        save_and_log_implementation(
            name="incremental_diff",
            raw_result=diff2,
            elements_count=diff_data.get('stats', {}).get('elements_added', 0),
            count_label="changed/added elements"
        )
        await manager.diffing_tool.cleanup()  # Cleanup second browser context
        
        # Example 3: Accessibility Tree (best for accessibility compliance)
        print("\n3. Using Accessibility Tree Tool (75-85% reduction)")
        print("-" * 50)
        a11y = await manager.accessibility_tool._arun("https://naukri.com", mode="interactive")
        a11y_data = json.loads(a11y)
        save_and_log_implementation(
            name="accessibility_tree",
            raw_result=a11y,
            elements_count=a11y_data.get('stats', {}).get('total_elements', 0),
            count_label="accessible elements"
        )
        await manager.accessibility_tool.cleanup()  # Cleanup third browser context
        
        # Example 4: File Output (maximum token savings)
        print("\n4. Using File Output Tool (95%+ token reduction)")
        print("-" * 50)
        files = await manager.file_output_tool._arun("https://naukri.com", action_name="demo")
        files_data = json.loads(files)
        save_and_log_implementation(
            name="file_output",
            raw_result=files,
            elements_count=files_data.get('summary', {}).get('interactive_elements', 0),
            count_label="elements recorded in structure file"
        )
        await manager.file_output_tool.cleanup()  # Cleanup fourth browser context
        
        # Example 5: Alternative Representations
        print("\n5. Using Alternative Representation Tool (80-95% reduction)")
        print("-" * 50)
        markdown_result = await manager.alt_representation_tool._arun("https://naukri.com", format="markdown")
        markdown_data = json.loads(markdown_result)
        content_preview = markdown_data.get('content', '')
        word_count = len(content_preview.split())
        save_and_log_implementation(
            name="alt_representation",
            raw_result=markdown_result,
            elements_count=word_count,
            count_label="words in markdown representation"
        )
        await manager.alt_representation_tool.cleanup()  # Cleanup fifth browser context
        
        print("\n" + "=" * 80)
        print("DEMONSTRATION COMPLETE")
        print("=" * 80)
        
    finally:
        # Cleanup
        await manager.cleanup_all()

# ============== Main Entry Point ==============

if __name__ == "__main__":
    # Install required packages if not present
    print("Checking dependencies...")
    print("Make sure you have installed:")
    print("  pip install langchain langchain-core playwright pydantic")
    print("  playwright install chromium")
    print()
    
    # Run the example
    asyncio.run(example_usage())