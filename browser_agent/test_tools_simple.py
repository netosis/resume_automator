import os
import sys

# Ensure modules in browser_agent can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from browser_tools import open_website, get_page_text, close_browser_session

def run_test():
    browser_type = os.getenv("BROWSER_TYPE", "brave").lower()
    print(f"--- Starting Browser Tools Verification Test ({browser_type.upper()}) ---")
    
    # 1. Test opening a website
    url = "https://www.google.com"
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
        
    # 3. Test closing the session
    print("\n3. Testing close_browser_session...")
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
