"""
uia_tools.py — Windows UI Automation diagnostic utilities for the browser agent.

Merged from:
  - uia_reference.py   (console tree printer, lightweight connect)
  - uia_browser_dump.py (JSON dumper, node finder, cursor demo via PersistentBrowserManager)

Usage (standalone):
  python uia_tools.py              # default: print tree to console
  python uia_tools.py --mode print # print tree to console
  python uia_tools.py --mode dump  # launch browser, dump tree to JSON, run cursor demo
"""

import os
import sys
import time
import json
import argparse

import uiautomation as auto


# ---------------------------------------------------------------------------
# Tree traversal helpers
# ---------------------------------------------------------------------------

def dump_tree(control, depth=0):
    """
    Recursively print the UI Automation tree to stdout.
    Useful for quick visual inspection without writing any files.
    """
    indent = "  " * depth
    try:
        rect = control.BoundingRectangle
        print(
            f"{indent}"
            f"{control.ControlTypeName:<15} | "
            f"Name='{control.Name}' | "
            f"AutomationId='{control.AutomationId}' | "
            f"Class='{control.ClassName}' | "
            f"Rect=({rect.left},{rect.top},{rect.right},{rect.bottom})"
        )
    except Exception as e:
        print(f"{indent}<Error reading control: {e}>")

    try:
        for child in control.GetChildren():
            dump_tree(child, depth + 1)
    except Exception:
        pass


def dump_tree_to_dict(control, depth=0, max_depth=12):
    """
    Recursively serialise the UI Automation tree to a JSON-compatible dict.
    Elements with all-zero bounding rectangles (hidden / not rendered) are skipped.
    """
    if depth > max_depth:
        return None

    rect_dict = None
    try:
        rect = control.BoundingRectangle
        if rect.left == 0 and rect.top == 0 and rect.right == 0 and rect.bottom == 0:
            return None
        rect_dict = {
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
        }
    except Exception:
        pass

    node = {
        "ControlTypeName": control.ControlTypeName,
        "Name": control.Name,
        "AutomationId": control.AutomationId,
        "ClassName": control.ClassName,
        "Rect": rect_dict,
        "Children": [],
    }

    try:
        for child in control.GetChildren():
            child_node = dump_tree_to_dict(child, depth + 1, max_depth)
            if child_node:
                node["Children"].append(child_node)
    except Exception:
        pass

    return node


# ---------------------------------------------------------------------------
# Browser window connection
# ---------------------------------------------------------------------------

def connect_to_browser(retries=5, retry_delay=1.0):
    """
    Find the first Chromium-based browser window (Brave / Chrome).

    Retries up to *retries* times with *retry_delay* seconds between attempts
    to allow the window time to appear after launch.

    Returns the window control, or None if not found.
    """
    desktop = auto.GetRootControl()
    for attempt in range(retries):
        for window in desktop.GetChildren():
            try:
                if window.ClassName == "Chrome_WidgetWin_1":
                    print(f"\n[UIAutomation] Connected to window: '{window.Name}' "
                          f"(Class: {window.ClassName})\n")
                    return window
            except Exception:
                pass
        if attempt < retries - 1:
            time.sleep(retry_delay)
    return None


# ---------------------------------------------------------------------------
# Node search
# ---------------------------------------------------------------------------

def find_node(node, identifier):
    """
    Recursively search a tree dict (produced by dump_tree_to_dict) for a node
    whose Name or ClassName matches *identifier*.

    Returns the first matching node dict, or None.
    """
    if not node:
        return None
    if node.get("Name") == identifier or node.get("ClassName") == identifier:
        return node
    for child in node.get("Children", []):
        result = find_node(child, identifier)
        if result:
            return result
    return None


# ---------------------------------------------------------------------------
# __main__ entry points
# ---------------------------------------------------------------------------

def _run_print_mode():
    """Print the live UI Automation tree of the browser to stdout."""
    # Remove the script's own directory from sys.path so that 'uiautomation'
    # refers to the installed library and not any local file with that name.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir in sys.path:
        sys.path.remove(script_dir)

    auto.SetGlobalSearchTimeout(5)
    browser = connect_to_browser(retries=1)
    if browser is None:
        print("No Chromium browser window found.")
        sys.exit(1)

    browser.SetActive()
    print("=" * 120)
    print("UI Automation Tree")
    print("=" * 120)
    dump_tree(browser)


def _run_dump_mode():
    """
    Launch the browser via PersistentBrowserManager, dump the UI Automation
    tree to outputs/browser_uia_tree.json, then run a cursor demo on key
    Brave UI elements.
    """
    from dotenv import load_dotenv
    load_dotenv()

    os.environ["BROWSER_INCOGNITO"] = "false"

    # Import here so the module stays usable without Playwright installed
    from browser_tools import PersistentBrowserManager

    print("Launching Brave browser via PersistentBrowserManager...")
    manager = PersistentBrowserManager.get_instance()

    try:
        page = manager.get_page()
        print("Navigating to google.com...")
        page.goto("https://www.google.com", wait_until="load")
        page.wait_for_timeout(3000)

        auto.SetGlobalSearchTimeout(5)
        print("Searching for browser window via UI Automation...")
        browser_win = connect_to_browser()
        if browser_win is None:
            print("Error: No Chromium/Brave browser window found.")
            sys.exit(1)

        browser_win.SetActive()

        print("Dumping UI Automation tree...")
        tree_dict = dump_tree_to_dict(browser_win, max_depth=12)

        outputs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
        os.makedirs(outputs_dir, exist_ok=True)
        output_file = os.path.join(outputs_dir, "browser_uia_tree.json")

        print(f"Saving tree to: {output_file}")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(tree_dict, f, indent=2, ensure_ascii=False)
        print("Tree saved successfully.")

        # Cursor demo — move to the bottom edge of each target element
        import pyautogui

        targets = [
            "DataProtectionOverlayView",
            "BraveContentsContainerOutline",
            "BraveInfoBarContainerView",
            "You are using an unsupported command-line flag: --no-sandbox. "
            "Stability and security will suffer.",
        ]

        for target in targets:
            print(f"\nSearching for: '{target}'...")
            target_node = find_node(tree_dict, target)
            if target_node and target_node.get("Rect"):
                rect = target_node["Rect"]
                print(f"  Found at Rect: {rect}")
                x = (rect["left"] + rect["right"]) // 2
                y = rect["bottom"]
                print(f"  Moving cursor to bottom-centre: ({x}, {y})")
                pyautogui.moveTo(x, y, duration=1.0)
                print("  Holding for 3 seconds...")
                time.sleep(3.0)
            else:
                print(f"  Warning: '{target}' not found in tree.")

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        print("Shutting down browser...")
        try:
            manager.close()
        except Exception as e:
            print(f"Error shutting down: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UI Automation browser diagnostic tools.")
    parser.add_argument(
        "--mode",
        choices=["print", "dump"],
        default="print",
        help=(
            "print: print the live UIA tree to stdout (default). "
            "dump: launch browser, save tree to JSON, run cursor demo."
        ),
    )
    args = parser.parse_args()

    if args.mode == "dump":
        _run_dump_mode()
    else:
        _run_print_mode()
