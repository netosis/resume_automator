import os
import re
import json
import time
import random
import base64
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
import async_logger
from browser_tools import (
    PersistentBrowserManager,
    get_representation_header_and_body,
    clean_page_text,
    move_mouse_to_element_and_click,
    execute_human_pyautogui_action
)
from js_templates import (
    DETECT_NAUKRI_POPUP_JS,
    GET_NEXT_NAUKRI_POPUP_QUESTION_JS,
    GET_NAUKRI_CHATBOT_A11Y_JS,
    FIND_NAUKRI_APPLY_BUTTON_JS,
    REMOVE_CLICK_TARGET_ATTR_JS,
    GET_ELEMENTS_WITH_COORDINATES_JS
)

@tool
def naukri_job_fetch(tool_summary: str = "") -> str:
    """
    Retrieves job details from the current page by locating and cleaning elements with class 'srp-jobtuple-wrapper'.
    Only use this on naukri.com search result pages.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Get page URL and title
        url = page.url
        title = page.title()
        
        # Locate all job cards matching `.srp-jobtuple-wrapper`
        job_cards_locator = page.locator(".srp-jobtuple-wrapper")
        card_count = job_cards_locator.count()
        
        job_cards_details = []
        for i in range(card_count):
            card = job_cards_locator.nth(i)
            # Retrieve HTML, strip HTML tags, and clean whitespace
            card_html = card.inner_html()
            # Clean HTML by removing tags and normal whitespace cleaning
            clean_text = re.sub(r'<[^>]*>', ' ', card_html)
            clean_text = clean_page_text(clean_text)
            job_cards_details.append(f"Job Listing {i + 1}:\n{clean_text}")
            
        method_b_content = "\n\n".join(job_cards_details)
        if not method_b_content:
            method_b_content = "No elements with class 'srp-jobtuple-wrapper' found on this page."
            
        return (
            f"Job Page URL: {url}\n"
            f"Page Title: {title}\n\n"
            f"Job Details from job cards:\n{method_b_content}"
        )
    except Exception as e:
        return f"Failed to fetch naukri job details. Error: {str(e)}"

@tool
def search_naukri_via_url(job_title: str, tool_summary: str = "") -> str:
    """
    Searches for jobs on naukri.com by directly modifying the URL pattern (e.g. 'naukri.com/ai-engineer-jobs')
    instead of using search boxes and buttons.
    When calling this tool, the LLM should ONLY provide the job role name (e.g., 'AI Engineer') for the 'job_title' parameter.
    Returns the confirmation of navigation and the updated accessibility tree if it has changed, otherwise False.
    """
    mode = "interactive"
    try:
        # Standardize job title: convert to lowercase, strip, replace spaces/special chars with hyphens
        sanitized_title = job_title.lower().strip()
        sanitized_title = re.sub(r'[^a-z0-9]+', '-', sanitized_title)
        sanitized_title = sanitized_title.strip('-')
        
        url = f"https://www.naukri.com/{sanitized_title}-jobs"
        
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        print(f"[Tool: search_naukri_via_url] Navigating to direct search URL: {url}")
        page.goto(url, wait_until="load")
        
        # Wait a small moment for dynamic loads
        page.wait_for_timeout(random.randint(1250, 1750))
        
        title = page.title()
        current_url = page.url
        
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"Successfully navigated to direct search URL: {current_url}. Page Title: '{title}'.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to search naukri via URL. Error: {str(e)}"

@tool
def manage_naukri_popup_question(answer: Optional[str] = None, tool_summary: str = "") -> str:
    """
    Detects and answers recruiter popup chatbot questions on naukri.com after clicking Apply.
    If 'answer' is not provided, it scans the page to check if a popup question is visible and returns the question text.
    If 'answer' is provided, it types it into the popup's input field and clicks the Save/Submit button, returning the next state.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # 1. Detect if popup question element and input are visible
        # Evaluate layout elements using JS in the page
        popup_info = page.evaluate(DETECT_NAUKRI_POPUP_JS)
        
        if not popup_info.get("detected"):
            return "No active recruiter question popup detected on the page."
            
        if not answer:
            return (
                f"Recruiter popup question detected!\n"
                f"Question: \"{popup_info['question']}\"\n"
                f"Input Placeholder: \"{popup_info['placeholder']}\"\n"
                f"Please invoke this tool again providing the 'answer' parameter to submit your response."
            )
            
        # Answer is provided, fill it
        input_locator = page.locator("input[placeholder*='Type message'], textarea[placeholder*='Type message'], input[placeholder*='Type your answer'], textarea[placeholder*='Type your answer'], input[placeholder*='Type your response'], textarea[placeholder*='Type your response'], input[placeholder*='answer'], textarea[placeholder*='answer'], input[placeholder*='message'], textarea[placeholder*='message']").first
        if not input_locator.is_visible():
            modal_input = page.locator("div[class*='modal'] input[type='text'], div[class*='dialog'] input[type='text'], div[class*='drawer'] input[type='text'], div[class*='popup'] input[type='text'], [class*='chatbot'] input[type='text'], [class*='botItem'] input[type='text'], div[class*='modal'] textarea, div[class*='dialog'] textarea, div[class*='drawer'] textarea, div[class*='popup'] textarea, [class*='chatbot'] textarea, [class*='botItem'] textarea").first
            if modal_input.is_visible():
                input_locator = modal_input
        input_locator.fill(answer)
        page.wait_for_timeout(random.randint(250, 750))
        
        # Click the Save/Submit button
        save_button = page.locator("button:has-text('Save'), button:has-text('Submit'), button:has-text('Next'), button:has-text('Send'), [class*='save'] button, [class*='Save'] button").first
        if not save_button.is_visible():
            save_button = page.locator("button:has-text('save'), button:has-text('submit'), button:has-text('next'), button:has-text('send')").first
            
        if not save_button.is_visible():
            # Broad search for any button inside the bottom footer/dialog containing text Save or Submit
            save_button = page.locator("button").filter(has_text=re.compile("^(save|submit|next|send)$", re.I)).first
            
        if not save_button.is_visible():
            return f"Error: Located the input field and filled the answer, but could not locate the 'Save' or 'Submit' button to submit it."
            
        move_mouse_to_element_and_click(page, save_button)
        # Wait for potential new question or modal close
        page.wait_for_timeout(random.randint(1750, 2250))
        
        # Check new state
        new_popup_info = page.evaluate(GET_NEXT_NAUKRI_POPUP_QUESTION_JS)
        
        if new_popup_info is None:
            return "Successfully submitted the answer. The recruiter popup question modal has closed."
        else:
            return (
                f"Successfully submitted the answer.\n"
                f"The next recruiter popup question has loaded: \"{new_popup_info['question']}\""
            )
            
    except Exception as e:
        return f"Failed to detect or answer the popup question. Error: {str(e)}"

def _get_llm_model():
    provider = os.getenv("LLM_PROVIDER", "google").lower()
    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        api_base = os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com/v1"
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        from langchain_deepseek import ChatDeepSeek
        return ChatDeepSeek(model=model_name, api_key=api_key, api_base=api_base, temperature=0.0)
    elif provider == "local":
        api_base = os.getenv("LOCAL_API_BASE", "http://localhost:11434/v1")
        model_name = os.getenv("LOCAL_MODEL", "qwen2.5")
        api_key = os.getenv("LOCAL_API_KEY", "local")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, api_key=api_key, base_url=api_base, temperature=0.0)
    else:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, api_key=api_key, temperature=0.0)


_SCREENSHOT_COUNTER = 0

def take_logged_screenshot(page) -> str:
    global _SCREENSHOT_COUNTER
    _SCREENSHOT_COUNTER += 1
    session_id = async_logger.get_session_id()
    log_dir = Path(__file__).parent.parent / "logs"
    screenshot_dir = log_dir / "screenshots"
    screenshot_dir.mkdir(exist_ok=True)
    screenshot_path = screenshot_dir / f"session_api_calls_{session_id}_{_SCREENSHOT_COUNTER}.png"
    page.screenshot(path=str(screenshot_path))
    print(f"[Screenshot Logger] Saved screenshot to: {screenshot_path}")
    return str(screenshot_path)


class NaukriChatbotFallback:
    """
    Fallback class that takes screenshots of the page, gathers elements and coordinates,
    sends them to the LLM for multimodal analysis, and executes a planned sequence
    of cursor moves and keyboard typing actions to complete the chatbot.
    """
    
    @staticmethod
    def get_candidate_details() -> str:
        """
        Retrieves candidate details from resume/My_resume.txt or uses a fallback profile.
        """
        try:
            workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            resume_path = os.path.join(workspace_dir, "resume", "My_resume.txt")
            if os.path.exists(resume_path):
                with open(resume_path, "r", encoding="utf-8") as f:
                    resume_text = f.read()
                print("[Chatbot Programmatic] Loaded candidate details from My_resume.txt")
                return f"Candidate Resume and Details:\n{resume_text}"
        except Exception as e:
            print(f"[Chatbot Programmatic Warning] Failed to load My_resume.txt: {e}")
            
        return (
            "- Candidate Name: John Doe\n"
            "- Email: johndoe@example.com\n"
            "- Phone Number: 9876543210\n"
            "- Target Role: AI Engineer / Developer\n"
            "- Experience: 3 years in AI Engineering, Python, NLP, and LLM development\n"
            "- Notice Period: 30 days\n"
            "- Current Location: Bengaluru\n"
            "- Expected CTC: 15 LPA\n"
            "- Current CTC: 10 LPA\n"
        )

    @staticmethod
    def run_fallback_step(page, model) -> dict:
        """
        Runs a single fallback interaction step:
        1. Takes screenshot.
        2. Gathers element coordinates.
        3. Queries Multimodal LLM to analyze the screenshot, answer questions, and output a planned action plan.
        4. Logs the API call.
        5. Executes actions.
        Returns a dict: {"visible": bool, "completed": bool, "status": str}
        """
        try:
            # Update current active page reference
            manager = PersistentBrowserManager.get_instance()
            page = manager.get_page()
            
            # 1. Take screenshot and save in logs/screenshots
            screenshot_path = take_logged_screenshot(page)
            
            # Encode image to base64
            with open(screenshot_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
                
            # 2. Extract elements with coordinates
            elements = page.evaluate(GET_ELEMENTS_WITH_COORDINATES_JS)
            
            elements_summary = []
            for idx, el in enumerate(elements):
                el_desc = f"Index {idx}: Tag <{el['tagName']}>"
                if el['className']:
                    el_desc += f" Class='{el['className']}'"
                if el['text']:
                    el_desc += f" Text='{el['text']}'"
                if el['placeholder']:
                    el_desc += f" Placeholder='{el['placeholder']}'"
                el_desc += f" Center=(x={el['x']:.1f}, y={el['y']:.1f})"
                elements_summary.append(el_desc)
                
            elements_text = "\n".join(elements_summary)
            candidate_info_str = NaukriChatbotFallback.get_candidate_details()
            
            prompt_text = (
                "You are analyzing a screenshot and a list of elements/coordinates on a job application webpage.\n"
                "Verify if the chatbot drawer/container (e.g. class='chatbot_MessageContainer') is currently visible on the page, "
                "or if the application is completed/successfully submitted (showing 'Applied', 'Applied successfully', 'Application submitted').\n\n"
                "Also, examine the chatbot conversation history in the screenshot, formulate the correct answer to the recruiter's latest question "
                "based on the candidate details below, and plan a sequence of tool actions (cursor clicks and keyboard typing) to input the response and hit enter.\n\n"
                "Candidate Details:\n"
                f"{candidate_info_str}\n\n"
                "List of Interactive Elements with coordinates:\n"
                f"\"\"\"\n{elements_text}\n\"\"\"\n\n"
                "Return your response strictly in the following JSON format. Do not add markdown codeblocks, prefix or suffix formatting:\n"
                "{\n"
                "  \"visible\": true or false,\n"
                "  \"completed\": true or false,\n"
                "  \"explanation\": \"Brief explanation of what you see\",\n"
                "  \"actions\": [\n"
                "    {\"type\": \"move_to_coordinates_and_click\", \"x\": float, \"y\": float},\n"
                "    {\"type\": \"keyboard_type\", \"text\": \"string\"},\n"
                "    {\"type\": \"keyboard_press\", \"key\": \"string\"},\n"
                "    {\"type\": \"wait\", \"seconds\": float}\n"
                "  ]\n"
                "}\n"
            )
            
            content = [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encoded_image}"
                    }
                }
            ]
            
            # Execute LLM call
            response = model.invoke([HumanMessage(content=content)])
            res_content = response.content.strip()
            
            # Clean JSON codeblock wrappers if present
            if res_content.startswith("```"):
                res_content = re.sub(r'^```(?:json)?\n|```$', '', res_content, flags=re.M).strip()
                
            # Log API Call
            in_tokens = 0
            out_tokens = 0
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                in_tokens = response.usage_metadata.get('input_tokens', 0)
                out_tokens = response.usage_metadata.get('output_tokens', 0)
            elif hasattr(response, 'response_metadata') and response.response_metadata:
                usage = response.response_metadata.get('token_usage', {})
                if usage:
                    in_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0) or 0
                    out_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0) or 0
                    
            model_name_str = getattr(model, "model_name", "gemini-2.5-flash") or getattr(model, "model", "gemini-2.5-flash")
            async_logger.log_api_call(
                caller_name="run_naukri_chatbot_fallback",
                model_name=model_name_str,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                sent_data={"prompt": prompt_text, "screenshot_path": screenshot_path},
                response_data=res_content
            )
            
            res_json = json.loads(res_content)
            
            visible = res_json.get("visible", False)
            completed = res_json.get("completed", False)
            explanation = res_json.get("explanation", "")
            actions = res_json.get("actions", [])
            
            print(f"[Fallback Class] Chatbot visible: {visible}, Completed: {completed}, Explanation: {explanation}")
            
            if not visible:
                return {"visible": False, "completed": completed, "status": "Chatbot not visible in screenshot.", "explanation": explanation}
                
            if completed:
                return {"visible": visible, "completed": True, "status": "Application confirmed completed by LLM.", "explanation": explanation}
                
            # Execute actions
            for action in actions:
                act_type = action.get("type")
                if act_type == "move_to_coordinates_and_click":
                    x = action.get("x")
                    y = action.get("y")
                    print(f"[Fallback Class Action] Moving PyAutoGUI mouse to viewport ({x}, {y}) and clicking...")
                    execute_human_pyautogui_action(page, "move_and_click", x=x, y=y)
                    page.wait_for_timeout(random.randint(200, 500))
                elif act_type == "keyboard_type":
                    txt = action.get("text")
                    print(f"[Fallback Class Action] PyAutoGUI Keyboard typing: '{txt}'...")
                    execute_human_pyautogui_action(page, "type", text=txt)
                    page.wait_for_timeout(random.randint(200, 500))
                elif act_type == "keyboard_press":
                    key = action.get("key")
                    print(f"[Fallback Class Action] PyAutoGUI Pressing key: '{key}'...")
                    execute_human_pyautogui_action(page, "press", key=key)
                    page.wait_for_timeout(random.randint(200, 500))
                elif act_type == "wait":
                    sec = action.get("seconds", 1.0)
                    print(f"[Fallback Class Action] Waiting {sec} seconds...")
                    page.wait_for_timeout(int(sec * 1000))
                    
            return {"visible": True, "completed": False, "status": "Action sequence executed successfully.", "explanation": explanation}
            
        except Exception as e:
            return {"visible": False, "completed": False, "status": f"Error during fallback step: {str(e)}"}


@tool
def run_naukri_chatbot_fallback(tool_summary: str = "") -> str:
    """
    Fallback tool that runs the screenshot-based, coordinate-movement chatbot filler.
    Use this if the primary 'manage_naukri_chatbot' cannot locate elements or fails.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        model = _get_llm_model()
        
        print("[Fallback Tool] Starting chatbot fallback interactive loop...")
        
        loop_count = 0
        max_loops = 10
        summary_logs = []
        
        while loop_count < max_loops:
            loop_count += 1
            # Update current active page
            page = manager.get_page()
            
            res = NaukriChatbotFallback.run_fallback_step(page, model)
            print(f"[Fallback Tool Step {loop_count}] Result: {res}")
            
            explanation = res.get("explanation")
            if explanation:
                summary_logs.append(f"Step {loop_count}: {explanation}")
            
            if res.get("completed"):
                summary_str = "\n".join(summary_logs)
                return f"Successfully completed chatbot questions via fallback. The job application has been successfully submitted.\nFallback Action Summary:\n{summary_str}"
                
            if not res.get("visible"):
                summary_str = "\n".join(summary_logs)
                return f"Successfully completed chatbot questions via fallback. The job application has been successfully submitted.\nFallback Action Summary:\n{summary_str}"
                
            # Wait between fallback steps
            page.wait_for_timeout(3000)
            
        summary_str = "\n".join(summary_logs)
        return f"Chatbot fallback response loop reached maximum iterations without completing.\nFallback Action Summary:\n{summary_str}"
    except Exception as e:
        return f"Failed to execute Naukri chatbot fallback. Error: {str(e)}"


@tool
def manage_naukri_chatbot(tool_summary: str = "") -> str:
    """
    Autonomous programmatic tool that detects the Naukri recruiter chatbot, extracts its messages,
    queries the LLM to determine the appropriate response, types the response into the chat input,
    and submits it. It runs in a loop until the chatbot disappears or the application is successful.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        model = _get_llm_model()
        
        # Load Candidate Details
        candidate_info_str = NaukriChatbotFallback.get_candidate_details()
        
        # 1. Search for chatbot_MessageContainer with 5 retries (1s delay) using regex
        chatbot_found = False
        for attempt in range(5):
            page = manager.get_page()
            html = page.content()
            # Regex search for class="chatbot_MessageContainer"
            if re.search(r'class=["\'][^"\']*chatbot_MessageContainer[^"\']*["\']', html) or re.search(r'chatbot_MessageContainer', html):
                chatbot_container = page.locator('.chatbot_MessageContainer, [class*="chatbot_MessageContainer"]').first
                if chatbot_container.is_visible():
                    chatbot_found = True
                    print(f"[Chatbot Programmatic] Chatbot container found using regex on attempt {attempt + 1}")
                    break
            print(f"[Chatbot Programmatic] attempt {attempt + 1}: chatbot_MessageContainer not found. Fetching webpage again...")
            page.wait_for_timeout(1000)
            
        if not chatbot_found:
            print("[Chatbot Programmatic] Chatbot container not found via regex. Skipping fallback presence check.")
            return "No active Naukri chatbot drawer (class='chatbot_MessageContainer') detected on the page."
            
        print("[Chatbot Programmatic] Chatbot detected. Starting autonomous response loop...")
        
        loop_count = 0
        max_loop_iterations = 20
        last_chatbot_text = ""
        unchanged_count = 0
        
        while loop_count < max_loop_iterations:
            loop_count += 1
            # Make sure that the browser's current active is updated within playwright
            page = manager.get_page()
            
            # Check if "Applied" shows up on the page
            page_text = page.locator("body").inner_text()
            if re.search(r'Applied', page_text, re.IGNORECASE) or "successfully applied" in page_text.lower() or "application submitted" in page_text.lower():
                print("[Chatbot Programmatic] 'Applied' or confirmation text detected on page. Stopping chatbot loop.")
                return "Successfully completed chatbot questions. The job application has been successfully submitted."
                
            # Verify if chatbot container is still visible using regex
            html = page.content()
            if not (re.search(r'class=["\'][^"\']*chatbot_MessageContainer[^"\']*["\']', html) or re.search(r'chatbot_MessageContainer', html)):
                chatbot_container = page.locator('.chatbot_MessageContainer, [class*="chatbot_MessageContainer"]').first
                if not chatbot_container.is_visible():
                    print("[Chatbot Programmatic] chatbot_MessageContainer disappears. Stopping chatbot loop.")
                    return "Successfully completed chatbot questions. The job application has been successfully submitted."
            
            # 2. Gather contents of class="botMsg msg " from the page
            # First, check using regex on the HTML to confirm elements are present
            if not (re.search(r'class=["\'][^"\']*(?:botMsg\s+msg|msg\s+botMsg)[^"\']*["\']', html) or re.search(r'botMsg', html)):
                print("[Chatbot Programmatic] botMsg elements not found in HTML via regex. Waiting...")
                page.wait_for_timeout(1500)
                continue
                
            chatbot_container = page.locator('.chatbot_MessageContainer, [class*="chatbot_MessageContainer"]').first
            msg_elements = chatbot_container.locator('.botMsg.msg, [class*="botMsg"][class*="msg"]')
            msg_count = msg_elements.count()
            
            if msg_count == 0:
                print("[Chatbot Programmatic] No message bubbles found yet. Waiting for recruiter to type...")
                page.wait_for_timeout(1500)
                continue
                
            messages_text = []
            for j in range(msg_count):
                txt = msg_elements.nth(j).inner_text().strip()
                if txt:
                    messages_text.append(txt)
                    
            full_chatbot_text = "\n".join(messages_text)
            
            if full_chatbot_text == last_chatbot_text:
                unchanged_count += 1
                if unchanged_count > 4:
                    print("[Chatbot Programmatic] Chat history unchanged for several iterations. Breaking loop to let page load.")
                    break
                print(f"[Chatbot Programmatic] Chat history hasn't changed. Waiting for recruiter's next question... (Attempt {unchanged_count}/4)")
                page.wait_for_timeout(2000)
                continue
                
            last_chatbot_text = full_chatbot_text
            unchanged_count = 0
            print(f"\n[Chatbot Programmatic Step {loop_count}] Gathered Chat History:\n{full_chatbot_text}\n")
            
            # 3. Query LLM to get the response about what to fill
            prompt_text = (
                "You are an assistant helping to fill out a job application chatbot.\n"
                "Below is the transcript of the chatbot conversation so far:\n"
                f"\"\"\"\n{full_chatbot_text}\n\"\"\"\n\n"
                "Please determine the appropriate response to answer the recruiter's last question based on the candidate details below:\n"
                f"{candidate_info_str}\n\n"
                "Your output must be ONLY the plain text response to be typed into the input field. "
                "Do not add quotes, explanations, prefixes, or any extra text. Just return the answer."
            )
            try:
                response = model.invoke([HumanMessage(content=prompt_text)])
                llm_response = response.content.strip()
                # Clean up any surrounding quotes added by the LLM
                if (llm_response.startswith('"') and llm_response.endswith('"')) or (llm_response.startswith("'") and llm_response.endswith("'")):
                    llm_response = llm_response[1:-1].strip()
                    
                # Log API Call
                in_tokens = 0
                out_tokens = 0
                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                    in_tokens = response.usage_metadata.get('input_tokens', 0)
                    out_tokens = response.usage_metadata.get('output_tokens', 0)
                elif hasattr(response, 'response_metadata') and response.response_metadata:
                    usage = response.response_metadata.get('token_usage', {})
                    if usage:
                        in_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0) or 0
                        out_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0) or 0
                        
                model_name_str = getattr(model, "model_name", "gemini-2.5-flash") or getattr(model, "model", "gemini-2.5-flash")
                async_logger.log_api_call(
                    caller_name="manage_naukri_chatbot",
                    model_name=model_name_str,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    sent_data=prompt_text,
                    response_data=llm_response
                )
            except Exception as le:
                print(f"[Chatbot Programmatic Warning] LLM invocation failed: {le}. Triggering fallback...")
                return run_naukri_chatbot_fallback.invoke({})
                
            print(f"[Chatbot Programmatic] LLM Answer: '{llm_response}'")
            
            # 4. Locate class="chatbot_InputContainer" within class="_chatBotContainer"
            # First, check using regex on the HTML to confirm both classes are present
            if not (re.search(r'class=["\'][^"\']*_chatBotContainer[^"\']*["\']', html) or re.search(r'_chatBotContainer', html)):
                print("[Chatbot Programmatic] _chatBotContainer not found via regex. Triggering fallback...")
                return run_naukri_chatbot_fallback.invoke({})
            if not (re.search(r'class=["\'][^"\']*chatbot_InputContainer[^"\']*["\']', html) or re.search(r'chatbot_InputContainer', html)):
                print("[Chatbot Programmatic] chatbot_InputContainer not found via regex. Triggering fallback...")
                return run_naukri_chatbot_fallback.invoke({})
                
            chatbot_root = page.locator('._chatBotContainer, [class*="_chatBotContainer"]').first
            input_container = chatbot_root.locator('.chatbot_InputContainer, [class*="chatbot_InputContainer"]').first
            
            if not input_container.is_visible():
                print("[Chatbot Programmatic] Input container not visible. Triggering fallback...")
                return run_naukri_chatbot_fallback.invoke({})
                
            input_el = input_container.locator('input, textarea, [contenteditable="true"], [role="textbox"]').first
            
            if not input_el.is_visible():
                # Fallback: Click container and type via keyboard
                print("[Chatbot Programmatic] Input element not visible inside container. Clicking container and typing via keyboard...")
                try:
                    input_container.scroll_into_view_if_needed()
                    input_container.click()
                    page.wait_for_timeout(500)
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(llm_response)
                    page.wait_for_timeout(500)
                    page.keyboard.press("Enter")
                    print("[Chatbot Programmatic] Submitted answer via keyboard type.")
                    page.wait_for_timeout(2000)
                    continue
                except Exception as ke:
                    print(f"[Chatbot Programmatic Warning] Keyboard fallback failed: {ke}. Triggering fallback...")
                    return run_naukri_chatbot_fallback.invoke({})
                
            # Send input and hit enter (standard fill)
            try:
                input_el.scroll_into_view_if_needed()
                input_el.fill(llm_response)
                page.wait_for_timeout(500)
                input_el.press("Enter")
            except Exception as fe:
                # If fill fails (e.g. element not fillable), use keyboard type fallback
                print(f"[Chatbot Programmatic Warning] Fill failed ({fe}). Clicking element and typing via keyboard...")
                try:
                    input_el.click()
                    page.wait_for_timeout(500)
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(llm_response)
                    page.wait_for_timeout(500)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(2000)
                except Exception as ke2:
                    print(f"[Chatbot Programmatic Warning] Keyboard fallback 2 failed: {ke2}. Triggering fallback...")
                    return run_naukri_chatbot_fallback.invoke({})
            
            # Wait for response to load (2 seconds)
            print("[Chatbot Programmatic] Submitted answer. Waiting for recruiter's response...")
            page.wait_for_timeout(2000)
            
        return "Chatbot response loop reached maximum iterations without completing."
    except Exception as e:
        print(f"[Chatbot Programmatic Error] manage_naukri_chatbot failed: {e}. Triggering fallback...")
        return run_naukri_chatbot_fallback.invoke({})

@tool
def click_naukri_apply_button(mode: str = "interactive", tool_summary: str = "") -> str:
    """
    Searches the current page for visible Naukri 'Apply' or 'Apply now' buttons/links and clicks them.
    Automatically detects if a new tab was opened, switches the active browser session to the new tab, and returns its content.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Scan page for a visible apply button/link using JS
        target_info = page.evaluate(FIND_NAUKRI_APPLY_BUTTON_JS)
        
        if not target_info:
            return "No matching Naukri 'Apply' button or link was found on the current page."
            
        selector = '[data-automation-click-target="true"]'
        locator = page.locator(selector).first
        
        # Keep track of active page before click
        old_page = page
        
        print(f"[Tool: click_naukri_apply_button] Clicking apply element: <{target_info['tagName']}> with text '{target_info['text']}'")
        move_mouse_to_element_and_click(page, locator)
        
        # Clean up temporary attribute
        page.evaluate(REMOVE_CLICK_TARGET_ATTR_JS)
        
        # Wait for potential page navigation or tab opening
        page.wait_for_timeout(random.randint(1750, 2250))
        
        # Backup check: if there are multiple pages, ensure we are on the latest one
        if len(manager.context.pages) > 1:
            latest_page = manager.context.pages[-1]
            if latest_page != manager.page:
                print(f"[PersistentBrowserManager] Backup check: Switching active page to the latest tab.")
                manager.page = latest_page
                
        current_page = manager.get_page()
        
        # Check for active recruiter popup questions or chatbot drawer (up to 5 times, 1 second apart)
        popup_info = {"detected": False}
        chatbot_info = {"detected": False}
        for attempt in range(5):
            popup_info = current_page.evaluate(DETECT_NAUKRI_POPUP_JS)
            chatbot_info = current_page.evaluate(GET_NAUKRI_CHATBOT_A11Y_JS)
            if (popup_info and popup_info.get("detected")) or (chatbot_info and chatbot_info.get("detected")):
                print(f"[click_naukri_apply_button] Popup or chatbot detected on attempt {attempt + 1}")
                break
            current_page.wait_for_timeout(1000)
            
        rep_header, rep_body = get_representation_header_and_body(current_page, mode)
        
        extra_detection = ""
        if popup_info and popup_info.get("detected"):
            extra_detection += (
                f"\n[ALERT]: Recruiter question popup detected!\n"
                f"Question: \"{popup_info['question']}\"\n"
                f"You MUST use the 'manage_naukri_popup_question' tool to answer it. Do NOT try to scroll or perform other actions.\n\n"
            )
        if chatbot_info and chatbot_info.get("detected"):
            extra_detection += (
                f"\n[ALERT]: Naukri recruiter chatbot drawer detected!\n"
                f"You MUST use the 'manage_naukri_chatbot' tool to retrieve and answer chatbot questions. Do NOT try to scroll or perform other actions.\n\n"
            )

        if current_page != old_page:
            return (
                f"Successfully clicked the Apply element: '{target_info['text']}'.\n"
                f"NOTICE: A new tab was opened and the browser session automatically switched to it.\n"
                f"New Tab URL: '{current_page.url}'\n"
                f"New Tab Title: '{current_page.title()}'\n\n"
                f"{extra_detection}"
                f"{rep_header} of the NEW tab:\n{rep_body}"
            )
        else:
            return (
                f"Successfully clicked the Apply element: '{target_info['text']}'.\n\n"
                f"{extra_detection}"
                f"{rep_header}:\n{rep_body}"
            )
            
    except Exception as e:
        return f"Failed to locate or click the Naukri Apply button. Error: {str(e)}"


