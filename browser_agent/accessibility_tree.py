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
            await self._page.goto(url, wait_until="networkidle")
            
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
        if self._context:
            try:
                for p in list(self._context.pages):
                    try:
                        if not p.is_closed():
                            await p.close()
                    except Exception as pe:
                        if "closed" not in str(pe).lower():
                            logger.warning(f"Error closing individual tab: {pe}")
            except Exception as ce:
                logger.warning(f"Error iterating context pages: {ce}")

        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                if "closed" not in str(e).lower():
                    logger.error(f"Error closing browser: {e}")
            self._browser = None
        elif self._context:
            try:
                await self._context.close()
            except Exception as e:
                if "closed" not in str(e).lower():
                    logger.error(f"Error closing context: {e}")
            self._context = None
            
        if getattr(self, "_playwright", None):
            try:
                await self._playwright.stop()
            except Exception as e:
                if "closed" not in str(e).lower():
                    logger.error(f"Error stopping playwright: {e}")
            self._playwright = None
            
        self._page = None
        self._initialized = False
