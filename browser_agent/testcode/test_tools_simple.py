import os
import sys

import json
# Ensure modules in browser_agent can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from browser_tools import (
    open_website,
    get_page_text,
    get_interactable_buttons,
    fetch_job_details,
    naukri_job_fetch,
    PersistentBrowserManager,
    close_browser_session
)

def run_test():
    browser_type = os.getenv("BROWSER_TYPE", "brave").lower()
    print(f"--- Starting Browser Tools Verification Test ({browser_type.upper()}) ---")
    
    # 1. Test opening a website
    url = "https://www.naukri.com/ai-engineer-jobs"
    print(f"\n1. Testing open_website with URL: {url}...")
    result = open_website.invoke({"url": url})
    print(f"Result: {result}")
    
    if "Failed" in result:
        print("Verification failed on step 1.")
        return False
        
    # 2. Test extracting page text
    print("\n2. Testing get_page_text...")
    text = get_page_text.invoke({})
    print(f"Extracted Text (first 200 chars):")
    print("-" * 50)
    # Safely handle console encoding in Windows to avoid charmap crash
    safe_stdout = sys.stdout.encoding or 'utf-8'
    safe_text = text[:200].encode(safe_stdout, errors='replace').decode(safe_stdout, errors='replace')
    print(safe_text)
    print("-" * 50)
    
    if not text or "Failed" in text:
        print("Verification failed on step 2.")
        return False
        
    # Wait for dynamic elements on Naukri.com to load completely
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        print("Waiting 5 seconds for Naukri.com dynamic page content to settle...")
        page.wait_for_timeout(5000)
    except Exception as e:
        print(f"Warning during wait: {e}")

    # 3. Test interactable buttons extraction
    print("\n3. Testing get_interactable_buttons...")
    buttons_text = get_interactable_buttons.invoke({})
    print(f"Buttons (first 500 chars):")
    print("-" * 50)
    safe_buttons = buttons_text[:500].encode(safe_stdout, errors='replace').decode(safe_stdout, errors='replace')
    print(safe_buttons)
    print("-" * 50)
    
    # Save resulting buttons to a JSON file for the user
    try:
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accessibility_tree.json")
        with open(json_path, "r", encoding="utf-8") as f:
            raw_buttons = json.load(f)
            
        out_json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "interactable_buttons.json")
        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(raw_buttons, f, indent=4, ensure_ascii=False)
        print(f"Successfully saved {len(raw_buttons)} elements to: {out_json_path}")
    except Exception as e:
        print(f"Warning: Failed to save buttons to JSON file: {e}")
        
    # 3.5 Test fetching job details using Method A (fetch_job_details)
    print("\n3.5. Testing fetch_job_details (Method A)...")
    job_details_a = fetch_job_details.invoke({})
    print(f"Job Details (Method A):")
    print("-" * 50)
    safe_details_a = job_details_a.encode(safe_stdout, errors='replace').decode(safe_stdout, errors='replace')
    print(safe_details_a)
    print("-" * 50)

    # 3.6 Test fetching job details using Method B (naukri_job_fetch)
    print("\n3.6. Testing naukri_job_fetch (Method B)...")
    job_details_b = naukri_job_fetch.invoke({})
    print(f"Job Details (Method B):")
    print("-" * 50)
    safe_details_b = job_details_b.encode(safe_stdout, errors='replace').decode(safe_stdout, errors='replace')
    print(safe_details_b)
    print("-" * 50)

    # 4. Test closing the session
    print("\n4. Testing close_browser_session...")
    close_result = close_browser_session.invoke({})
    print(f"Result: {close_result}")
    
    print(f"\nVerification Test for {browser_type.upper()} Completed Successfully!")
    return True

if __name__ == "__main__":
    try:
        success = run_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nVerification crashed with error: {e}")
        sys.exit(1)
