import os
import base64
import sys
import time
import random
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, SystemMessage
import async_logger

# Ensure parent and current directories are on path to allow imports
sys.path.append(str(Path(__file__).parent.resolve()))
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
    select_custom_combobox_option,
    set_checkbox_state,
    upload_file,
    generate_fill_values,
    close_browser_session,
    PersistentBrowserManager,
    get_compressed_dom,
    save_chat_transcript,
    fill_entire_form,
    update_agent_memory,
    os_level_mouse_keyboard_action
)

# Configure Stream Encoding for Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Force Browser Incognito/Non-Persistent Mode
os.environ["BROWSER_INCOGNITO"] = "true"

# Load environment variables
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

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

def analyze_page_layout_screenshot(page) -> str:
    """
    Takes a full-page screenshot and sends it to the Gemini model to identify
    which fields are required and which buttons must be clicked first.
    Returns the text analysis from the LLM.
    """
    try:
        screenshot_bytes = page.screenshot(full_page=True, type="png")
        base64_image = base64.b64encode(screenshot_bytes).decode('utf-8')
    except Exception as e:
        print(f"[Workday Agent Warning] Failed to take page screenshot: {e}")
        return "Failed to take screenshot."

    # Get list of form fields with selectors to associate visual layout with selectors
    from browser_tools import get_form_fields
    fields_desc = get_form_fields.invoke({})

    provider = os.getenv("LLM_PROVIDER", "google").lower()
    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            print("[Workday Agent Warning] DEEPSEEK_API_KEY is not set.")
            return "DeepSeek API key missing. Skipping visual analysis."
        api_base = os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com/v1"
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        
        print(f"[Workday Agent] Initializing ChatDeepSeek model='{model_name}' for visual analysis...")
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
        
        print(f"[Workday Agent] Initializing ChatOpenAI local model='{model_name}' for visual analysis...")
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
            print("[Workday Agent Warning] GEMINI_API_KEY / GOOGLE_API_KEY is not set.")
            return "Gemini API key missing. Skipping visual analysis."
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        
        print(f"[Workday Agent] Initializing ChatGoogleGenerativeAI model='{model_name}' for visual analysis...")
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = ChatGoogleGenerativeAI(
            model=model_name,
            api_key=api_key,
            temperature=0.0
        )

    prompt_text = (
        "You are analyzing a screenshot of a Workday job application page. "
        "Your task is to identify and list:\n"
        "1. Which fields are required to be filled and must be searched for within the webpage's code, along with their CSS selectors and the respective values that should be filled (Candidate: John Doe, johndoe@gmail.com, Phone: 9876543210, Address: 123 Main Street, City: Bengaluru, Postal Code: 560001).\n"
        "2. Which fields require dropdown selection or clicking on buttons/checkboxes instead of standard text input, specifying their selectors and what option to select or button/checkbox to click.\n\n"
        "Here is the list of form fields and their CSS selectors currently found on the page:\n"
        f"{fields_desc}\n\n"
        "Match the visual layout in the screenshot to these selectors and provide a clear mapping of fields to fill (with their selectors and values) and buttons/selections to click."
    )

    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt_text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_image}"}
            }
        ]
    )

    print(f"[Workday Agent] Sending page layout snapshot to '{model_name}' for visual analysis...")
    try:
        response = model.invoke([message])
    except Exception as e:
        print(f"[Workday Agent Warning] Multimodal vision analysis failed (possibly no vision support on local model): {e}")
        print("[Workday Agent] Falling back to text-only layout description analysis...")
        text_message = HumanMessage(content=prompt_text)
        response = model.invoke([text_message])

    # Log the token usage of this layout analysis step to another log file
    llm_in = 0
    llm_out = 0
    if hasattr(response, 'usage_metadata') and response.usage_metadata:
        llm_in = response.usage_metadata.get('input_tokens', 0)
        llm_out = response.usage_metadata.get('output_tokens', 0)

    # Log to the unified session log file
    try:
        from browser_tools import log_api_call
        log_api_call(
            caller_name="Screenshot Layout Analysis",
            model_name=model_name,
            input_tokens=llm_in,
            output_tokens=llm_out,
            sent_data=prompt_text,
            response_data=response.content
        )
    except Exception as e:
        print(f"[Workday Agent Warning] Failed to log unified API call: {e}")

    try:
        from pathlib import Path
        import json
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        filename = log_dir / f"screenshot_analysis_token_log_{time.strftime('%Y%m%d_%H%M%S')}.json"
        
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "llm_input_tokens": llm_in,
            "llm_output_tokens": llm_out,
            "total_tokens": llm_in + llm_out,
            "prompt": prompt_text[:500] + "..."
        }
        
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(log_entry, f, indent=4)
        print(f"[Workday Agent Token Logger] Dedicated screenshot analysis token log saved to: {filename}")
    except Exception as e:
        print(f"[Workday Agent Warning] Failed to save screenshot analysis token log: {e}")

    return response.content


def handle_workday_how_did_you_hear_about_us(page) -> bool:
    """
    Programmatically selects 'Job Board > Naukri' for 'How Did You Hear About Us?' question
    without invoking the LLM model.
    """
    try:
        # Check if the question label is present on the page
        has_question = page.locator("text=/How Did You Hear About Us/i").first.is_visible()
        if not has_question:
            return False
            
        # We search for data-automation-id="multiSelectContainer"
        multiselect = page.locator('[data-automation-id="multiSelectContainer"]').first
        if not multiselect.is_visible():
            return False
            
        # Check if "Naukri" is already selected to avoid re-clicking
        selected_text = multiselect.inner_text()
        if "Naukri" in selected_text:
            return False
            
        print("[Workday Programmatic] 'How Did You Hear About Us?' field with multiSelectContainer detected.")
        
        # Step 1: Click on the multiSelectContainer element
        print("[Workday Programmatic] Clicking multiSelectContainer...")
        multiselect.scroll_into_view_if_needed()
        multiselect.click()
        
        # Step 2: Wait for about 2 seconds
        page.wait_for_timeout(2000)
        
        # Step 3: Search for promptLeafNode elements
        prompt_leaves = page.locator('[data-automation-id="promptLeafNode"], .promptLeafNode, promptLeafNode')
        
        # Step 4: Within these elements, search for data-automation-id="promptOption" and data-automation-label="Job Board"
        job_board_option = prompt_leaves.locator('[data-automation-id="promptOption"][data-automation-label="Job Board"]').first
        if not job_board_option.is_visible():
            job_board_option = prompt_leaves.locator('[data-automation-label="Job Board"]').first
        if not job_board_option.is_visible():
            job_board_option = prompt_leaves.locator("text=/Job Board/i").first
            
        if job_board_option.is_visible():
            print("[Workday Programmatic] Found 'Job Board' option. Clicking it...")
            job_board_option.click()
            page.wait_for_timeout(1000) # Wait a moment for children to load
            
            # Step 5: Search for "Naukri" within the loaded elements and click
            naukri_option = page.locator("text=/Naukri/i").first
            if not naukri_option.is_visible():
                naukri_option = page.locator('[data-automation-id="promptOption"]').filter(has_text="Naukri").first
            
            if naukri_option.is_visible():
                print("[Workday Programmatic] Found 'Naukri' option. Clicking it...")
                naukri_option.click()
                page.wait_for_timeout(1000)
                print("[Workday Programmatic] Successfully selected 'Naukri' under 'Job Board'.")
                return True
            else:
                print("[Workday Programmatic] Warning: 'Naukri' option not found in loaded elements.")
        else:
            print("[Workday Programmatic] Warning: 'Job Board' option not found within promptLeafNodes.")
    except Exception as e:
        print(f"[Workday Programmatic Error] Failed to handle 'How Did You Hear About Us' dropdown: {e}")
    return False


def run_workday_agent(resume_path: str, target_url: str = None):
    """
    Runs the Workday Form Applier Agent.
    If target_url is provided, it navigates to the URL first.
    If not, it assumes the browser is already open on a Workday page and proceeds to scan and fill.
    """
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
        
        print(f"[Workday Agent] Initializing ChatDeepSeek model='{model_name}'...")
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
        
        print(f"[Workday Agent] Initializing ChatOpenAI local model='{model_name}' at base='{api_base}'...")
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
        
        print(f"[Workday Agent] Initializing ChatGoogleGenerativeAI model='{model_name}'...")
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = ChatGoogleGenerativeAI(
            model=model_name,
            api_key=api_key,
            temperature=0.0
        )

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
        select_custom_combobox_option,
        set_checkbox_state,
        upload_file,
        generate_fill_values,
        close_browser_session,
        get_compressed_dom,
        fill_entire_form,
        os_level_mouse_keyboard_action
    ]

    model_with_tools = model.bind_tools(tools)

    print("\n--- Starting Workday Apply Agent Execution ---")
    print(f"Target URL: {target_url or 'Already active browser session'}\n")

    # Construct initial instructions based on whether URL navigation is required
    if target_url:
        start_step = f"1. Open the website using the `open_website` tool on URL: {target_url}\n2. Locate and click the 'Apply' or 'Apply Now' button. If an options dropdown or modal opens, click 'Apply Manually'.\n"
    else:
        start_step = "1. You are already on the Workday page or form (or redirected to it). Check if you need to click 'Apply' or 'Apply Manually', or if you are already on the login or form page. Scan the page using `get_form_fields` or get accessibility tree to find out.\n"

    prompt = (
        f"You are a helpful browser automation agent. Your task is to apply for the job on Workday. "
        f"Here are the instructions to guide you:\n\n"
        f"{start_step}"
        "3. Handling Account Creation/Sign In Gates:\n"
        "   Workday forms require an account. If you see a Sign In form (asking for Email Address and Password):\n"
        "   - Look for a button or link to 'Create Account' and click it.\n"
        "   - On the Create Account form, fill in:\n"
        "     * Email Address: johndoe@example.com\n"
        "     * Password: Password123!\n"
        "     * Confirm Password: Password123!\n"
        "     * Check the required policy/terms agreement checkbox(es).\n"
        "     * Click the submit button to create the account.\n"
        "   - If you are redirected back to a login form or if you already have an account, enter:\n"
        "     * Email Address: johndoe@example.com\n"
        "     * Password: Password123!\n"
        "     * Click 'Sign In' or 'Log In'.\n\n"
        "4. Filling the Application Form Manually page-by-page:\n"
        "   Once the main application pages load (e.g. 'My Information', 'My Experience', 'Application Questions', 'Voluntary Disclosures', 'Review'):\n"
        "   - Call `get_form_fields` to scan all input fields on the current page.\n"
        "   - Pass the output of `get_form_fields` to the `generate_fill_values` tool to get a JSON dictionary mapping CSS selectors to their appropriate fill values.\n"
        "   - Formulate a JSON list of specifications mapping selectors to values and types (text, select, checkbox, custom_combobox, file).\n"
        "   - Use the `fill_entire_form` tool to fill out all the fields on the current page at once. E.g. map text inputs to type='text', checkboxes/radios to type='checkbox', selects to type='select', custom dropdowns to type='custom_combobox', and file uploads to type='file' (setting value to the absolute file path, e.g. the resume path).\n"
        "   - Use individual tools (such as `input_text_into_element`) only as a fallback if batch filling fails.\n"
        "   - Once all fields on the current page are populated, click the 'Next' or 'Submit' button to progress to the next page.\n"
        "   - Repeat this scan -> generate values -> fill -> Next workflow for each subsequent page of the application.\n\n"
        "5. Final Review & Keep Browser Open:\n"
        "   - Keep progressing until you reach the final 'Review' or confirmation screen.\n"
        "   - Once the review page is reached or you have successfully filled all fields, stop execution.\n"
        "   - DO NOT close the browser context. Keep the browser open so the final submission can be inspected.\n\n"
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
        "  \"completed_steps\": [\"Opened workday portal\", \"Uploaded resume\"],\n"
        "  \"extracted_data\": {\"candidate_name\": \"John Doe\"},\n"
        "  \"next_immediate_step\": \"Fill out work experience page\"\n"
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
    
    llm_token_logs = []
    tool_token_logs = []
    llm_call_token_logs = []
    total_llm_input = 0
    total_llm_output = 0
    total_tool_input = 0
    total_tool_output = 0

    manager = PersistentBrowserManager.get_instance()
    session_id = getattr(manager, "session_id", None) or time.strftime("%Y%m%d_%H%M%S")

    try:
        max_steps = 30
        last_response_content = None
        previous_page_state = ""
        for step in range(max_steps):
            # Programmatically handle "How Did You Hear About Us?" Workday question if present
            try:
                manager = PersistentBrowserManager.get_instance()
                if manager.page and not manager.page.is_closed():
                    handle_workday_how_did_you_hear_about_us(manager.page)
            except Exception as e:
                print(f"[Workday Agent Warning] Programmatic dropdown check failed: {e}")

            # Check if the page state has changed to perform screenshot layout analysis
            state_changed = False
            try:
                manager = PersistentBrowserManager.get_instance()
                if manager.page and not manager.page.is_closed():
                    # Wait for navigation/load state to settle
                    try:
                        manager.page.wait_for_load_state("networkidle", timeout=3000)
                    except Exception:
                        pass
                    
                    new_state = f"{manager.page.url}"
                    step_element = manager.page.locator(r'text=/step \d+ of \d+/i').first
                    if step_element.is_visible():
                        new_state += f"_{step_element.inner_text()}"
                    
                    if new_state != previous_page_state:
                        state_changed = True
                        previous_page_state = new_state
            except Exception as e:
                print(f"[Workday Agent Warning] Page state check failed: {e}")

            if state_changed:
                try:
                    manager = PersistentBrowserManager.get_instance()
                    if manager.page and not manager.page.is_closed():
                        print(f"[Workday Agent Step {step + 1}] New page layout detected. Performing visual layout screenshot analysis...")
                        analysis_plan = analyze_page_layout_screenshot(manager.page)
                        messages.append(HumanMessage(content=f"Visual Analysis of current page layout (use this plan to fill the page efficiently):\n{analysis_plan}"))
                except Exception as e:
                    print(f"[Workday Agent Warning] Layout analysis failed: {e}")

            # Update memory state (pruning and scratchpad maintenance)
            update_agent_memory(messages, state_summary, last_response_content, keep_last_n_tool_outputs=2)

            print(f"[Workday Agent Step {step + 1}] Invoking LLM ({provider.upper()})...")
            try:
                response = invoke_model_with_retry(model_with_tools, messages)
            except Exception as e:
                print(f"\n[Workday Agent Error]: API call failed: {e}")
                break
                
            messages.append(response)
            last_response_content = response.content
            save_chat_transcript("workday", messages, session_id)

            llm_in = 0
            llm_out = 0
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                llm_in = response.usage_metadata.get('input_tokens', 0)
                llm_out = response.usage_metadata.get('output_tokens', 0)
                total_llm_input += llm_in
                total_llm_output += llm_out
            
            # Log to the unified session log file
            try:
                sent_msgs = [{"role": type(m).__name__, "content": m.content} for m in messages[:-1]]
                from browser_tools import log_api_call
                if response.tool_calls:
                    log_api_call(
                        caller_name="Workday Agent API Call (requested tools)",
                        model_name=model_name,
                        input_tokens=llm_in,
                        output_tokens=llm_out,
                        sent_data={"messages": sent_msgs},
                        response_data={"content": response.content, "tool_calls": response.tool_calls}
                    )
                else:
                    log_api_call(
                        caller_name="Workday Agent API Call (final)",
                        model_name=model_name,
                        input_tokens=llm_in,
                        output_tokens=llm_out,
                        sent_data={"messages": sent_msgs},
                        response_data={"content": response.content}
                    )
            except Exception as e:
                print(f"[Workday Agent Warning] Failed to log unified API call: {e}")

            llm_token_logs.append({
                "step": step + 1,
                "input_tokens": llm_in,
                "output_tokens": llm_out,
                "total_tokens": llm_in + llm_out
            })

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
                print(f"\n[Workday Agent Thoughts]:\n{response.content}\n")

            if not response.tool_calls:
                print("[Workday Agent Execution Complete]")
                break

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                input_tokens = model.get_num_tokens(str(tool_args))
                print(f"[Workday Agent Tool Call]: {tool_name} with args {tool_args} | Input Size: {input_tokens} tokens")

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
                            print(f"[Workday Agent Warning] Failed to log tool execution: {le}")

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
                        save_chat_transcript("workday", messages, session_id)
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
                            print(f"[Workday Agent Warning] Failed to log tool execution failure: {le}")

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
                        save_chat_transcript("workday", messages, session_id)
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
                        print(f"[Workday Agent Warning] Failed to log unregistered tool error: {le}")

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
                    save_chat_transcript("workday", messages, session_id)

        else:
            print("[Workday Agent Warning]: Reached maximum steps without completion.")
    except KeyboardInterrupt:
        print("\n" + "="*50)
        print("SESSION TOKEN USAGE SUMMARY (FORCE CLOSED)")
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

        save_chat_transcript("workday", messages, session_id)

        session_summary = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "force_closed",
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
            "tool_calls": tool_token_logs,
            "llm_call_token_logs": llm_call_token_logs
        }
        try:
            log_dir = Path(__file__).parent.parent / "logs"
            log_dir.mkdir(exist_ok=True)
            filename = log_dir / f"session_token_usage_workday_force_closed_{time.strftime('%Y%m%d_%H%M%S')}.json"
            import json
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(session_summary, f, indent=4)
            print(f"[Workday Agent Token Logger] Token usage logged to: {filename}")
        except Exception as e:
            print(f"[Workday Agent Token Logger Warning] Failed to save token log to file: {e}")
        raise KeyboardInterrupt
    else:
        print("[Workday Agent Warning]: Reached maximum steps without completion.")

    # Log token usage summary
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
        "tool_calls": tool_token_logs,
        "llm_call_token_logs": llm_call_token_logs
    }

    try:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        filename = log_dir / f"session_token_usage_workday_{time.strftime('%Y%m%d_%H%M%S')}.json"
        import json
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(session_summary, f, indent=4)
        print(f"[Workday Agent Token Logger] Token usage logged to: {filename}")
        
        # Also write the dedicated LLM call token usage file
        llm_log_filename = log_dir / f"llm_call_token_usage_workday_{time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(llm_log_filename, "w", encoding="utf-8") as f:
            json.dump(llm_call_token_logs, f, indent=4)
        print(f"[Workday Agent Token Logger] Dedicated LLM call token usage logged to: {llm_log_filename}")
    except Exception as e:
        print(f"[Workday Agent Token Logger Warning] Failed to save token log to file: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Workday Form Applier Agent")
    parser.add_argument("url", nargs="?", help="The Workday job application URL")
    args = parser.parse_args()

    # Create dummy resume if needed
    dummy_resume = Path(__file__).parent / "testcode" / "dummy_resume.pdf"
    if not dummy_resume.exists():
        dummy_resume.write_bytes(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/Resources << >>\n/MediaBox [0 0 595.275 841.889]\n/Contents 4 0 R\n>>\nendobj\n4 0 obj\n<<\n/Length 15\n>>\nstream\nBT /F1 12 Tf ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\n0000000212 00000 n\ntrailer\n<<\n/Size 5\n/Root 1 0 R\n>>\nstartxref\n278\n%%EOF\n")

    target = args.url or "https://kimberlyclark.wd1.myworkdayjobs.com/en-US/GLOBAL/job/IT-Centre-Bengaluru-GDTC/AI-Engineer_885971-2"
    try:
        run_workday_agent(resume_path=str(dummy_resume.resolve()), target_url=target)
    except KeyboardInterrupt:
        print("\nExiting.")
        sys.exit(0)
