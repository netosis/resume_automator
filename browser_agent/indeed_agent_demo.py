import os
import sys
import time
import random
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, SystemMessage
import async_logger

# Reconfigure stdout/stderr to UTF-8 on Windows to avoid cp1252/charmap print crashes
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def invoke_model_with_retry(model, messages, max_retries=5, initial_delay=2.0):
    """
    Invokes the model with exponential backoff retry for 429 (Rate Limit) and 503 (Service Unavailable) errors.
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

# Add current directory to path to allow import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from browser_tools import (
    open_website,
    get_page_text,
    click_on_element,
    input_text_into_element,
    scroll_page,
    get_interactable_buttons,
    fetch_job_details,
    close_browser_session,
    get_form_fields,
    select_dropdown_option,
    set_checkbox_state,
    upload_file,
    log_api_call,
    get_compressed_dom,
    close_current_tab,
    go_back,
    save_chat_transcript,
    fill_entire_form,
    PersistentBrowserManager,
    update_agent_memory
)
from indeed_tools import (
    search_indeed_via_url,
    indeed_job_fetch,
    fetch_indeed_job_details,
    click_indeed_apply_button
)

# Global token tracker for handling force close cleanup
_TOKEN_TRACKER = {
    "prompt": "",
    "model_name": "unknown",
    "llm_token_logs": [],
    "tool_token_logs": [],
    "total_llm_input": 0,
    "total_llm_output": 0,
    "total_tool_input": 0,
    "total_tool_output": 0,
    "messages": []
}


def save_force_close_logs(platform: str):
    print("\n" + "="*50)
    print("SESSION TOKEN USAGE SUMMARY (FORCE CLOSED)")
    print("="*50)
    print(f"LLM Calls:")
    print(f"  Total Input Tokens:  {_TOKEN_TRACKER['total_llm_input']}")
    print(f"  Total Output Tokens: {_TOKEN_TRACKER['total_llm_output']}")
    print(f"  Total LLM Tokens:    {_TOKEN_TRACKER['total_llm_input'] + _TOKEN_TRACKER['total_llm_output']}")
    print(f"\nTool Calls:")
    print(f"  Total Input Tokens:  {_TOKEN_TRACKER['total_tool_input']}")
    print(f"  Total Output Tokens: {_TOKEN_TRACKER['total_tool_output']}")
    print(f"  Total Tool Tokens:   {_TOKEN_TRACKER['total_tool_input'] + _TOKEN_TRACKER['total_tool_output']}")
    print("\nDetailed Tool Token Usage:")
    for log in _TOKEN_TRACKER['tool_token_logs']:
        print(f"  - Step {log['step']}: Tool '{log['tool_name']}' | Input: {log['input_tokens']} | Output: {log['output_tokens']} | Status: {log['status']}")
    print("="*50 + "\n")

    session_summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "force_closed",
        "task_prompt": _TOKEN_TRACKER["prompt"],
        "llm_totals": {
            "input": _TOKEN_TRACKER["total_llm_input"],
            "output": _TOKEN_TRACKER["total_llm_output"],
            "total": _TOKEN_TRACKER["total_llm_input"] + _TOKEN_TRACKER["total_llm_output"]
        },
        "tool_totals": {
            "input": _TOKEN_TRACKER["total_tool_input"],
            "output": _TOKEN_TRACKER["total_tool_output"],
            "total": _TOKEN_TRACKER["total_tool_input"] + _TOKEN_TRACKER["total_tool_output"]
        },
        "llm_steps": _TOKEN_TRACKER["llm_token_logs"],
        "tool_calls": _TOKEN_TRACKER["tool_token_logs"]
    }

    try:
        from pathlib import Path
        import json
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        filename = log_dir / f"{platform}_force_closed_token_usage_{time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(session_summary, f, indent=4)
        print(f"[Token Logger] Force close token usage logged to: {filename}")
    except Exception as e:
        print(f"[Token Logger Warning] Failed to save force close token log: {e}")

    try:
        manager = PersistentBrowserManager.get_instance()
        session_id = getattr(manager, "session_id", time.strftime("%Y%m%d_%H%M%S"))
        save_chat_transcript(platform, _TOKEN_TRACKER["messages"], session_id)
    except Exception as e:
        print(f"[Transcript Force Close Warning] Failed to save final chat transcript: {e}")

# Load environment variables (for GEMINI_API_KEY)
load_dotenv()

# Force Browser Normal/Persistent mode (not incognito) so user session cookies are reused
os.environ["BROWSER_INCOGNITO"] = "false"
os.environ["BROWSER_TYPE"] = "brave"
os.environ["BROWSER_PROFILE"] = "Default"

def run_browser_agent(prompt: str):
    """
    Runs a simple agent loop using the Gemini model and the browser tools.
    """
    _TOKEN_TRACKER["prompt"] = prompt
    # Determine which LLM provider to use
    provider = os.getenv("LLM_PROVIDER")
    if not provider:
        provider = "deepseek" if os.getenv("DEEPSEEK_API_KEY") else "google"
    provider = provider.lower()

    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            print("Error: DEEPSEEK_API_KEY is not set in your environment variables.")
            print("Please create a .env file or export the key, then try again.")
            return
        
        api_base = os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com/v1"
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        
        print(f"Initializing ChatDeepSeek model='{model_name}' at base='{api_base}'...")
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
            print("Error: GEMINI_API_KEY / GOOGLE_API_KEY is not set in your environment variables.")
            print("Please create a .env file or export the key, then try again.")
            return
        
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        
        print(f"Initializing ChatGoogleGenerativeAI model='{model_name}'...")
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = ChatGoogleGenerativeAI(
            model=model_name,
            api_key=api_key,
            temperature=0.0
        )
    _TOKEN_TRACKER["model_name"] = model_name

    # Define tool library
    tools = [
        open_website,
        get_page_text,
        click_on_element,
        input_text_into_element,
        scroll_page,
        get_interactable_buttons,
        fetch_job_details,
        click_indeed_apply_button,
        close_browser_session,
        get_form_fields,
        select_dropdown_option,
        set_checkbox_state,
        upload_file,
        get_compressed_dom,
        close_current_tab,
        go_back,
        fill_entire_form,
        search_indeed_via_url,
        indeed_job_fetch,
        fetch_indeed_job_details
    ]

    # Bind tools to the model
    model_with_tools = model.bind_tools(tools)

    print("\n--- Starting Indeed Browser Agent Execution ---")
    print(f"Task Prompt: {prompt}\n")

    # Token tracking variables
    llm_token_logs = []
    tool_token_logs = []
    
    total_llm_input = 0
    total_llm_output = 0
    total_tool_input = 0
    total_tool_output = 0

    state_summary = {
        "completed_steps": [],
        "extracted_data": {},
        "next_immediate_step": ""
    }

    messages = [
        HumanMessage(content=(
            f"You are a helpful browser automation agent. Your task is: {prompt}. "
            "Use the browser tools provided to execute the request. "
            "You have tools for fetching job details from search result pages: "
            "1. 'fetch_job_details': General page text extraction (truncated to 3000 characters). "
            "2. 'indeed_job_fetch': Specialized tool for extracting and cleaning job listings from indeed.com search results. "
            "3. 'fetch_indeed_job_details': Specialized tool for fetching the detailed job description and checking active apply options for the currently selected job card on indeed.com. "
            "You also have a direct URL job search tool: "
            "- 'search_indeed_via_url': Navigate directly to job search on indeed.com. "
            "You have a batch form filling tool: "
            "- 'fill_entire_form': Clicks, types, and selects all fields on a form page at once using a list of field specifications. ALWAYS use this tool to fill form fields, checkboxes, dropdowns, and file uploads at once rather than filling them one by one. Use individual input/select tools only as a fallback. "
            "You also have a specialized tool for clicking Indeed apply buttons: "
            "- 'click_indeed_apply_button': Automatically searches the page for visible elements matching 'Apply', 'Apply on Company Site', etc. and clicks them, auto-switching tabs if a new page is opened. "
            "You also have specialized tools for browser navigation and tab management: "
            "- 'close_current_tab': Closes the currently active browser tab and switches to the last remaining open tab. Use this when a new tab was opened after clicking Apply or a job link and you are done with it. "
            "- 'go_back': Navigates the current browser tab back one step in browser history. "
            "After performing your operations, analyze the retrieved information and present a final response. "
            "IMPORTANT: Do not close the browser session. Keep the browser open.\n\n"
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
            "  \"completed_steps\": [\"Opened indeed.com\", \"Searched for Python developer jobs\"],\n"
            "  \"extracted_data\": {\"search_query\": \"Python developer\"},\n"
            "  \"next_immediate_step\": \"Click on the first job link\"\n"
            "}\n"
            "</scratchpad>\n"
            "Do not omit this block from your response! Always output it."
        )),
        SystemMessage(content=f"### CURRENT AGENT STATE SUMMARY:\n{json.dumps(state_summary, indent=2)}")
    ]

    _TOKEN_TRACKER["messages"] = messages
    manager = PersistentBrowserManager.get_instance()
    session_id = getattr(manager, "session_id", time.strftime("%Y%m%d_%H%M%S"))

    max_steps = 35
    last_response_content = None
    for step in range(max_steps):
        # Update memory state (pruning and scratchpad maintenance)
        update_agent_memory(messages, state_summary, last_response_content, keep_last_n_tool_outputs=2)
        
        print(f"[Agent Step {step + 1}] Invoking LLM ({provider.upper()})...")
        try:
            response = invoke_model_with_retry(model_with_tools, messages)
        except Exception as e:
            print(f"\n[Agent Error]: API call failed after retries. Error: {e}")
            break
        messages.append(response)
        last_response_content = response.content
        save_chat_transcript("indeed", messages, session_id)

        # Log LLM token usage if available
        llm_in = 0
        llm_out = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            llm_in = response.usage_metadata.get('input_tokens', 0)
            llm_out = response.usage_metadata.get('output_tokens', 0)
        elif hasattr(response, 'response_metadata') and response.response_metadata:
            token_usage = response.response_metadata.get('token_usage', {})
            if isinstance(token_usage, dict):
                llm_in = token_usage.get('prompt_tokens', 0) or token_usage.get('input_tokens', 0)
                llm_out = token_usage.get('completion_tokens', 0) or token_usage.get('output_tokens', 0)
        
        # Fallback estimation using get_num_tokens
        if (llm_in == 0 or llm_out == 0) and hasattr(model, 'get_num_tokens'):
            try:
                llm_in = model.get_num_tokens(str(messages[:-1]))
                llm_out = model.get_num_tokens(response.content or "")
            except Exception:
                pass
                
        total_llm_input += llm_in
        total_llm_output += llm_out
        
        # Update global tracker
        _TOKEN_TRACKER["total_llm_input"] = total_llm_input
        _TOKEN_TRACKER["total_llm_output"] = total_llm_output
        _TOKEN_TRACKER["llm_token_logs"].append({
            "step": step + 1,
            "input_tokens": llm_in,
            "output_tokens": llm_out,
            "total_tokens": llm_in + llm_out
        })
        
        # Print LLM API call tokens
        print(f"[LLM API Call]: Sent: {llm_in} tokens | Returned: {llm_out} tokens")

        if response.content:
            print(f"\n[Agent Thoughts]:\n{response.content}\n")

        if not response.tool_calls:
            # Log final response
            try:
                sent_msgs = [{"role": type(m).__name__, "content": m.content} for m in messages[:-1]]
                log_api_call(
                    caller_name="Final Response",
                    model_name=model_name,
                    input_tokens=llm_in,
                    output_tokens=llm_out,
                    sent_data=sent_msgs,
                    response_data=response.content
                )
            except Exception as e:
                print(f"[Agent Warning] Failed to log final API call: {e}")
            print("[Agent Execution Complete]")
            break

        # Process tool calls
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            input_tokens = model.get_num_tokens(str(tool_args))
            print(f"[Agent Tool Call]: {tool_name} with args {tool_args} | Input Size: {input_tokens} tokens")
            print(f"[API Call Tokens for Tool '{tool_name}']: Sent to API: {llm_in} | Returned by Model: {llm_out}")

            # Log to the unified session log file specifically for this tool call
            try:
                sent_msgs = [{"role": type(m).__name__, "content": m.content} for m in messages[:-1]]
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
                    print(f"[Tool Response]: {result}")
                    print(f"[Token Usage]: Tool '{tool_name}' consumed: {input_tokens} (input) + {output_tokens} (output) = {input_tokens + output_tokens} total tokens\n")
                    
                    # Log tool execution to unified session log
                    try:
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

                    tool_token_logs.append({
                        "step": step + 1,
                        "tool_name": tool_name,
                        "args": tool_args,
                        "input_tokens": llm_in,
                        "output_tokens": output_tokens,
                        "status": "success"
                    })
                    total_tool_input += llm_in
                    total_tool_output += output_tokens
                    
                    # Update global tracker
                    _TOKEN_TRACKER["total_tool_input"] = total_tool_input
                    _TOKEN_TRACKER["total_tool_output"] = total_tool_output
                    _TOKEN_TRACKER["tool_token_logs"] = tool_token_logs
                    
                    messages.append(ToolMessage(content=result_str, tool_call_id=tool_id))
                    save_chat_transcript("indeed", messages, session_id)
                except Exception as e:
                    error_msg = f"Error running tool '{tool_name}': {str(e)}"
                    error_tokens = model.get_num_tokens(error_msg)
                    print(f"[Tool Error]: {error_msg}")
                    print(f"[Token Usage]: Tool '{tool_name}' error output: {error_tokens} tokens\n")
                    
                    # Log tool execution error to unified session log
                    try:
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

                    tool_token_logs.append({
                        "step": step + 1,
                        "tool_name": tool_name,
                        "args": tool_args,
                        "input_tokens": llm_in,
                        "output_tokens": error_tokens,
                        "status": "error",
                        "error": str(e)
                    })
                    total_tool_input += llm_in
                    total_tool_output += error_tokens
                    
                    # Update global tracker
                    _TOKEN_TRACKER["total_tool_input"] = total_tool_input
                    _TOKEN_TRACKER["total_tool_output"] = total_tool_output
                    _TOKEN_TRACKER["tool_token_logs"] = tool_token_logs
                    
                    messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
                    save_chat_transcript("indeed", messages, session_id)
            else:
                error_msg = f"Tool '{tool_name}' is not registered."
                error_tokens = model.get_num_tokens(error_msg)
                print(f"[Tool Error]: {error_msg}")
                print(f"[Token Usage]: Tool '{tool_name}' error output: {error_tokens} tokens\n")
                
                # Log unregistered tool execution to unified session log
                try:
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

                tool_token_logs.append({
                    "step": step + 1,
                    "tool_name": tool_name,
                    "args": tool_args,
                    "input_tokens": llm_in,
                    "output_tokens": error_tokens,
                    "status": "not_registered"
                })
                total_tool_input += llm_in
                total_tool_output += error_tokens
                
                # Update global tracker
                _TOKEN_TRACKER["total_tool_input"] = total_tool_input
                _TOKEN_TRACKER["total_tool_output"] = total_tool_output
                _TOKEN_TRACKER["tool_token_logs"] = tool_token_logs
                
                messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id))
                save_chat_transcript("indeed", messages, session_id)
    else:
        print("[Agent Warning]: Reached maximum steps without formal completion.")

    # Print session token usage summary
    print("\n" + "="*50)
    print("SESSION TOKEN USAGE SUMMARY")
    print("="*50)
    print(f"LLM Calls:")
    print(f"  Total Input Tokens:  {total_llm_input}")
    print(f"  Total Output Tokens: {total_llm_output}")
    print(f"  Total LLM Tokens:    {total_llm_input + total_llm_output}")
    print(f"\nTool Calls:")
    print(f"  Total Input Tokens:  {total_tool_input}")
    print(f"  Total Output Tokens: {total_tool_output}")
    print(f"  Total Tool Tokens:   {total_tool_input + total_tool_output}")
    print("\nDetailed Tool Token Usage:")
    for log in tool_token_logs:
        print(f"  - Step {log['step']}: Tool '{log['tool_name']}' | Input: {log['input_tokens']} | Output: {log['output_tokens']} | Status: {log['status']}")
    print("="*50 + "\n")

    # Save summary
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
        from pathlib import Path
        import json
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        filename = log_dir / f"indeed_token_usage_{time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(session_summary, f, indent=4)
        print(f"[Token Logger] Token usage logged to: {filename}")
    except Exception as e:
        print(f"[Token Logger Warning] Failed to save token log to file: {e}")

if __name__ == "__main__":
    default_prompt = (
        "Search for 'AI Engineer' jobs on indeed.com using the direct URL modification tool. "
        "Find and apply to 5 different jobs. For each job, select and open the job listing, "
        "fetch the job details using 'fetch_indeed_job_details' to examine the description and check the application button, "
        "click the 'Apply with Indeed' (or 'Apply now') button to open the application tab. "
        "On the application tab, fill out the form step-by-step (using 'get_form_fields' to read fields, "
        "filling them at once using 'fill_entire_form', and clicking 'Continue' or 'Next' or using 'click_indeed_apply_button' to progress), "

        "finally click 'Submit your application' to complete it. After submitting, close the tab using "
        "'close_current_tab', return to the search results to select the next job, and repeat until "
        "you have applied to 5 unique jobs. Keep the browser open when complete."
    )
    
    print("Welcome to the Indeed Browser Automation LLM Agent Demo!")
    print("Press Enter to use the default prompt, or enter a custom prompt below.")
    print(f"Default prompt: \"{default_prompt}\"")
    
    try:
        user_prompt = input("\nEnter prompt: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        sys.exit(0)

    prompt = user_prompt if user_prompt else default_prompt
    try:
        run_browser_agent(prompt)
    except KeyboardInterrupt:
        save_force_close_logs("indeed")
        sys.exit(0)
