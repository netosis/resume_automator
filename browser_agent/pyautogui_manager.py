import os
import time
import math
import random
from typing import Optional
from playwright.sync_api import Page

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.01
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False

try:
    import pygetwindow as gw
    _PYGETWINDOW_AVAILABLE = True
except ImportError:
    _PYGETWINDOW_AVAILABLE = False


class PyAutoGUIManager:
    """
    Singleton manager for executing PyAutoGUI mouse, keyboard, or scroll actions.
    Converts Playwright viewport coordinates to absolute monitor coordinates, using Bezier 
    curves for human-like mouse movement, and realistic typing delays.
    Falls back to native Playwright actions if PyAutoGUI is unavailable or in headless mode.
    """
    _instance: Optional['PyAutoGUIManager'] = None

    def __init__(self):
        self.is_headless = os.environ.get("HEADLESS", "false").lower() == "true"
        self.available = _PYAUTOGUI_AVAILABLE and not self.is_headless

    @classmethod
    def get_instance(cls) -> 'PyAutoGUIManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_chrome_offset(self, page: Page):
        """
        Returns the pixel offset caused by browser chrome
        (tabs + address bar + bookmarks bar), dynamically,
        so it adjusts automatically if bookmarks bar is shown/hidden,
        zoom level changes, etc.
        """
        offset = page.evaluate("""
            () => ({
                x: window.outerWidth - window.innerWidth,
                y: window.outerHeight - window.innerHeight
            })
        """)
        # Using user's provided logic for offset
        # Note: on Windows, x difference is both left+right borders.
        # We will return it as is per the prompt, though we might divide by 2 in the addition.
        return offset["x"], offset["y"]

    def get_browser_window_origin(self, page: Page):
        """
        Finds the actual OS-level window position of the browser
        (its top-left corner on screen), not the page viewport.
        """
        if not _PYGETWINDOW_AVAILABLE:
            print("[PyAutoGUI] pygetwindow not available, assuming (0,0)")
            return 0, 0
            
        title_substring = page.title()
        if not title_substring:
            title_substring = "Brave"
            
        matches = [w for w in gw.getAllTitles() if title_substring.lower() in w.lower()]
        if not matches:
            # Fallback to general browser titles
            matches = [w for w in gw.getAllTitles() if "brave" in w.lower() or "chrome" in w.lower() or "firefox" in w.lower()]
            
        if not matches:
            print(f"[PyAutoGUI] No window found matching '{title_substring}'")
            return 0, 0
            
        win = gw.getWindowsWithTitle(matches[0])[0]

        # Bring it to front so coordinates are accurate / clicking works
        if win.isMinimized:
            win.restore()
        win.activate()

        return win.left, win.top

    def move_and_click(self, page: Page, x: float, y: float):
        if not self.available:
            print("[PyAutoGUI] Library not available or browser is headless. Falling back to Playwright native interactions.")
            page.mouse.move(x, y)
            page.mouse.click(x, y)
            return

        # Convert viewport coordinates to absolute monitor coordinates using requested logic
        win_x, win_y = self.get_browser_window_origin(page)
        chrome_x, chrome_y = self.get_chrome_offset(page)

        end_x = int(win_x + chrome_x + x)
        end_y = int(win_y + chrome_y + y)
        
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
                cx = (u**3 * p0[0] + 3 * u**2 * t_eased * p1[0] + 3 * u * t_eased**2 * p2[0] + t_eased**3 * p3[0])
                cy = (u**3 * p0[1] + 3 * u**2 * t_eased * p1[1] + 3 * u * t_eased**2 * p2[1] + t_eased**3 * p3[1])
                
                jitter_factor = math.sin(math.pi * t)
                jitter_x = random.uniform(-2, 2) * jitter_factor
                jitter_y = random.uniform(-2, 2) * jitter_factor
                
                pyautogui.moveTo(int(cx + jitter_x), int(cy + jitter_y))
                time.sleep(random.uniform(0.005, 0.015))
            
            pyautogui.moveTo(end_x, end_y)
            time.sleep(random.uniform(0.001, 0.003))
        
        page.mouse.click(x, y)

    def type_text(self, page: Page, text: str):
        if not self.available:
            print("[PyAutoGUI] Library not available or browser is headless. Falling back to Playwright native interactions.")
            page.keyboard.type(text)
            return

        for char in text:
            pyautogui.write(char)
            time.sleep(random.uniform(0.03, 0.1))
            
    def press_key(self, page: Page, key: str):
        if not self.available:
            print("[PyAutoGUI] Library not available or browser is headless. Falling back to Playwright native interactions.")
            page.keyboard.press(key)
            return

        key_map = {
            "Enter": "enter",
            "Backspace": "backspace",
            "Tab": "tab",
            "Control+A": "ctrl+a",
            "Escape": "esc",
            "Control+W": "ctrl+w"
        }
        pyautogui_key = key_map.get(key, key.lower())
        if "+" in pyautogui_key:
            keys = pyautogui_key.split("+")
            pyautogui.hotkey(*keys)
        else:
            pyautogui.press(pyautogui_key)
        time.sleep(random.uniform(0.1, 0.3))
        
    def scroll(self, page: Page, amount: int):
        if not self.available:
            print("[PyAutoGUI] Library not available or browser is headless. Falling back to Playwright native interactions.")
            if amount > 0:
                page.mouse.wheel(0, -amount * 10)
            else:
                page.mouse.wheel(0, -amount * 10)
            return

        pyautogui.scroll(amount)
        time.sleep(random.uniform(0.2, 0.4))

    def execute_action(self, page: Page, action_type: str, **kwargs):
        """Wrapper method for backward compatibility."""
        if action_type == "move_and_click":
            x = kwargs.get("x")
            y = kwargs.get("y")
            if x is not None and y is not None:
                self.move_and_click(page, x, y)
        elif action_type == "type":
            self.type_text(page, kwargs.get("text", ""))
        elif action_type == "press":
            self.press_key(page, kwargs.get("key", ""))
        elif action_type == "scroll":
            self.scroll(page, kwargs.get("scroll_amount", 0))
