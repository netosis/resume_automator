import os
import sys
import time
import random
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage

# Ensure parent and current directories are on path to allow imports
sys.path.append(str(Path(__file__).parent.parent.resolve()))
from browser_tools import (
    open_website,
    get_page_text,
    click_on_element,
    input_text_into_element,
    scroll_page,
    get_interactable_buttons,
    click_apply_button,
    get_form_fields,
    select_dropdown_option,
    set_checkbox_state,
    upload_file,
    generate_fill_values,
    close_browser_session,
    PersistentBrowserManager
)

# 1. Configure Stream Encoding for Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 2. Force Browser Incognito/Non-Persistent Mode
os.environ["BROWSER_INCOGNITO"] = "true"

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

def ensure_dummy_resume() -> str:
    """Creates a minimal dummy PDF resume for testing."""
    path = Path(__file__).parent / "dummy_resume.pdf"
    if not path.exists():
        path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/Resources << >>\n/MediaBox [0 0 595.275 841.889]\n/Contents 4 0 R\n>>\nendobj\n4 0 obj\n<<\n/Length 15\n>>\nstream\nBT /F1 12 Tf ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\n0000000212 00000 n\ntrailer\n<<\n/Size 5\n/Root 1 0 R\n>>\nstartxref\n278\n%%EOF\n")
    return str(path.resolve())

def invoke_model_with_retry(model, messages, max_retries=5, initial_delay=2.0):
    """
    Invokes the model with exponential backoff retry.
    """
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return model.invoke(messages)
        except Exception as e:
            err_msg = str(e)
            is_rate_limit = "429" in err_msg or "ResourceExhausted" in err_msg or "quota" in err_msg.lower()
            is_service_unavailable = "503" in err_msg or "ServiceUnavailable" in err_msg or "unavailable" in err_msg.lower()
            
            if (is_rate_limit or is_service_unavailable) and attempt < max_retries - 1:
                sleep_time = delay + random.uniform(0, 1.0)
                print(f"\n[API Warning]: Encountered transient error ({type(e).__name__}: {err_msg}). Retrying in {sleep_time:.2f} seconds... (Attempt {attempt + 1}/{max_retries})")
                time.sleep(sleep_time)
                delay *= 2
            else:
                raise e

def run_workday_apply(target_url: str, resume_path: str):
    """Runs the LangChain Agent loop using browser tools to apply on Workday."""
    from workday_agent import run_workday_agent
    run_workday_agent(resume_path=resume_path, target_url=target_url)

    # Hold the browser open for 5 minutes (300 seconds)
    print("\n--- Form filling complete! Keeping browser open for 5 minutes (300s) for your inspection ---")
    try:
        time.sleep(300)
    except KeyboardInterrupt:
        print("\nClose request received. Stopping hold.")

    # Explicitly close the browser context after holding
    try:
        print("Closing browser session...")
        manager = PersistentBrowserManager.get_instance()
        manager.close()
    except Exception as e:
        print(f"Error closing browser: {e}")

if __name__ == "__main__":
    target_url = "https://kimberlyclark.wd1.myworkdayjobs.com/en-US/GLOBAL/job/IT-Centre-Bengaluru-GDTC/AI-Engineer_885971-2"
    resume_path = ensure_dummy_resume()
    run_workday_apply(target_url, resume_path)
