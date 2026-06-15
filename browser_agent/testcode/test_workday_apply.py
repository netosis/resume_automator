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

    # Core set of browser tools (added generate_fill_values)
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
        generate_fill_values,
        close_browser_session
    ]

    model_with_tools = model.bind_tools(tools)

    print("\n--- Starting Workday Apply Agent Execution ---")
    print(f"Incognito Mode: ACTIVE")
    print(f"Target URL: {target_url}\n")

    # Prompt instructing the agent on the new generate_fill_values workflow
    prompt = (
        f"You are a helpful browser automation agent. Your task is to apply for the job on the page: {target_url}\n\n"
        "Here are the instructions to guide you:\n"
        "1. Open the website using the `open_website` tool.\n"
        "2. Locate and click the 'Apply' or 'Apply Now' button. If a options dropdown or modal opens, click 'Apply Manually'.\n"
        "3. Once the main form page loads, verify if form fields are rendered. If they are not visible, wait, scroll down (`scroll_page`), or check interactable elements.\n"
        "4. Once the fields are visible, invoke the `get_form_fields` tool to scan all the form inputs.\n"
        "5. Pass the output of `get_form_fields` to the `generate_fill_values` tool to get a JSON dictionary mapping CSS selectors to their appropriate fill values.\n"
        "6. Using the JSON output from `generate_fill_values`, fill out the form fields by iterating through each key/value pair and invoking the appropriate input tools:\n"
        "   - Use `input_text_into_element` for text boxes.\n"
        "   - Use `select_dropdown_option` for dropdowns.\n"
        "   - Use `set_checkbox_state` for checkboxes or radio options.\n"
        f"7. For the time being, leave the resume uploading part as it is: upload the resume located at {resume_path} to the target file upload field.\n"
        "8. Once all fields on the current page are populated, click the Next/Submit button to proceed.\n"
        "9. If there are subsequent form pages, repeat the get_form_fields -> generate_fill_values -> input/select filling workflow to progress further.\n"
        "10. Keep the browser session open. Do not close it.\n"
    )

    messages = [HumanMessage(content=prompt)]

    # Token logging lists
    llm_token_logs = []
    tool_token_logs = []
    
    total_llm_input = 0
    total_llm_output = 0
    total_tool_input = 0
    total_tool_output = 0

    # Increased steps limit to 30
    max_steps = 30
    for step in range(max_steps):
        print(f"[Agent Step {step + 1}] Invoking LLM ({provider.upper()})...")
        try:
            response = invoke_model_with_retry(model_with_tools, messages)
        except Exception as e:
            print(f"\n[Agent Error]: API call failed: {e}")
            break
            
        messages.append(response)

        # Log LLM token usage
        llm_in = 0
        llm_out = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            llm_in = response.usage_metadata.get('input_tokens', 0)
            llm_out = response.usage_metadata.get('output_tokens', 0)
            total_llm_input += llm_in
            total_llm_output += llm_out
        
        llm_token_logs.append({
            "step": step + 1,
            "input_tokens": llm_in,
            "output_tokens": llm_out,
            "total_tokens": llm_in + llm_out
        })

        if response.content:
            print(f"\n[Agent Thoughts]:\n{response.content}\n")

        if not response.tool_calls:
            print("[Agent Execution Complete]")
            break

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            input_tokens = model.get_num_tokens(str(tool_args))
            print(f"[Agent Tool Call]: {tool_name} with args {tool_args} | Input Size: {input_tokens} tokens")

            matching_tool = next((t for t in tools if t.name == tool_name), None)
            if matching_tool:
                try:
                    result = matching_tool.invoke(tool_args)
                    result_str = str(result)
                    
                    output_tokens = model.get_num_tokens(result_str)
                    print(f"[Tool Response]: {result_str[:400]}... [truncated for display]")
                    print(f"[Token Usage]: Tool '{tool_name}' consumed: {input_tokens} (input) + {output_tokens} (output) tokens\n")
                    
                    tool_token_logs.append({
                        "step": step + 1,
                        "tool_name": tool_name,
                        "args": tool_args,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "status": "success"
                    })
                    total_tool_input += input_tokens
                    total_tool_output += output_tokens
                    
                    messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
                except Exception as e:
                    error_msg = f"Error running tool '{tool_name}': {str(e)}"
                    error_tokens = model.get_num_tokens(error_msg)
                    print(f"[Tool Error]: {error_msg}")
                    
                    tool_token_logs.append({
                        "step": step + 1,
                        "tool_name": tool_name,
                        "args": tool_args,
                        "input_tokens": input_tokens,
                        "output_tokens": error_tokens,
                        "status": "error",
                        "error": str(e)
                    })
                    total_tool_input += input_tokens
                    total_tool_output += error_tokens
                    
                    messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
            else:
                error_msg = f"Tool '{tool_name}' is not registered."
                error_tokens = model.get_num_tokens(error_msg)
                print(f"[Tool Error]: {error_msg}")
                
                tool_token_logs.append({
                    "step": step + 1,
                    "tool_name": tool_name,
                    "args": tool_args,
                    "input_tokens": input_tokens,
                    "output_tokens": error_tokens,
                    "status": "not_registered"
                })
                total_tool_input += input_tokens
                total_tool_output += error_tokens
                
                messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
    else:
        print("[Agent Warning]: Reached maximum steps without completion.")

    # Save Session Token Usage Summary
    session_summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "task_prompt": prompt,
        "llm_totals": {
            "input": total_llm_input,
            "output": total_llm_output,
            "total": total_llm_input + total_llm_output
        },
        "tool_totals": {
            "input": total_tool_input,
            "output": total_tool_output,
            "total": total_tool_input + total_tool_output
        },
        "llm_steps": llm_token_logs,
        "tool_calls": tool_token_logs
    }

    try:
        log_dir = Path(__file__).parent.parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        filename = log_dir / f"session_token_usage_workday_{time.strftime('%Y%m%d_%H%M%S')}.json"
        import json
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(session_summary, f, indent=4)
        print(f"[Token Logger] Token usage logged to: {filename}")
    except Exception as e:
        print(f"[Token Logger Warning] Failed to save token log to file: {e}")

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
