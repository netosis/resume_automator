import os
import sys
import time
import random
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, SystemMessage
import async_logger

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
    click_apply_button,
    close_browser_session,
    get_form_fields,
    select_dropdown_option,
    set_checkbox_state,
    upload_file,
    PersistentBrowserManager,
    get_compressed_dom,
    save_chat_transcript,
    fill_entire_form,
    update_agent_memory
)
from naukri_tools import (
    naukri_job_fetch,
    search_naukri_via_url
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
    # Check if the target URL is already a Workday URL
    if "myworkdayjobs.com" in target_url or "workday" in target_url:
        print(f"\n[Handoff]: Target URL '{target_url}' is a Workday application. Directly invoking Workday Agent...")
        from workday_agent import run_workday_agent
        run_workday_agent(resume_path=resume_path, target_url=target_url)
        return

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
    elif provider == "local":
        api_base = os.getenv("LOCAL_API_BASE", "http://localhost:11434/v1")
        model_name = os.getenv("LOCAL_MODEL", "qwen2.5")
        api_key = os.getenv("LOCAL_API_KEY", "local")
        
        print(f"Initializing ChatOpenAI local model='{model_name}' at base='{api_base}'...")
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=api_base,
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
        close_browser_session,
        get_compressed_dom,
        fill_entire_form
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
        "4. Fill out the entire application form at once using the `fill_entire_form` tool (instead of calling individual tools field-by-field) with a JSON list containing specifications for all the fields:\n"
        "   - Full Name (text type): John Doe\n"
        "   - Email Address (text type): johndoe@example.com\n"
        "   - Target Role (select type): AI Systems Engineer (select this value or label)\n"
        "   - Work Location Preference (checkbox/radio type): Remote (checked=True)\n"
        f"   - Upload Resume (file type): Upload the file located at: {resume_path}\n"
        "   - Privacy Policy / Terms (checkbox/radio type): Agree to terms (checked=True)\n"
        "5. Submit the application by clicking the submit button.\n"
        "6. Do not close the browser context. Keep the browser open so the final submission screen can be inspected.\n\n"
        "### STATEFUL SCRATCHPAD INSTRUCTIONS:\n"
        "To optimize memory, you must maintain a running 'State Summary / Scratchpad'. "
        "In every response, you MUST include a `<scratchpad>` XML block containing a JSON object summarizing your current state. "
        "The JSON object must follow this structure:\n"
        "{\n"
        "  \"completed_steps\": [\"Brief description of step 1\", \"Brief description of step 2\"],\n"
        "  \"extracted_data\": {\"key1\": \"value1\", \"key2\": \"value2\"},\n"
        "  \"next_immediate_step\": \"What you plan to do next\"\n"
        "}\n"
        "Example format in your output:\n"
        "<scratchpad>\n"
        "{\n"
        "  \"completed_steps\": [\"Opened job page\", \"Clicked apply button\"],\n"
        "  \"extracted_data\": {\"job_title\": \"Software Engineer\"},\n"
        "  \"next_immediate_step\": \"Fill the contact information form\"\n"
        "}\n"
        "</scratchpad>\n"
        "Do not omit this block from your response! Always output it."
    )

    state_summary = {
        "completed_steps": [],
        "extracted_data": {},
        "next_immediate_step": ""
    }

    import json
    messages = [
        HumanMessage(content=prompt),
        SystemMessage(content=f"### CURRENT AGENT STATE SUMMARY:\n{json.dumps(state_summary, indent=2)}")
    ]
    llm_call_token_logs = []
    
    manager = PersistentBrowserManager.get_instance()
    session_id = getattr(manager, "session_id", None) or time.strftime("%Y%m%d_%H%M%S")

    try:
        max_steps = 15
        last_response_content = None
        for step in range(max_steps):
            # Dynamic check for redirection to Workday
            try:
                manager = PersistentBrowserManager.get_instance()
                if manager.page and not manager.page.is_closed():
                    current_url = manager.page.url
                    if "myworkdayjobs.com" in current_url or "workday" in current_url:
                        print(f"\n[Handoff]: Detected Workday form/redirection at '{current_url}'. Invoking Workday Agent...")
                        from workday_agent import run_workday_agent
                        run_workday_agent(resume_path=resume_path)
                        print("[Handoff]: Workday Agent execution complete. Exiting main agent loop.")
                        return
            except Exception as e:
                print(f"[Handoff Warning]: Failed to check browser state for Workday: {e}")

            # Update memory state (pruning and scratchpad maintenance)
            update_agent_memory(messages, state_summary, last_response_content, keep_last_n_tool_outputs=2)

            print(f"[Agent Step {step + 1}] Invoking LLM ({provider.upper()})...")
            try:
                response = invoke_model_with_retry(model_with_tools, messages)
            except Exception as e:
                print(f"\n[Agent Error]: API call failed: {e}")
                break
                
            messages.append(response)
            last_response_content = response.content
            save_chat_transcript("apply", messages, session_id)

            llm_in = 0
            llm_out = 0
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                llm_in = response.usage_metadata.get('input_tokens', 0)
                llm_out = response.usage_metadata.get('output_tokens', 0)

            # Log to the unified session log file
            try:
                sent_msgs = [{"role": type(m).__name__, "content": m.content} for m in messages[:-1]]
                from browser_tools import log_api_call
                if response.tool_calls:
                    log_api_call(
                        caller_name="Main Agent Loop API Call (requested tools)",
                        model_name=model_name,
                        input_tokens=llm_in,
                        output_tokens=llm_out,
                        sent_data={"messages": sent_msgs},
                        response_data={"content": response.content, "tool_calls": response.tool_calls}
                    )
                else:
                    log_api_call(
                        caller_name="Main Agent Loop API Call (final)",
                        model_name=model_name,
                        input_tokens=llm_in,
                        output_tokens=llm_out,
                        sent_data={"messages": sent_msgs},
                        response_data={"content": response.content}
                    )
            except Exception as e:
                print(f"[Agent Warning] Failed to log unified API call: {e}")

            if response.tool_calls:
                for tool_call in response.tool_calls:
                    llm_call_token_logs.append({
                        "step": step + 1,
                        "tool_call_name": tool_call["name"],
                        "llm_input_tokens": llm_in,
                        "llm_output_tokens": llm_out
                    })
            else:
                llm_call_token_logs.append({
                    "step": step + 1,
                    "tool_call_name": "none",
                    "llm_input_tokens": llm_in,
                    "llm_output_tokens": llm_out
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

                # Log to the unified session log file specifically for this tool call
                try:
                    sent_msgs = [{"role": type(m).__name__, "content": m.content} for m in messages[:-1]]
                    from browser_tools import log_api_call
                    log_api_call(
                        caller_name=f"API Call requesting Tool: {tool_name}",
                        model_name=model_name,
                        input_tokens=llm_in,
                        output_tokens=llm_out,
                        sent_data={"messages": sent_msgs, "requested_tool_call": tool_call},
                        response_data={"content": response.content, "tool_calls": response.tool_calls}
                    )
                except Exception as e:
                    print(f"[Agent Warning] Failed to log tool API call: {e}")

                matching_tool = next((t for t in tools if t.name == tool_name), None)
                if matching_tool:
                    try:
                        result = matching_tool.invoke(tool_args)
                        result_str = str(result)
                        output_tokens = model.get_num_tokens(result_str)
                        print(f"[Tool Response]: {result_str[:400]}... [truncated for display]")
                        print(f"[Token Usage]: Tool '{tool_name}' consumed: {input_tokens} (input) + {output_tokens} (output) tokens\n")
                        
                        # Log tool execution to unified session log
                        try:
                            from browser_tools import log_api_call
                            log_api_call(
                                caller_name=f"Tool Execute: {tool_name}",
                                model_name="tool_local",
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                sent_data=tool_args,
                                response_data=result_str
                            )
                        except Exception as le:
                            print(f"[Agent Warning] Failed to log tool execution: {le}")

                        messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
                        save_chat_transcript("apply", messages, session_id)
                    except Exception as e:
                        error_msg = f"Error running tool '{tool_name}': {str(e)}"
                        error_tokens = model.get_num_tokens(error_msg)
                        print(f"[Tool Error]: {error_msg}")
                        
                        # Log tool execution error to unified session log
                        try:
                            from browser_tools import log_api_call
                            log_api_call(
                                caller_name=f"Tool Execute: {tool_name} (FAILED)",
                                model_name="tool_local",
                                input_tokens=input_tokens,
                                output_tokens=error_tokens,
                                sent_data=tool_args,
                                response_data=error_msg
                            )
                        except Exception as le:
                            print(f"[Agent Warning] Failed to log tool execution failure: {le}")

                        messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
                        save_chat_transcript("apply", messages, session_id)
                else:
                    error_msg = f"Tool '{tool_name}' is not registered."
                    error_tokens = model.get_num_tokens(error_msg)
                    print(f"[Tool Error]: {error_msg}")
                    
                    # Log unregistered tool execution to unified session log
                    try:
                        from browser_tools import log_api_call
                        log_api_call(
                            caller_name=f"Tool Execute: {tool_name} (UNREGISTERED)",
                            model_name="tool_local",
                            input_tokens=input_tokens,
                            output_tokens=error_tokens,
                            sent_data=tool_args,
                            response_data=error_msg
                        )
                    except Exception as le:
                        print(f"[Agent Warning] Failed to log unregistered tool error: {le}")

                    messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
                    save_chat_transcript("apply", messages, session_id)
        else:
            print("[Agent Warning]: Reached maximum steps without completion.")
    except KeyboardInterrupt:
        print("\n" + "="*50)
        print("SESSION TOKEN USAGE SUMMARY (FORCE CLOSED)")
        print("="*50)
        total_in = sum(x.get("llm_input_tokens", 0) for x in llm_call_token_logs)
        total_out = sum(x.get("llm_output_tokens", 0) for x in llm_call_token_logs)
        print(f"LLM Calls:")
        print(f"  Total Input Tokens:  {total_in}")
        print(f"  Total Output Tokens: {total_out}")
        print(f"  Total LLM Tokens:    {total_in + total_out}")
        print("="*50 + "\n")
        
        save_chat_transcript("apply", messages, session_id)
        
        try:
            log_dir = Path(__file__).parent.parent / "logs"
            log_dir.mkdir(exist_ok=True)
            llm_log_filename = log_dir / f"llm_call_token_usage_apply_{time.strftime('%Y%m%d_%H%M%S')}.json"
            import json
            with open(llm_log_filename, "w", encoding="utf-8") as f:
                json.dump(llm_call_token_logs, f, indent=4)
            print(f"[Apply Agent Token Logger] Dedicated LLM call token usage logged to: {llm_log_filename}")
        except Exception as e:
            print(f"[Apply Agent Token Logger Warning] Failed to save token log to file: {e}")
        raise KeyboardInterrupt

    # Write log file containing LLM call token usage
    try:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        llm_log_filename = log_dir / f"llm_call_token_usage_apply_{time.strftime('%Y%m%d_%H%M%S')}.json"
        import json
        with open(llm_log_filename, "w", encoding="utf-8") as f:
            json.dump(llm_call_token_logs, f, indent=4)
        print(f"[Apply Agent Token Logger] Dedicated LLM call token usage logged to: {llm_log_filename}")
    except Exception as e:
        print(f"[Apply Agent Token Logger Warning] Failed to save token log to file: {e}")

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
    
    try:
        run_apply_agent(target_url, resume_path)
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(0)
