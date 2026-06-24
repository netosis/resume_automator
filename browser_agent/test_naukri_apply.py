import os
import sys
import time
import random
import json
import copy
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage, SystemMessage

# Add browser_agent folder to path to allow imports
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
    go_back,
    fill_entire_form,
    PersistentBrowserManager,
    update_agent_memory,
    os_level_mouse_keyboard_action
)
from naukri_tools import (
    _get_llm_model,
    naukri_job_fetch,
    search_naukri_via_url,
    manage_naukri_popup_question,
    manage_naukri_chatbot,
    click_naukri_apply_button
)
from js_templates import DETECT_NAUKRI_POPUP_JS, GET_NAUKRI_CHATBOT_A11Y_JS

def run_test_apply(url: str):
    load_dotenv()
    
    print("\n=== Initializing Test Apply Script ===")
    print(f"Target URL: {url}\n")
    
    # Initialize the LLM
    model = _get_llm_model()
    model_name = getattr(model, "model_name", "unknown") or getattr(model, "model", "unknown")
    print(f"Model initialized: {model_name}")
    
    # Setup tools
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
        go_back,
        fill_entire_form,
        manage_naukri_popup_question,
        manage_naukri_chatbot,
        os_level_mouse_keyboard_action
    ]
    model_with_tools = model.bind_tools(tools)
    
    # Start browser manager
    manager = PersistentBrowserManager.get_instance()
    page = manager.get_page()
    
    print(f"[Test] Navigating directly to: {url}")
    page.goto(url, wait_until="load")
    page.wait_for_timeout(3000)
    
    # Programmatically click the Apply button first
    print("[Test] Clicking the Apply button programmatically...")
    click_res = click_naukri_apply_button.invoke({})
    print(f"[Test] Click Apply Result:\n{click_res}\n")
    
    active_page = manager.get_page()
    active_page.wait_for_timeout(2000)
    
    # Check if recruiter popup or chatbot is detected
    popup_info = active_page.evaluate(DETECT_NAUKRI_POPUP_JS)
    chatbot_info = active_page.evaluate(GET_NAUKRI_CHATBOT_A11Y_JS)
    
    has_popup = (popup_info and popup_info.get("detected")) or (chatbot_info and chatbot_info.get("detected"))
    
    if not has_popup:
        print("[Test] No active popup question or chatbot detected. Waiting 3 seconds to see if it loads...")
        active_page.wait_for_timeout(3000)
        popup_info = active_page.evaluate(DETECT_NAUKRI_POPUP_JS)
        chatbot_info = active_page.evaluate(GET_NAUKRI_CHATBOT_A11Y_JS)
        has_popup = (popup_info and popup_info.get("detected")) or (chatbot_info and chatbot_info.get("detected"))
        
    if not has_popup:
        print("[Test] Still no popup/chatbot detected. Checking if page text indicates successful apply.")
        page_text = active_page.locator("body").inner_text().lower()
        if "successfully applied" in page_text or "application submitted" in page_text or "applied successfully" in page_text:
            print("[Test Success] Job successfully applied programmatically without questions!")
            return
        else:
            print("[Test Info] No popup/chatbot and no success message. Treating as applied or manually completed.")
            return

    print("[Test] Active popup question or chatbot detected! Launching LLM agent to handle questions...")
    
    # Define agent state summary and messages
    state_summary = {
        "completed_steps": [],
        "extracted_data": {},
        "next_immediate_step": ""
    }
    
    agent_messages = [
        HumanMessage(content=(
            "You are a helpful browser automation agent. Your task is: Answer the recruiter popup questions / chatbot drawer on the page to complete the job application. "
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
            "Do not omit this block from your response! Always output it."
        )),
        SystemMessage(content=f"### CURRENT AGENT STATE SUMMARY:\n{json.dumps(state_summary, indent=2)}")
    ]
    
    max_steps = 20
    last_response_content = None
    applied_successfully = False
    
    for step in range(max_steps):
        # Update memory state
        update_agent_memory(agent_messages, state_summary, last_response_content, keep_last_n_tool_outputs=2)
        
        # Sync updated state summary
        scratchpad_content = f"### CURRENT AGENT STATE SUMMARY:\n{json.dumps(state_summary, indent=2)}"
        for idx, msg in enumerate(agent_messages):
            if isinstance(msg, SystemMessage) and msg.content.startswith("### CURRENT AGENT STATE SUMMARY:"):
                agent_messages[idx] = SystemMessage(content=scratchpad_content)
                break
                
        # Append guidance based on screen detection
        try:
            popup_info = active_page.evaluate(DETECT_NAUKRI_POPUP_JS)
            chatbot_info = active_page.evaluate(GET_NAUKRI_CHATBOT_A11Y_JS)
            system_guidance = ""
            if popup_info and popup_info.get("detected"):
                system_guidance = (
                    f"### IMPORTANT ACTIVE RECUPT QUESTION MODAL DETECTED:\n"
                    f"Question: \"{popup_info['question']}\"\n"
                    f"You MUST use the 'manage_naukri_popup_question' tool to answer it.\n"
                )
            elif chatbot_info and chatbot_info.get("detected"):
                system_guidance = (
                    f"### IMPORTANT ACTIVE CHATBOT DRAWER DETECTED:\n"
                    f"A recruiter chatbot drawer is visible on the page.\n"
                    f"You MUST use the 'manage_naukri_chatbot' tool to retrieve and answer chatbot questions.\n"
                )
            if system_guidance:
                agent_messages = [m for m in agent_messages if not (isinstance(m, SystemMessage) and ("ACTIVE RECUPT" in m.content or "ACTIVE CHATBOT" in m.content))]
                agent_messages.append(SystemMessage(content=system_guidance))
        except Exception as e:
            print(f"[Test Warning] Error during loop state checks: {e}")
            
        print(f"\n[Test Agent Step {step + 1}] Invoking LLM...")
        try:
            response = model_with_tools.invoke(agent_messages)
        except Exception as e:
            print(f"[Test Agent Error] API call failed: {e}")
            break
            
        agent_messages.append(response)
        last_response_content = response.content
        
        if response.content:
            print(f"[Test Agent Thoughts]:\n{response.content}\n")
            
        # Fallback for DeepSeek tool call parsing when response.tool_calls is empty
        if not response.tool_calls and response.content:
            content_str = response.content
            if isinstance(content_str, list):
                content_str = "\n".join([item["text"] for item in content_str if isinstance(item, dict) and "text" in item] + [item for item in content_str if isinstance(item, str)])
            
            has_ds_marker = "</｜｜DSML｜｜tool_calls>" in content_str or "<｜tool_calls｜>" in content_str
            if has_ds_marker or "manage_naukri_chatbot" in content_str or "manage_naukri_popup_question" in content_str:
                print("  [DeepSeek Fallback Parser] Detected unparsed tool call in response content. Attempting manual extraction...")
                response.content = content_str.replace("</｜｜DSML｜｜tool_calls>", "").replace("<｜tool_calls｜>", "").strip()
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
                    synthetic_tool_call = {
                        "name": detected_tool,
                        "args": {"tool_summary": f"Fallback parse: handling active chatbot/popup via {detected_tool}"},
                        "id": f"fallback_call_{int(time.time())}"
                    }
                    response.tool_calls = [synthetic_tool_call]
                    print(f"  [DeepSeek Fallback Parser] Successfully extracted synthetic tool call: {synthetic_tool_call}")

        if not response.tool_calls:
            content_lower = (response.content or "").lower()
            if "applied" in content_lower or "success" in content_lower or "completed" in content_lower:
                applied_successfully = True
            print("[Test Agent Step] No tool calls returned. Execution Complete.")
            break
            
        # Process tool calls
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]
            
            print(f"[Test Agent Tool Call] Invoking: {tool_name} with {tool_args}")
            matching_tool = next((t for t in tools if t.name == tool_name), None)
            if matching_tool:
                try:
                    result = matching_tool.invoke(tool_args)
                    result_str = str(result)
                    if "Accessibility Tree" in result_str:
                        result_str = result_str.split("Accessibility Tree")[0].strip()
                    print(f"[Test Tool Response]: {result_str[:400]}...")
                    
                    tool_msg = ToolMessage(content=result_str, tool_call_id=tool_id)
                    agent_messages.append(tool_msg)
                except Exception as e:
                    error_msg = f"Error running tool '{tool_name}': {str(e)}"
                    print(f"[Test Tool Error]: {error_msg}")
                    tool_msg = ToolMessage(content=error_msg, tool_call_id=tool_id)
                    agent_messages.append(tool_msg)
            else:
                error_msg = f"Tool '{tool_name}' is not registered."
                print(f"[Test Tool Error]: {error_msg}")
                tool_msg = ToolMessage(content=error_msg, tool_call_id=tool_id)
                agent_messages.append(tool_msg)
                
    print(f"\n[Test Finished] Applied successfully: {applied_successfully}")
    print("Keeping browser open for 60 seconds to allow you to review...")
    page.wait_for_timeout(60000)

if __name__ == "__main__":
    test_url = "https://lgsihrms.darwinbox.in/ms/candidatev2/a6914476a29263/careers/jobDetails/a6a2fb6db37ca4"
    try:
        run_test_apply(test_url)
    except KeyboardInterrupt:
        print("\nExiting script.")
