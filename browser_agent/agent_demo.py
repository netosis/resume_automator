import os
import sys
import time
import random
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage

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
    naukri_job_fetch,
    click_apply_button,
    search_naukri_via_url,
    close_browser_session,
    get_form_fields,
    select_dropdown_option,
    set_checkbox_state,
    upload_file
)

# Load environment variables (for GEMINI_API_KEY)
load_dotenv()

def run_browser_agent(prompt: str):
    """
    Runs a simple agent loop using the Gemini model and the browser tools.
    """
    # Determine which LLM provider to use (default to deepseek if DEEPSEEK_API_KEY is present)
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

    # Define tool library
    tools = [
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
        upload_file
    ]

    # Bind tools to the model
    model_with_tools = model.bind_tools(tools)

    print("\n--- Starting Agent Execution ---")
    print(f"Task Prompt: {prompt}\n")

    # Token tracking variables
    llm_token_logs = []
    tool_token_logs = []
    
    total_llm_input = 0
    total_llm_output = 0
    total_tool_input = 0
    total_tool_output = 0

    messages = [
        HumanMessage(content=(
            f"You are a helpful browser automation agent. Your task is: {prompt}. "
            "Use the browser tools provided to execute the request. "
            "You have two tools for fetching job details: "
            "1. 'fetch_job_details': General page text extraction (truncated to 3000 characters). "
            "2. 'naukri_job_fetch': Specialized tool for extracting and cleaning job listings from '.srp-jobtuple-wrapper' cards on naukri.com search result pages. "
            "You also have a specialized tool for clicking apply buttons: "
            "- 'click_apply_button': Automatically searches the page for visible elements matching 'Apply', 'Apply on Company Site', etc. and clicks them, auto-switching tabs if a new page is opened. "
            "After performing your operations, analyze the retrieved information and present a final response. "
            "IMPORTANT: Do not close the browser session. Keep the browser open."
        ))
    ]

    max_steps = 10
    for step in range(max_steps):
        print(f"[Agent Step {step + 1}] Invoking LLM ({provider.upper()})...")
        try:
            response = invoke_model_with_retry(model_with_tools, messages)
        except Exception as e:
            print(f"\n[Agent Error]: API call failed after retries. Error: {e}")
            break
        messages.append(response)

        # Log LLM token usage if available in usage_metadata
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

        # Print thoughts if there is any content response
        if response.content:
            print(f"\n[Agent Thoughts]:\n{response.content}\n")

        # If there are no tool calls, agent has finished
        if not response.tool_calls:
            print("[Agent Execution Complete]")
            break

        # Process each tool call suggested by the model
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            # Count input tokens
            input_tokens = model.get_num_tokens(str(tool_args))
            print(f"[Agent Tool Call]: {tool_name} with args {tool_args} | Input Size: {input_tokens} tokens")

            # Find and invoke the matching tool
            matching_tool = next((t for t in tools if t.name == tool_name), None)
            if matching_tool:
                try:
                    result = matching_tool.invoke(tool_args)
                    result_str = str(result)
                    
                    # Count output tokens
                    output_tokens = model.get_num_tokens(result_str)
                    print(f"[Tool Response]: {result}")
                    print(f"[Token Usage]: Tool '{tool_name}' consumed: {input_tokens} (input) + {output_tokens} (output) = {input_tokens + output_tokens} total tokens\n")
                    
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
                    print(f"[Token Usage]: Tool '{tool_name}' error output: {error_tokens} tokens\n")
                    
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
                print(f"[Token Usage]: Tool '{tool_name}' error output: {error_tokens} tokens\n")
                
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

    # Save to file
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
        filename = log_dir / f"session_token_usage_{time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(session_summary, f, indent=4)
        print(f"[Token Logger] Token usage logged to: {filename}")
    except Exception as e:
        print(f"[Token Logger Warning] Failed to save token log to file: {e}")

if __name__ == "__main__":
    default_prompt = (
        "Search for 'AI Engineer' jobs on naukri.com using the direct URL modification tool. "
        "Open the first job listing. On the job details page, find and click the 'Apply' button "
        "using the specialized tool, then stop execution and keep the browser open."
    )
    
    print("Welcome to the Browser Automation LLM Agent Demo!")
    print("Press Enter to use the default prompt, or enter a custom prompt below.")
    print(f"Default prompt: \"{default_prompt}\"")
    
    try:
        user_prompt = input("\nEnter prompt: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        sys.exit(0)

    prompt = user_prompt if user_prompt else default_prompt
    run_browser_agent(prompt)
