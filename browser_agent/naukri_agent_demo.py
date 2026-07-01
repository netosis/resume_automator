import os
import sys
import time
import random
import re
import json
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, SystemMessage
from js_templates import NAUKRI_JOB_STATUS_CHECK_JS, DETECT_NAUKRI_POPUP_JS, GET_NAUKRI_CHATBOT_A11Y_JS
import async_logger
import copy

# Reconfigure stdout/stderr to UTF-8 on Windows to avoid cp1252/charmap print crashes
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def invoke_model_with_retry(model, messages, max_retries=5, initial_delay=2.0):
    """
    Invokes the model with exponential backoff retry for 429 (Rate Limit),
    503 (Service Unavailable), and Ollama connection errors.
    """
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            return model.invoke(messages)
        except Exception as e:
            err_msg = str(e)
            is_rate_limit = "429" in err_msg or "ResourceExhausted" in err_msg or "quota" in err_msg.lower()
            is_service_unavailable = "503" in err_msg or "ServiceUnavailable" in err_msg or "unavailable" in err_msg.lower()
            is_ollama_conn_err = "Connection refused" in err_msg or "ConnectError" in err_msg or "connect error" in err_msg.lower()
            
            if (is_rate_limit or is_service_unavailable or is_ollama_conn_err) and attempt < max_retries - 1:
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
    update_agent_memory,
    os_level_mouse_keyboard_action,
    close_browser_on_interrupt
)
from pyautogui_manager import PyAutoGUIManager
from naukri_tools import (
    naukri_job_fetch,
    search_naukri_via_url,
    manage_naukri_popup_question,
    manage_naukri_chatbot,
    click_naukri_apply_button
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

def extract_job_role(prompt: str) -> str:
    """
    Extracts the job role from the user prompt. Looks for quoted strings
    or keywords like 'for ... jobs'.
    """
    match = re.search(r"['\"]([^'\"]+)['\"]", prompt)
    if match:
        return match.group(1)
    
    match = re.search(r"for\s+(.+?)\s+jobs", prompt, re.IGNORECASE)
    if match:
        return match.group(1)
        
    return "AI Engineer"

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
    elif provider == "ollama":
        api_base = os.getenv("OLLAMA_API_BASE", os.getenv("LOCAL_API_BASE", "http://localhost:11434/v1"))
        model_name = os.getenv("OLLAMA_MODEL", os.getenv("LOCAL_MODEL", "qwen2.5"))
        api_key = os.getenv("OLLAMA_API_KEY", os.getenv("LOCAL_API_KEY", "local"))
        soft_limit = int(os.getenv("OLLAMA_SOFT_TOKEN_LIMIT", "35000"))
        hard_limit = int(os.getenv("OLLAMA_HARD_TOKEN_LIMIT", "50000"))

        print(
            f"Initializing OllamaChunkedModel model='{model_name}' at base='{api_base}' "
            f"(soft_limit={soft_limit}, hard_limit={hard_limit})..."
        )
        from ollama_chunked_model import OllamaChunkedModel
        model = OllamaChunkedModel(
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
            temperature=0.0,
            soft_token_limit=soft_limit,
            hard_token_limit=hard_limit,
            verbose=True,
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
        naukri_job_fetch,
        click_naukri_apply_button,
        search_naukri_via_url,
        close_browser_session,
        get_form_fields,
        select_dropdown_option,
        set_checkbox_state,
        upload_file,
        get_compressed_dom,
        close_current_tab,
        go_back,
        fill_entire_form,
        manage_naukri_popup_question,
        manage_naukri_chatbot,
        os_level_mouse_keyboard_action
    ]

    # Bind tools to the model
    model_with_tools = model.bind_tools(tools)

    print("\n--- Starting Naukri Browser Agent Execution ---")
    print(f"Task Prompt: {prompt}\n")

    # Token tracking variables
    llm_token_logs = []
    tool_token_logs = []
    
    total_llm_input = 0
    total_llm_output = 0
    total_tool_input = 0
    total_tool_output = 0

    # 1. Programmatic job openings preparation
    job_role = extract_job_role(prompt)
    print(f"[Naukri Prep] Extracted job role: '{job_role}'")
    
    sanitized_title = job_role.lower().strip()
    sanitized_title = re.sub(r'[^a-z0-9]+', '-', sanitized_title)
    sanitized_title = sanitized_title.strip('-')
    search_url = f"https://www.naukri.com/{sanitized_title}-jobs-4"
    
    manager = PersistentBrowserManager.get_instance()
    page = manager.get_page()
    
    print("[Naukri Prep] Initializing browser flow by navigating to Google first...")
    page.goto("https://www.google.com", wait_until="load")
    page.wait_for_timeout(random.randint(1500, 2500))
    
    # Calibrate PyAutoGUI screen coordinates via UI Automation.
    # BraveInfoBarContainerView.bottom gives us the exact absolute Y pixel
    # where the browser content area starts (below tabs, address bar, and any
    # infobar such as the --no-sandbox warning). All subsequent move_and_click
    # calls will use this offset instead of the less reliable JS-based fallback.
    print("[Naukri Prep] Calibrating PyAutoGUI screen offsets via UI Automation...")
    PyAutoGUIManager.get_instance().calibrate_browser_offsets()
    
    print(f"[Naukri Prep] Navigating to: {search_url}")
    page.goto(search_url, wait_until="load")
    page.wait_for_timeout(random.randint(2750, 3250))
    
    # Locate all job cards matching `.srp-jobtuple-wrapper`
    job_cards_locator = page.locator(".srp-jobtuple-wrapper")
    card_count = job_cards_locator.count()
    
    if card_count == 0:
        print("[Naukri Prep] No job cards found. Waiting another 3 seconds for search results...")
        page.wait_for_timeout(random.randint(2750, 3250))
        job_cards_locator = page.locator(".srp-jobtuple-wrapper")
        card_count = job_cards_locator.count()
        
    print(f"[Naukri Prep] Found {card_count} job postings on the search page.")
    
    search_page = page
    valid_tabs = []
    
    # File to store skipped third-party job URLs
    script_dir = os.path.dirname(os.path.abspath(__file__))
    outputs_dir = os.path.join(script_dir, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    skipped_file_path = os.path.join(outputs_dir, "skipped_third_party_jobs.txt")
    
    def run_agent_on_active_tab(job_page) -> bool:
        """
        Runs the stateful LLM agent loop on a single open job description page tab.
        Returns True if successfully applied, False otherwise.
        """
        state_summary = {
            "completed_steps": [],
            "extracted_data": {},
            "next_immediate_step": ""
        }

        agent_messages = [
            HumanMessage(content=(
                f"You are a helpful browser automation agent. Your task is: Answer the recruiter popup questions / chatbot drawer on the page to complete the job application. "
                "The Apply button has already been clicked programmatically and an active questions modal or chatbot drawer is visible on the screen.\n"
                "Your workflow is:\n"
                "1. If it is a recruiter question popup, use the 'manage_naukri_popup_question' tool to detect and answer the questions iteratively until completed.\n"
                "2. If it is a chatbot drawer (class 'chatbot_MessageContainer'), use the 'manage_naukri_chatbot' tool to extract the chatbot's accessibility tree of questions/items. Then, use browser tools ('click_on_element', 'input_text_into_element', 'select_dropdown_option', 'set_checkbox_state', or 'fill_entire_form') to fill the fields / checkboxes / dropdowns and click the choice or submit buttons. Call 'manage_naukri_chatbot' iteratively to check for new questions after answering until the chatbot is completed.\n"
                "3. Once you have completed all questions and the application is submitted, complete your turn. Do NOT close the browser session or close the tab itself. Just confirm completion.\n"
                "IMPORTANT: Do not attempt to search on naukri.com or click on any search listings page.\n"
                "Do not close the browser session at the end. Keep the browser open.\n\n"
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
                "  \"completed_steps\": [\"Apply button clicked\", \"Answering questions modal\"],\n"
                "  \"extracted_data\": {\"job_title\": \"AI Engineer\"},\n"
                "  \"next_immediate_step\": \"Answer recruiter popup questions\"\n"
                "}\n"
                "</scratchpad>\n"
                "Do not omit this block from your response! Always output it."
            )),
            SystemMessage(content=f"### CURRENT AGENT STATE SUMMARY:\n{json.dumps(state_summary, indent=2)}")
        ]

        nonlocal total_llm_input, total_llm_output, total_tool_input, total_tool_output, llm_token_logs, tool_token_logs

        full_messages = [copy.deepcopy(msg) for msg in agent_messages]
        _TOKEN_TRACKER["messages"] = full_messages
        session_id = async_logger.get_session_id()

        max_steps = 40
        last_response_content = None
        applied_successfully = False

        for step in range(max_steps):
            # Update memory state (pruning and scratchpad maintenance)
            update_agent_memory(agent_messages, state_summary, last_response_content, keep_last_n_tool_outputs=2)

            # Sync updated state summary SystemMessage into full_messages
            scratchpad_content = f"### CURRENT AGENT STATE SUMMARY:\n{json.dumps(state_summary, indent=2)}"
            for idx, msg in enumerate(full_messages):
                if isinstance(msg, SystemMessage) and msg.content.startswith("### CURRENT AGENT STATE SUMMARY:"):
                    full_messages[idx] = copy.deepcopy(SystemMessage(content=scratchpad_content))
                    break

            # Programmatically check for recruiter popup or chatbot drawer if application is not yet successful
            try:
                page_text = job_page.locator("body").inner_text().lower()
                if "successfully applied" in page_text or "application submitted" in page_text or "applied successfully" in page_text:
                    applied_successfully = True
                    print(f"  [Job Agent Step {step + 1}] Detected application success in page text.")
                
                if not applied_successfully:
                    popup_info = job_page.evaluate(DETECT_NAUKRI_POPUP_JS)
                    chatbot_info = job_page.evaluate(GET_NAUKRI_CHATBOT_A11Y_JS)
                    
                    system_guidance = ""
                    if popup_info and popup_info.get("detected"):
                        system_guidance = (
                            f"### IMPORTANT ACTIVE RECUPT QUESTION MODAL DETECTED:\n"
                            f"Question: \"{popup_info['question']}\"\n"
                            f"You MUST use the 'manage_naukri_popup_question' tool to answer it. Do NOT try to scroll or perform other actions until this modal is handled.\n"
                        )
                    elif chatbot_info and chatbot_info.get("detected"):
                        # Update chatbot_tree.json with job title and company grouping
                        try:
                            items = chatbot_info.get("items", [])
                            title_info = job_page.evaluate('''() => {
                                let title = document.querySelector(".jd-header-title")?.innerText || document.querySelector("h1")?.innerText || document.title || "Unknown Job";
                                let company = document.querySelector(".jd-header-comp-name")?.innerText || document.querySelector(".company-name")?.innerText || "Unknown Company";
                                return {title: title, company: company};
                            }''')
                            header_key = f"{title_info['title']} at {title_info['company']}"
                            
                            tree_path = os.path.join(os.path.dirname(__file__), "outputs", "chatbot_tree.json")
                            os.makedirs(os.path.dirname(tree_path), exist_ok=True)
                            
                            tree_data = {}
                            if os.path.exists(tree_path):
                                try:
                                    with open(tree_path, "r", encoding="utf-8") as f:
                                        data = json.load(f)
                                        if isinstance(data, dict):
                                            tree_data = data
                                        elif isinstance(data, list):
                                            tree_data = {"Unknown Job at Unknown Company": data}
                                except Exception:
                                    pass
                            
                            tree_data[header_key] = items
                            with open(tree_path, "w", encoding="utf-8") as f:
                                json.dump(tree_data, f, indent=2)
                        except Exception as e:
                            print(f"  [Job Agent Warning] Failed to update chatbot_tree.json: {e}")

                        system_guidance = (
                            f"### IMPORTANT ACTIVE CHATBOT DRAWER DETECTED:\n"
                            f"A recruiter chatbot drawer is visible on the page.\n"
                            f"You MUST use the 'manage_naukri_chatbot' tool to retrieve and answer chatbot questions. Do NOT try to scroll or perform other actions.\n"
                        )
                    
                    if system_guidance:
                        # Append a system guidance instruction message to agent_messages before invoking LLM
                        # We can remove any previous system guidance message to avoid cluttering
                        agent_messages = [m for m in agent_messages if not (isinstance(m, SystemMessage) and ("ACTIVE RECUPT QUESTION" in m.content or "ACTIVE CHATBOT DRAWER" in m.content))]
                        sys_msg = SystemMessage(content=system_guidance)
                        agent_messages.append(sys_msg)

                        # Sync system guidance message into full_messages
                        full_messages = [m for m in full_messages if not (isinstance(m, SystemMessage) and ("ACTIVE RECUPT QUESTION" in m.content or "ACTIVE CHATBOT DRAWER" in m.content))]
                        full_messages.append(copy.deepcopy(sys_msg))
            except Exception as e:
                print(f"  [Job Agent Warning] Error during loop state checks: {e}")

            print(f"  [Job Agent Step {step + 1}] Invoking LLM ({provider.upper()})...")
            try:
                response = invoke_model_with_retry(model_with_tools, agent_messages)
            except Exception as e:
                print(f"\n  [Job Agent Error]: API call failed. Error: {e}")
                break

            agent_messages.append(response)
            full_messages.append(copy.deepcopy(response))
            last_response_content = response.content
            save_chat_transcript("naukri", full_messages, session_id)

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
                    llm_in = model.get_num_tokens(str(agent_messages[:-1]))
                    llm_out = model.get_num_tokens(response.content or "")
                except Exception:
                    pass

            total_llm_input += llm_in
            total_llm_output += llm_out

            # Update global tracker
            _TOKEN_TRACKER["total_llm_input"] = total_llm_input
            _TOKEN_TRACKER["total_llm_output"] = total_llm_output
            llm_token_logs.append({
                "step": step + 1,
                "input_tokens": llm_in,
                "output_tokens": llm_out,
                "total_tokens": llm_in + llm_out
            })

            # Print LLM API call tokens
            print(f"  [LLM API Call]: Sent: {llm_in} tokens | Returned: {llm_out} tokens")

            if response.content:
                print(f"\n  [Agent Thoughts]:\n{response.content}\n")

            # Fallback for DeepSeek tool call parsing when response.tool_calls is empty
            if not response.tool_calls and response.content:
                content_str = response.content
                if isinstance(content_str, list):
                    content_str = "\n".join([item["text"] for item in content_str if isinstance(item, dict) and "text" in item] + [item for item in content_str if isinstance(item, str)])
                
                has_ds_marker = "</｜｜DSML｜｜tool_calls>" in content_str or "<｜tool_calls｜>" in content_str
                
                # If DeepSeek marker is present, or if model mentions a tool but langchain failed to parse
                if has_ds_marker or "manage_naukri_chatbot" in content_str or "manage_naukri_popup_question" in content_str:
                    print("  [DeepSeek Fallback Parser] Detected unparsed tool call in response content. Attempting manual extraction...")
                    
                    # Clean up the DSML token from content to keep thoughts clean
                    response.content = content_str.replace("</｜｜DSML｜｜tool_calls>", "").replace("<｜tool_calls｜>", "").strip()
                    
                    # Determine which tool was intended
                    detected_tool = None
                    for t_name in ["manage_naukri_chatbot", "manage_naukri_popup_question"]:
                        if t_name in content_str:
                            detected_tool = t_name
                            break
                    if not detected_tool:
                        for t in tools:
                            if t.name in content_str:
                                detected_tool = t.name
                                break
                                
                    if detected_tool:
                        # Construct a synthetic tool call
                        synthetic_tool_call = {
                            "name": detected_tool,
                            "args": {"tool_summary": f"Fallback parse: handling active chatbot/popup via {detected_tool}"},
                            "id": f"fallback_call_{int(time.time())}"
                        }
                        # Populate response.tool_calls
                        response.tool_calls = [synthetic_tool_call]
                        print(f"  [DeepSeek Fallback Parser] Successfully extracted synthetic tool call: {synthetic_tool_call}")

            if not response.tool_calls:
                # Check state_summary or thoughts for applied success
                content_lower = (response.content or "").lower()
                if "applied" in content_lower or "success" in content_lower or "completed" in content_lower:
                    applied_successfully = True

                try:
                    sent_msgs = [{"role": type(m).__name__, "content": m.content} for m in agent_messages[:-1]]
                    log_api_call(
                        caller_name="Final Response",
                        model_name=model_name,
                        input_tokens=llm_in,
                        output_tokens=llm_out,
                        sent_data=sent_msgs,
                        response_data=response.content
                    )
                except Exception as e:
                    print(f"  [Agent Warning] Failed to log final API call: {e}")
                print("  [Job Agent Execution Complete]")
                break

            # Process tool calls
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                input_tokens = model.get_num_tokens(str(tool_args))
                print(f"  [Agent Tool Call]: {tool_name} with args {tool_args} | Input Size: {input_tokens} tokens")
                print(f"  [API Call Tokens for Tool '{tool_name}']: Sent to API: {llm_in} | Returned by Model: {llm_out}")

                # Log to the unified session log file specifically for this tool call
                try:
                    sent_msgs = [{"role": type(m).__name__, "content": m.content} for m in agent_messages[:-1]]
                    log_api_call(
                        caller_name=f"API Call requesting Tool: {tool_name}",
                        model_name=model_name,
                        input_tokens=llm_in,
                        output_tokens=llm_out,
                        sent_data={"messages": sent_msgs, "requested_tool_call": tool_call},
                        response_data={"content": response.content, "tool_calls": response.tool_calls}
                    )
                except Exception as e:
                    print(f"  [Agent Warning] Failed to log tool API call: {e}")

                matching_tool = next((t for t in tools if t.name == tool_name), None)
                if matching_tool:
                    try:
                        result = matching_tool.invoke(tool_args)
                        result_str = str(result)
                        
                        # Truncate A11y tree and Compressed DOM to save tokens
                        if "Accessibility Tree" in result_str:
                            result_str = result_str.split("Accessibility Tree")[0].strip()
                        if "Compressed DOM" in result_str:
                            result_str = result_str.split("Compressed DOM")[0].strip()
                            
                        tool_summary = tool_args.get("tool_summary", "")
                        if tool_summary:
                            result_str = f"Tool Summary: {tool_summary}\nResult: {result_str}"
                            
                        output_tokens = model.get_num_tokens(result_str)
                        print(f"  [Tool Response (Truncated)]: {result_str}")
                        print(f"  [Token Usage]: Tool '{tool_name}' consumed: {input_tokens} (input) + {output_tokens} (output) = {input_tokens + output_tokens} total tokens\n")

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
                            print(f"  [Agent Warning] Failed to log tool execution: {le}")

                        total_tool_input += input_tokens
                        total_tool_output += output_tokens

                        # Update global tracker
                        _TOKEN_TRACKER["total_tool_input"] = total_tool_input
                        _TOKEN_TRACKER["total_tool_output"] = total_tool_output
                        tool_token_logs.append({
                            "step": step + 1,
                            "tool_name": tool_name,
                            "args": tool_args,
                            "input_tokens": llm_in,
                            "output_tokens": output_tokens,
                            "status": "success"
                        })

                        tool_msg = ToolMessage(content=result_str, tool_call_id=tool_id)
                        agent_messages.append(tool_msg)
                        full_messages.append(copy.deepcopy(tool_msg))
                        save_chat_transcript("naukri", full_messages, session_id)

                        # If we used apply button or close tab tools, update success detection
                        if tool_name in ["click_naukri_apply_button", "click_on_element"]:
                            # If page text indicates success
                            try:
                                page_text = job_page.locator("body").inner_text().lower()
                                if "successfully applied" in page_text or "application submitted" in page_text or "applied successfully" in page_text:
                                    applied_successfully = True
                            except Exception:
                                pass
                    except Exception as e:
                        error_msg = f"Error running tool '{tool_name}': {str(e)}"
                        error_tokens = model.get_num_tokens(error_msg)
                        print(f"  [Tool Error]: {error_msg}")
                        print(f"  [Token Usage]: Tool '{tool_name}' error output: {error_tokens} tokens\n")

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
                            print(f"  [Agent Warning] Failed to log tool execution failure: {le}")

                        total_tool_input += input_tokens
                        total_tool_output += error_tokens

                        # Update global tracker
                        _TOKEN_TRACKER["total_tool_input"] = total_tool_input
                        _TOKEN_TRACKER["total_tool_output"] = total_tool_output
                        tool_token_logs.append({
                            "step": step + 1,
                            "tool_name": tool_name,
                            "args": tool_args,
                            "input_tokens": llm_in,
                            "output_tokens": error_tokens,
                            "status": "error",
                            "error": str(e)
                        })

                        tool_msg = ToolMessage(content=error_msg, tool_call_id=tool_id)
                        agent_messages.append(tool_msg)
                        full_messages.append(copy.deepcopy(tool_msg))
                        save_chat_transcript("naukri", full_messages, session_id)
                else:
                    error_msg = f"Tool '{tool_name}' is not registered."
                    error_tokens = model.get_num_tokens(error_msg)
                    print(f"  [Tool Error]: {error_msg}")
                    print(f"  [Token Usage]: Tool '{tool_name}' error output: {error_tokens} tokens\n")

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
                        print(f"  [Agent Warning] Failed to log unregistered tool error: {le}")

                    total_tool_input += input_tokens
                    total_tool_output += error_tokens

                    # Update global tracker
                    _TOKEN_TRACKER["total_tool_input"] = total_tool_input
                    _TOKEN_TRACKER["total_tool_output"] = total_tool_output
                    tool_token_logs.append({
                        "step": step + 1,
                        "tool_name": tool_name,
                        "args": tool_args,
                        "input_tokens": llm_in,
                        "output_tokens": error_tokens,
                        "status": "not_registered"
                    })

                    tool_msg = ToolMessage(content=error_msg, tool_call_id=tool_id)
                    agent_messages.append(tool_msg)
                    full_messages.append(copy.deepcopy(tool_msg))
                    save_chat_transcript("naukri", full_messages, session_id)
        return applied_successfully

    applied_count = 0
    opened_count = 0
    # max_jobs_to_open = random.randint(5, 7)
    max_jobs_to_open = 10
    print(f"[Naukri Agent] Target: Open {max_jobs_to_open} jobs in total and apply to those that are direct.")
    
    # Loop through cards and click titles to open in new tabs
    for i in range(card_count):
        if opened_count >= max_jobs_to_open:
            print(f"[Naukri Agent] Opened {opened_count} jobs (limit was {max_jobs_to_open}). Breaking sequential loop.")
            break
            
        # Locate the card again (dynamic access)
        card = page.locator(".srp-jobtuple-wrapper").nth(i)
        
        # Try multiple selectors for the job title link inside the card
        title_link = card.locator("a.title")
        if not title_link.count():
            title_link = card.locator("a[href*='job-listings']")
        if not title_link.count():
            title_link = card.locator("a").first
            
        if not title_link.count():
            print(f"[Naukri Prep] Skipping listing {i+1} (no title link found)")
            continue
            
        try:
            # Scroll into view
            title_link.scroll_into_view_if_needed()
            link_text = title_link.inner_text().strip()
            
            # Randomized delay before opening: 1 to 2 seconds
            open_delay = random.uniform(1.0, 2.0)
            print(f"[Naukri Prep] Waiting {open_delay:.2f}s before opening job {i+1}: '{link_text}'")
            page.wait_for_timeout(int(open_delay * 1000))
            
            # Click using slow cursor movements
            box = title_link.bounding_box()
            if box:
                viewport_x = box['x'] + box['width'] / 2
                viewport_y = box['y'] + box['height'] / 2
                
                print(f"[Naukri Prep] Moving mouse slowly to ({viewport_x:.1f}, {viewport_y:.1f}) and clicking...")
                
                # Click using PyAutoGUI
                with page.context.expect_page(timeout=15000) as new_page_info:
                    PyAutoGUIManager.get_instance().move_and_click(page, viewport_x, viewport_y)
                new_page = new_page_info.value
            else:
                # Fallback to standard locator click
                with page.context.expect_page(timeout=15000) as new_page_info:
                    title_link.click()
                new_page = new_page_info.value
            
            # Wait for new page to load
            new_page.wait_for_load_state("load")
            new_url = new_page.url
            opened_count += 1
            print(f"[Naukri Prep] Opened job {i+1} in new tab ({opened_count}/{max_jobs_to_open}): {new_url}")
            
            # The infobar (--no-sandbox warning) only appears on the original search tab.
            # New job tabs open without it, so the calibrated Y-offset must be cleared.
            PyAutoGUIManager.get_instance().reset_calibration()
            
            # Wait for content to settle
            new_page.wait_for_timeout(random.randint(1750, 2250))
            
            # Run JS evaluation to check for Applied or Third-Party Apply
            status_check = new_page.evaluate(NAUKRI_JOB_STATUS_CHECK_JS)
            
            is_applied = status_check.get("isApplied", False)
            is_third_party = status_check.get("isThirdParty", False)
            third_party_btn = status_check.get("buttonText", "")
            
            if is_applied:
                print(f"[Naukri Prep] Job {i+1} is ALREADY APPLIED. Skipping.")
                close_delay = random.uniform(5.0, 7.0)
                print(f"[Naukri Prep] Waiting {close_delay:.2f}s before closing tab...")
                new_page.wait_for_timeout(int(close_delay * 1000))
                new_page.close()
                
                # Switch back to search page to open the next one
                search_page.bring_to_front()
                manager.page = search_page
                # Re-apply UIA calibration: the infobar is back on the search tab.
                PyAutoGUIManager.get_instance().calibrate_browser_offsets()
            elif is_third_party:
                print(f"[Naukri Prep] Job {i+1} is a THIRD-PARTY post (Button: '{third_party_btn}'). Logging and skipping.")
                with open(skipped_file_path, "a", encoding="utf-8") as sf:
                    sf.write(f"Job Listing {i+1}: {link_text} | URL: {new_url} | Reason: Third-party apply ({third_party_btn})\n")
                close_delay = random.uniform(5.0, 7.0)
                print(f"[Naukri Prep] Waiting {close_delay:.2f}s before closing tab...")
                new_page.wait_for_timeout(int(close_delay * 1000))
                new_page.close()
                
                # Switch back to search page to open the next one
                search_page.bring_to_front()
                manager.page = search_page
                # Re-apply UIA calibration: the infobar is back on the search tab.
                PyAutoGUIManager.get_instance().calibrate_browser_offsets()
            else:
                print(f"[Naukri Agent] Job {i+1} is direct & unapplied. Starting application now!")
                manager.page = new_page
                new_page.bring_to_front()
                
                # 1. Programmatically click Apply button first without invoking LLM
                click_res = click_naukri_apply_button.invoke({})
                print(f"[Naukri Agent] Apply button clicked programmatically. Result:\n{click_res}")
                
                # Update page reference in case a new tab opened
                active_page = manager.get_page()
                
                # 2. Check and confirm if popup questions or chatbot drawer are active
                popup_info = active_page.evaluate(DETECT_NAUKRI_POPUP_JS)
                chatbot_info = active_page.evaluate(GET_NAUKRI_CHATBOT_A11Y_JS)
                
                has_popup = (popup_info and popup_info.get("detected")) or (chatbot_info and chatbot_info.get("detected"))
                
                success = False
                if has_popup:
                    print(f"[Naukri Agent] Confirmed: Active pop-up question or chatbot drawer is present! Initiating LLM agent to handle questions.")
                    # Run the stateful LLM agent loop to answer questions
                    success = run_agent_on_active_tab(active_page)
                else:
                    print(f"[Naukri Agent] No active popup questions or chatbot detected. Checking for applied confirmation.")
                    page_text = active_page.locator("body").inner_text().lower()
                    if "successfully applied" in page_text or "application submitted" in page_text or "applied successfully" in page_text:
                        print(f"[Naukri Agent] Job {i+1} successfully applied programmatically (no questions required)!")
                        success = True
                    else:
                        print(f"[Naukri Agent] No questions and no explicit confirmation, treating as successfully applied.")
                        success = True
                
                if success:
                    applied_count += 1
                    print(f"[Naukri Agent] Job {i+1} successfully applied! Applied count: {applied_count}")
                else:
                    print(f"[Naukri Agent] Job {i+1} application finished (not successfully or skipped).")
                
                # Close the job tab if not already closed
                try:
                    if not new_page.is_closed():
                        new_page.close()
                except Exception:
                    pass
                
                # Switch back to search page to open the next one
                try:
                    search_page.bring_to_front()
                    manager.page = search_page
                    # Re-apply UIA calibration: the infobar is back on the search tab.
                    PyAutoGUIManager.get_instance().calibrate_browser_offsets()
                except Exception:
                    pass
            
        except Exception as e:
            print(f"[Naukri Agent] Error processing job listing {i+1}: {e}")
            try:
                search_page.bring_to_front()
                manager.page = search_page
                # Ensure calibration is restored after any mid-job error.
                PyAutoGUIManager.get_instance().calibrate_browser_offsets()
            except Exception:
                pass

    # Close the search page tab now that we are completely done
    print("[Naukri Agent] Closing the search page tab.")
    try:
        search_page.close()
    except Exception:
        pass

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
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        filename = log_dir / f"naukri_token_usage_{time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(session_summary, f, indent=4)
        print(f"[Token Logger] Token usage logged to: {filename}")
    except Exception as e:
        print(f"[Token Logger Warning] Failed to save token log to file: {e}")

if __name__ == "__main__":
    default_prompt = (
        "Search for 'AI Engineer' jobs on naukri.com using the direct URL modification tool. "
        "Find and open 5 to 7 jobs, then apply to the ones that can be applied directly on naukri. "
        "For each job, open the job listing, click the 'Apply' button. If any chatbot / recruiter popups or drawer questions show up, "
        "use 'manage_naukri_chatbot' to detect and answer them iteratively until completed. "

        "If a new tab opens, handle the application, close the tab, and return to the main tab. "
        "Keep the browser open when complete."
    )
    
    print("Welcome to the Naukri Browser Automation LLM Agent Demo!")
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
        close_browser_on_interrupt()
        save_force_close_logs("naukri")
        sys.exit(0)
