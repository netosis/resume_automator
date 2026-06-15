import os
import sys
import time
import random
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage

# Ensure modules in browser_agent can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Reconfigure stdout/stderr to UTF-8 on Windows to avoid cp1252/charmap print crashes
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass
from browser_tools import (
    open_website,
    get_page_text,
    click_on_element,
    input_text_into_element,
    scroll_page,
    get_interactable_buttons,
    fetch_job_details,
    naukri_job_fetch,
    click_apply_button,
    search_naukri_via_url,
    close_browser_session,
    get_form_fields,
    select_dropdown_option,
    set_checkbox_state,
    upload_file,
    PersistentBrowserManager
)

# 1. Force Browser Incognito Mode
os.environ["BROWSER_INCOGNITO"] = "true"

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

def ensure_dummy_resume() -> str:
    """Creates a minimal dummy PDF resume for the file upload test."""
    path = Path(__file__).parent / "testcode" / "dummy_resume.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Minimal PDF structure
        path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/Resources << >>\n/MediaBox [0 0 595.275 841.889]\n/Contents 4 0 R\n>>\nendobj\n4 0 obj\n<<\n/Length 15\n>>\nstream\nBT /F1 12 Tf ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\n0000000212 00000 n\ntrailer\n<<\n/Size 5\n/Root 1 0 R\n>>\nstartxref\n278\n%%EOF\n")
    return str(path.resolve())

def invoke_model_with_retry(model, messages, max_retries=5, initial_delay=2.0):
    """
    Invokes the model with exponential backoff retry for transient API rate limits.
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

def run_apply_agent(target_url: str, resume_path: str):
    """Runs the LangChain Agent loop using the browser tools to apply for a job."""
    provider = os.getenv("LLM_PROVIDER")
    if not provider:
        provider = "deepseek" if os.getenv("DEEPSEEK_API_KEY") else "google"
    provider = provider.lower()

    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            print("Error: DEEPSEEK_API_KEY is not set.")
            return
        
        api_base = os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com/v1"
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        
        print(f"Initializing ChatDeepSeek model='{model_name}'...")
        from langchain_deepseek import ChatDeepSeek
        model = ChatDeepSeek(
            model=model_name,
            api_key=api_key,
            api_base=api_base,
            temperature=0.0
        )
    else:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("Error: GEMINI_API_KEY / GOOGLE_API_KEY is not set.")
            return
        
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        
        print(f"Initializing ChatGoogleGenerativeAI model='{model_name}'...")
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = ChatGoogleGenerativeAI(
            model=model_name,
            api_key=api_key,
            temperature=0.0
        )

    # Core set of browser tools
    tools = [
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
        close_browser_session
    ]

    model_with_tools = model.bind_tools(tools)

    print("\n--- Starting Apply Agent Execution ---")
    print(f"Incognito Mode: ACTIVE")
    print(f"Target URL: {target_url}\n")

    # Build the prompt
    prompt = (
        f"You are a helpful browser automation agent. Your task is to apply for the job on the page: {target_url}\n\n"
        "Here are the instructions to guide you:\n"
        "1. Open the website using the `open_website` tool.\n"
        "2. Locate and click the 'Apply Now' or 'Apply' button. If a new tab opens, the browser session will automatically follow it.\n"
        "3. Once the form is visible, call the `get_form_fields` tool to scan all the input fields and find their labels and selectors.\n"
        "4. Fill out the application form with these details:\n"
        "   - Full Name: John Doe\n"
        "   - Email Address: johndoe@example.com\n"
        f"   - Target Role: AI Systems Engineer (select this from the targetRole dropdown option)\n"
        "   - Work Location Preference: Select 'Remote' (check the checkbox)\n"
        f"   - Upload Resume: Upload the file located at: {resume_path}\n"
        "   - Privacy Policy / Terms: Agree to terms (check the checkbox)\n"
        "5. Submit the application by clicking the submit button.\n"
        "6. Do not close the browser context. Keep the browser open so the final submission screen can be inspected.\n"
    )

    messages = [HumanMessage(content=prompt)]

    max_steps = 15
    for step in range(max_steps):
        print(f"[Agent Step {step + 1}] Invoking LLM ({provider.upper()})...")
        try:
            response = invoke_model_with_retry(model_with_tools, messages)
        except Exception as e:
            print(f"\n[Agent Error]: API call failed: {e}")
            break
            
        messages.append(response)

        if response.content:
            print(f"\n[Agent Thoughts]:\n{response.content}\n")

        if not response.tool_calls:
            print("[Agent Execution Complete]")
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            print(f"[Agent Tool Call]: {tool_name} with args {tool_args}")

            matching_tool = next((t for t in tools if t.name == tool_name), None)
            if matching_tool:
                try:
                    result = matching_tool.invoke(tool_args)
                    result_str = str(result)
                    print(f"[Tool Response]: {result_str[:400]}... [truncated for display]")
                    messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
                except Exception as e:
                    error_msg = f"Error running tool '{tool_name}': {str(e)}"
                    print(f"[Tool Error]: {error_msg}")
                    messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
            else:
                error_msg = f"Tool '{tool_name}' is not registered."
                print(f"[Tool Error]: {error_msg}")
                messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
    else:
        print("[Agent Warning]: Reached maximum steps without completion.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Apply for jobs automatically using Browser Agent")
    parser.add_argument("url", nargs="?", help="The job application page URL")
    args = parser.parse_args()

    resume_path = ensure_dummy_resume()
    
    if args.url:
        target_url = args.url
    else:
        mock_form_path = Path(__file__).parent / "testcode" / "mock_form.html"
        if not mock_form_path.exists():
            print(f"Error: {mock_form_path} does not exist. Please create mock_form.html first.")
            sys.exit(1)
        target_url = mock_form_path.absolute().as_uri()
        print(f"No URL provided. Defaulting to local Mock Form.")
        
    print(f"Target URL: {target_url}")
    print(f"Dummy Resume Path: {resume_path}")
    
    run_apply_agent(target_url, resume_path)
