import os
import sys
import json
import unittest
import tempfile
from pathlib import Path

# Ensure browser_agent is on path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_tools import (
    get_compressed_dom,
    get_compressed_dom_info,
    PersistentBrowserManager
)

class TestDOMCompressionIntegration(unittest.TestCase):
    def setUp(self):
        # Force headless mode and non-persistent context for automated testing
        self.old_headless = os.environ.get("BROWSER_HEADLESS")
        self.old_persistent = os.environ.get("USE_PERSISTENT_CONTEXT")
        self.old_incognito = os.environ.get("BROWSER_INCOGNITO")
        
        os.environ["BROWSER_HEADLESS"] = "true"
        os.environ["USE_PERSISTENT_CONTEXT"] = "false"
        os.environ["BROWSER_INCOGNITO"] = "true"
        
        # Create a temporary HTML file for testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.html_file = Path(self.temp_dir.name) / "test_dom.html"
        
        self.html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>DOM Compression Test Page</title>
            <style>
                .hidden { display: none; }
                .invisible { visibility: hidden; }
            </style>
        </head>
        <body>
            <h1>Welcome to the DOM Test</h1>
            <p>This is a paragraph description of the DOM test page.</p>
            <div class="hidden">
                <button id="hidden-btn">Hidden Button</button>
            </div>
            <div class="invisible">
                <a href="/invisible">Invisible Link</a>
            </div>
            <form>
                <label for="username">Username:</label>
                <input type="text" id="username" name="username" value="dom_user" placeholder="Enter username">
                
                <button type="button" id="submit-btn">Click Me!</button>
                <select id="gender">
                    <option value="male">Male</option>
                    <option value="female">Female</option>
                </select>
            </form>
            <a href="https://example.com/about">About Us Page</a>
        </body>
        </html>
        """
        self.html_file.write_text(self.html_content, encoding="utf-8")
        self.file_url = self.html_file.absolute().as_uri()

    def tearDown(self):
        try:
            manager = PersistentBrowserManager.get_instance()
            manager.close()
        except Exception:
            pass
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

        if self.old_incognito is not None:
            os.environ["BROWSER_INCOGNITO"] = self.old_incognito
        else:
            os.environ.pop("BROWSER_INCOGNITO", None)

    def test_dom_compression_modes(self):
        # Open page first using sync Playwright or open_website tool
        from browser_tools import open_website
        open_website.invoke({"url": self.file_url, "mode": "dom_interactive"})
        
        # Reset cache in the browser_tools module namespace to force a fresh retrieval
        import browser_tools as browser_tools
        browser_tools._LAST_DOM_STATE = {
            "url": None,
            "mode": None,
            "json": None
        }
        
        # 1. Test DOM interactive mode
        dom_interactive_res = get_compressed_dom.invoke({"mode": "interactive"})
        self.assertNotEqual(dom_interactive_res, "Failed to retrieve compressed DOM.")
        self.assertNotEqual(dom_interactive_res, False)
        
        interactive_data = json.loads(dom_interactive_res)
        self.assertEqual(interactive_data["mode"], "interactive")
        
        elements = interactive_data["elements"]
        tags = [e["tag"] for e in elements]
        
        # Interactive elements should be present
        self.assertIn("input", tags)
        self.assertIn("button", tags)
        self.assertIn("select", tags)
        self.assertIn("a", tags)
        
        # Hidden and invisible elements should NOT be present
        ids = [e.get("id", "") for e in elements]
        self.assertNotIn("hidden-btn", ids)
        
        # Non-interactive elements like headings/paragraphs should NOT be present in interactive mode
        self.assertNotIn("h1", tags)
        self.assertNotIn("p", tags)
        
        # Check that attributes like value/placeholder are present
        input_elem = next(e for e in elements if e["tag"] == "input")
        self.assertEqual(input_elem.get("value"), "dom_user")
        self.assertEqual(input_elem.get("placeholder"), "Enter username")

        # Reset cache again to force a fresh retrieval for reading mode
        browser_tools._LAST_DOM_STATE = {
            "url": None,
            "mode": None,
            "json": None
        }

        # 2. Test DOM reading mode
        dom_reading_res = get_compressed_dom.invoke({"mode": "reading"})
        self.assertNotEqual(dom_reading_res, False)
        
        reading_data = json.loads(dom_reading_res)
        self.assertEqual(reading_data["mode"], "reading")
        
        reading_tags = [e["tag"] for e in reading_data["elements"]]
        self.assertIn("h1", reading_tags)
        self.assertIn("p", reading_tags)
        self.assertIn("input", reading_tags)

if __name__ == "__main__":
    unittest.main()
