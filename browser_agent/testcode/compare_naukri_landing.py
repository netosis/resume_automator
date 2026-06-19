import os
import sys
import json
from pathlib import Path

# Ensure browser_agent is on path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_tools import (
    open_website,
    get_accessibility_tree,
    get_compressed_dom,
    PersistentBrowserManager
)

def estimate_tokens(text: str, model=None) -> int:
    if model:
        try:
            return model.get_num_tokens(text)
        except Exception:
            pass
    return len(text) // 4

def run_landing_comparison():
    os.environ["BROWSER_HEADLESS"] = "true"
    os.environ["BROWSER_INCOGNITO"] = "true"
    os.environ["USE_PERSISTENT_CONTEXT"] = "false"
    
    provider = os.getenv("LLM_PROVIDER", "google").lower()
    model = None
    
    try:
        if provider == "google":
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                from langchain_google_genai import ChatGoogleGenerativeAI
                model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=api_key)
    except Exception:
        pass

    url = "https://www.naukri.com/"
    print(f"Navigating to Naukri Search Landing Page ({url})...")
    
    try:
        open_website.invoke({"url": url, "mode": "interactive"})
        
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        page.wait_for_timeout(4000) # Allow landing page to fully settle
        
        results = {}
        for mode in ["interactive", "reading", "full"]:
            import browser_tools as browser_tools
            browser_tools._LAST_ACCESSIBILITY_STATE = {"url": None, "mode": None, "json": None}
            a11y_res = get_accessibility_tree.invoke({"mode": mode})
            
            browser_tools._LAST_DOM_STATE = {"url": None, "mode": None, "json": None}
            dom_res = get_compressed_dom.invoke({"mode": mode})
            
            a11y_str = str(a11y_res)
            dom_str = str(dom_res)
            
            a11y_tokens = estimate_tokens(a11y_str, model)
            dom_tokens = estimate_tokens(dom_str, model)
            
            results[mode] = {
                "a11y_chars": len(a11y_str),
                "a11y_tokens": a11y_tokens,
                "dom_chars": len(dom_str),
                "dom_tokens": dom_tokens,
                "savings_pct": ((a11y_tokens - dom_tokens) / a11y_tokens) * 100 if a11y_tokens > 0 else 0
            }
            print(f"Mode: {mode}")
            print(f"  Accessibility Tree: {a11y_tokens} tokens ({len(a11y_str)} chars)")
            print(f"  Compressed DOM:     {dom_tokens} tokens ({len(dom_str)} chars)")
            print(f"  Savings:            {results[mode]['savings_pct']:.1f}%")
            
        # Write json output
        out_path = Path(__file__).parent / "naukri_landing_comparison.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4)
            
    finally:
        try:
            manager = PersistentBrowserManager.get_instance()
            manager.close()
        except Exception:
            pass

if __name__ == "__main__":
    run_landing_comparison()
