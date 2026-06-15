import os
import sys
import json
import unittest
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure browser_agent is on path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from accessibility_tree import (
    AccessibilityTreeTool,
    AccessibilityMode,
    get_accessibility_snapshot,
)

class TestAccessibilityTreeUnit(unittest.TestCase):
    def setUp(self):
        self.tool = AccessibilityTreeTool()

    def test_prune_tree_interactive_mode(self):
        # Create a mock accessibility tree
        mock_tree = {
            "role": "RootWebArea",
            "name": "Test Page",
            "children": [
                {
                    "role": "heading",
                    "name": "Main Heading",
                    "children": []
                },
                {
                    "role": "button",
                    "name": "Submit Button",
                    "pressed": True,
                    "children": []
                },
                {
                    "role": "paragraph",
                    "name": "Some text content here.",
                    "children": []
                },
                {
                    "role": "textbox",
                    "name": "Username Input",
                    "value": "user123",
                    "children": []
                },
                {
                    "role": "link",
                    "name": "Google",
                    "value": "https://google.com",
                    "children": []
                }
            ]
        }
        
        # In interactive mode, headings and paragraphs should be pruned.
        # Buttons, textboxes, and links should remain.
        pruned = self.tool._prune_tree(mock_tree, "interactive")
        
        # Let's count matching roles
        roles = [elem["role"] for elem in pruned]
        self.assertIn("button", roles)
        self.assertIn("textbox", roles)
        self.assertIn("link", roles)
        self.assertNotIn("heading", roles)
        self.assertNotIn("paragraph", roles)
        
        # Verify custom attributes are retained/truncated
        button_elem = next(e for e in pruned if e["role"] == "button")
        self.assertEqual(button_elem["name"], "Submit Button")
        self.assertTrue(button_elem.get("pressed"))
        
        textbox_elem = next(e for e in pruned if e["role"] == "textbox")
        self.assertEqual(textbox_elem["value"], "user123")
        
        link_elem = next(e for e in pruned if e["role"] == "link")
        self.assertEqual(link_elem["url"], "https://google.com")

    def test_prune_tree_reading_mode(self):
        mock_tree = {
            "role": "RootWebArea",
            "name": "Test Page",
            "children": [
                {
                    "role": "heading",
                    "name": "Main Heading",
                    "children": []
                },
                {
                    "role": "button",
                    "name": "Submit Button",
                    "children": []
                },
                {
                    "role": "paragraph",
                    "name": "Some text content here.",
                    "children": []
                },
                {
                    "role": "textbox",
                    "name": "Username Input",
                    "children": []
                }
            ]
        }
        
        # In reading mode, headings, paragraphs, buttons, etc. are relevant.
        # Textboxes are not typically in reading content roles.
        pruned = self.tool._prune_tree(mock_tree, "reading")
        roles = [elem["role"] for elem in pruned]
        self.assertIn("heading", roles)
        self.assertIn("paragraph", roles)
        self.assertIn("button", roles)
        self.assertNotIn("textbox", roles)

    def test_prune_tree_full_mode(self):
        mock_tree = {
            "role": "RootWebArea",
            "name": "Test Page",
            "children": [
                {
                    "role": "heading",
                    "name": "Main Heading",
                    "children": []
                },
                {
                    "role": "paragraph",
                    "name": "Some text content here.",
                    "children": []
                }
            ]
        }
        
        pruned = self.tool._prune_tree(mock_tree, "full")
        roles = [elem["role"] for elem in pruned]
        self.assertIn("heading", roles)
        self.assertIn("paragraph", roles)
        self.assertIn("rootwebarea", roles) # In full mode, the root is relevant too

    def test_prune_tree_depth_limit(self):
        # Build nested node structure deeper than 25 levels
        curr = {"role": "button", "name": "Deep Button", "children": []}
        for _ in range(30):
            curr = {"role": "button", "name": "Wrapper", "children": [curr]}
            
        pruned = self.tool._prune_tree(curr, "full")
        # Depth > 25 should return empty or not traverse below depth 25
        self.assertEqual(len(pruned), 26)

    def test_prune_tree_truncation(self):
        long_name = "A" * 150
        long_val = "B" * 150
        mock_tree = {
            "role": "textbox",
            "name": long_name,
            "value": long_val,
            "children": []
        }
        pruned = self.tool._prune_tree(mock_tree, "interactive")
        self.assertEqual(len(pruned), 1)
        self.assertEqual(len(pruned[0]["name"]), 80)
        self.assertEqual(len(pruned[0]["value"]), 50)


class TestAccessibilityTreeAsync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tool = AccessibilityTreeTool()

    async def asyncTearDown(self):
        await self.tool.cleanup()

    @patch("accessibility_tree.get_accessibility_snapshot")
    async def test_find_element_by_name(self, mock_snapshot_fn):
        # Test finding element when page is None
        self.tool._page = None
        elements = await self.tool.find_element_by_name("test")
        self.assertEqual(elements, [])

        # Mock page
        self.tool._page = MagicMock()
        
        # Mock snapshot returning simple tree
        mock_snapshot_fn.return_value = {
            "role": "RootWebArea",
            "name": "Home",
            "children": [
                {
                    "role": "button",
                    "name": "Submit Registration",
                    "children": []
                },
                {
                    "role": "link",
                    "name": "About Us Link",
                    "children": []
                }
            ]
        }
        
        # Test case-insensitive substring match
        found = await self.tool.find_element_by_name("submit")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["role"], "button")
        self.assertEqual(found[0]["name"], "Submit Registration")

        found_both = await self.tool.find_element_by_name("us")
        self.assertEqual(len(found_both), 1)
        self.assertEqual(found_both[0]["role"], "link")
        
        found_none = await self.tool.find_element_by_name("nonexistent")
        self.assertEqual(found_none, [])


class TestAccessibilityTreeIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Force headless mode and non-persistent context for automated testing
        self.old_headless = os.environ.get("BROWSER_HEADLESS")
        self.old_persistent = os.environ.get("USE_PERSISTENT_CONTEXT")
        os.environ["BROWSER_HEADLESS"] = "true"
        os.environ["USE_PERSISTENT_CONTEXT"] = "false"
        
        self.tool = AccessibilityTreeTool()
        
        # Create a temporary HTML file for testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.html_file = Path(self.temp_dir.name) / "test.html"
        
        self.html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Accessibility Test Page</title>
        </head>
        <body>
            <h1>Welcome to the Accessibility Test</h1>
            <p>This is a paragraph description of the test.</p>
            <form>
                <label for="username">Username:</label>
                <input type="text" id="username" name="username" value="test_user" placeholder="Enter username">
                
                <button type="button" id="submit-btn">Click Me!</button>
            </form>
            <a href="https://example.com/about">About Us Page</a>
        </body>
        </html>
        """
        self.html_file.write_text(self.html_content, encoding="utf-8")
        self.file_url = self.html_file.absolute().as_uri()

    async def asyncTearDown(self):
        await self.tool.cleanup()
        self.temp_dir.cleanup()
        
        # Restore environment variables
        if self.old_headless is not None:
            os.environ["BROWSER_HEADLESS"] = self.old_headless
        else:
            os.environ.pop("BROWSER_HEADLESS", None)
            
        if self.old_persistent is not None:
            os.environ["USE_PERSISTENT_CONTEXT"] = self.old_persistent
        else:
            os.environ.pop("USE_PERSISTENT_CONTEXT", None)

    async def test_integration_run_modes(self):
        # We run the tool end-to-end using the local file URL.
        # Run with 'interactive' mode
        json_result_interactive = await self.tool._arun(self.file_url, mode=AccessibilityMode.INTERACTIVE)
        result_interactive = json.loads(json_result_interactive)
        
        # Check basic fields
        self.assertEqual(result_interactive["url"], self.file_url)
        self.assertEqual(result_interactive["title"], "Accessibility Test Page")
        self.assertEqual(result_interactive["mode"], "interactive")
        
        # Verify stats and basic extraction works without crashing
        self.assertIn("stats", result_interactive)
        self.assertTrue(result_interactive["stats"]["total_elements"] >= 0)

        # Run with 'reading' mode
        json_result_reading = await self.tool._arun(self.file_url, mode=AccessibilityMode.READING)
        result_reading = json.loads(json_result_reading)
        self.assertEqual(result_reading["mode"], "reading")
        
        # Search element by name using the helper in active browser context
        found_elements = await self.tool.find_element_by_name("Click Me")
        # Check that we found the button element (or similar role depending on rendering)
        self.assertTrue(len(found_elements) > 0)
        self.assertTrue(any(e["role"] is not None for e in found_elements))

if __name__ == "__main__":
    unittest.main()
