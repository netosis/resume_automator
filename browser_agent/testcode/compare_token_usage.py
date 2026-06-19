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
    # Fallback to character-based estimation
    return len(text) // 4

def run_comparison():
    # Force headless and incognito mode for testing
    os.environ["BROWSER_HEADLESS"] = "true"
    os.environ["BROWSER_INCOGNITO"] = "true"
    os.environ["USE_PERSISTENT_CONTEXT"] = "false"
    
    # Initialize model for token counting
    provider = os.getenv("LLM_PROVIDER", "google").lower()
    model = None
    
    try:
        if provider == "google":
            api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if api_key:
                from langchain_google_genai import ChatGoogleGenerativeAI
                model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=api_key)
        elif provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if api_key:
                from langchain_deepseek import ChatDeepSeek
                model = ChatDeepSeek(model="deepseek-chat", api_key=api_key)
    except Exception as e:
        print(f"Warning: Failed to load model tokenizer ({e}). Using character fallback.")

    print("=== Token Usage Comparison: DOM Compression vs. Accessibility Tree ===")
    
    # Test URLs
    urls = [
        ("Naukri Jobs Search", "https://www.naukri.com/ai-engineer-jobs"),
        ("Workday Application Mock Page", Path(__file__).parent / "mock_form.html")
    ]
    
    results = {}
    
    try:
        for name, url_or_path in urls:
            if isinstance(url_or_path, Path):
                url = url_or_path.absolute().as_uri()
            else:
                url = url_or_path
                
            print(f"\nNavigating to {name} ({url})...")
            # Open the website first
            open_website.invoke({"url": url, "mode": "interactive"})
            
            # Allow some time to load
            manager = PersistentBrowserManager.get_instance()
            page = manager.get_page()
            page.wait_for_timeout(3000)
            
            results[name] = {}
            
            # Compare each mode
            for mode in ["interactive", "reading", "full"]:
                print(f"  Fetching trees for mode: '{mode}'...")
                
                # Fetch fresh accessibility tree (using clean caches)
                import browser_tools as browser_tools
                browser_tools._LAST_ACCESSIBILITY_STATE = {"url": None, "mode": None, "json": None}
                a11y_res = get_accessibility_tree.invoke({"mode": mode})
                
                # Fetch fresh compressed DOM
                browser_tools._LAST_DOM_STATE = {"url": None, "mode": None, "json": None}
                dom_res = get_compressed_dom.invoke({"mode": mode})
                
                # Verify outputs
                a11y_str = str(a11y_res)
                dom_str = str(dom_res)
                
                a11y_chars = len(a11y_str)
                dom_chars = len(dom_str)
                
                a11y_tokens = estimate_tokens(a11y_str, model)
                dom_tokens = estimate_tokens(dom_str, model)
                
                results[name][mode] = {
                    "a11y_chars": a11y_chars,
                    "a11y_tokens": a11y_tokens,
                    "dom_chars": dom_chars,
                    "dom_tokens": dom_tokens,
                    "savings_pct": ((a11y_tokens - dom_tokens) / a11y_tokens) * 100 if a11y_tokens > 0 else 0
                }
                
                print(f"    Accessibility Tree: {a11y_tokens} tokens ({a11y_chars} chars)")
                print(f"    Compressed DOM:     {dom_tokens} tokens ({dom_chars} chars)")
                print(f"    Savings:            {results[name][mode]['savings_pct']:.1f}%")
                
    finally:
        # Close session
        try:
            manager = PersistentBrowserManager.get_instance()
            manager.close()
        except Exception:
            pass
            
    # Output markdown report format
    report_lines = []
    report_lines.append("# Token Usage Comparison Report\n")
    report_lines.append("Comparing **DOM Compression** against **Accessibility Tree** representations across different pages and modes.\n")
    
    for name, modes in results.items():
        report_lines.append(f"## {name}")
        report_lines.append("| Mode | Accessibility Tree (Tokens) | Compressed DOM (Tokens) | Token Change / Savings |")
        report_lines.append("| :--- | :---: | :---: | :---: |")
        for mode, data in modes.items():
            savings_str = f"{data['savings_pct']:.1f}% reduction" if data['savings_pct'] > 0 else f"{abs(data['savings_pct']):.1f}% increase"
            if abs(data['savings_pct']) < 1.0:
                savings_str = "No significant difference"
            report_lines.append(f"| {mode.capitalize()} | {data['a11y_tokens']:,} | {data['dom_tokens']:,} | {savings_str} |")
        report_lines.append("")
        
    report_content = "\n".join(report_lines)
    
    # Save the report to artifacts directory
    artifacts_dir = Path("D:/LLM Projects/resume_automator/logs")
    artifacts_dir.mkdir(exist_ok=True)
    report_file = artifacts_dir / "token_comparison_report.md"
    report_file.write_text(report_content, encoding="utf-8")
    print(f"\nSaved report to: {report_file}")
    
if __name__ == "__main__":
    run_comparison()
