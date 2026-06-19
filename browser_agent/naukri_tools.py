import os
import re
import json
import time
import random
from typing import Optional, Dict, List, Any, Union
from langchain_core.tools import tool
import async_logger
from browser_tools import (
    PersistentBrowserManager,
    get_representation_header_and_body,
    clean_page_text,
    move_mouse_to_element_and_click
)
from js_templates import (
    DETECT_NAUKRI_POPUP_JS,
    GET_NEXT_NAUKRI_POPUP_QUESTION_JS,
    GET_NAUKRI_CHATBOT_A11Y_JS,
    FIND_NAUKRI_APPLY_BUTTON_JS,
    REMOVE_CLICK_TARGET_ATTR_JS
)

@tool
def naukri_job_fetch() -> str:
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
def search_naukri_via_url(job_title: str) -> str:
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
def manage_naukri_popup_question(answer: Optional[str] = None) -> str:
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
        input_locator = page.locator("input[placeholder*='Type message'], textarea[placeholder*='Type message'], input[placeholder*='Type your answer'], textarea[placeholder*='Type your answer']").first
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

@tool
def manage_naukri_chatbot() -> str:
    """
    Checks for the presence of the Naukri recruiter/application chatbot drawer.
    If the drawer (class="chatbot_MessageContainer") is found, it extracts
    an accessibility-tree-style structured representation of the messages and
    interactive options/fields under class="botItem chatbot_ListItem".
    This allows the LLM to inspect questions, select options, and fill out chatbot inputs.
    Returns a formatted text representation of the chatbot state, or a message indicating no chatbot was found.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # 1. Evaluate the custom JS code to check for the chatbot drawer and parse items
        chatbot_info = page.evaluate(GET_NAUKRI_CHATBOT_A11Y_JS)
        
        if not chatbot_info or not chatbot_info.get("detected"):
            return "No active Naukri chatbot drawer (class='chatbot_MessageContainer') detected."
            
        items = chatbot_info.get("items", [])
        if not items:
            return "Naukri chatbot drawer detected, but no message items (class='botItem chatbot_ListItem') were found inside it."
            
        # 2. Save the full JSON representation in outputs folder
        script_dir = os.path.dirname(os.path.abspath(__file__))
        outputs_dir = os.path.join(script_dir, "outputs")
        os.makedirs(outputs_dir, exist_ok=True)
        chatbot_json_path = os.path.join(outputs_dir, "chatbot_tree.json")
        with open(chatbot_json_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
            
        # 3. Format the chatbot tree into a readable text representation for the LLM
        lines = []
        lines.append("Naukri Chatbot Drawer Detected!")
        lines.append(f"Parsed {len(items)} message bubbles (class='botItem chatbot_ListItem'):\n")
        
        for item in items:
            lines.append(f"--- Chatbot Item {item['itemIndex']} ---")
            lines.append(f"Message/Question: \"{item['questionText']}\"")
            
            elements = item.get("elements", [])
            if elements:
                lines.append("Interactive Elements:")
                for elem in elements:
                    elem_type = elem.get("type") or elem.get("tag")
                    elem_desc = f"  - [{elem_type}]"
                    if elem.get("text"):
                        elem_desc += f" \"{elem['text']}\""
                    if elem.get("placeholder"):
                        elem_desc += f" (Placeholder: \"{elem['placeholder']}\")"
                    if elem.get("value"):
                        elem_desc += f" (Value: \"{elem['value']}\")"
                    if elem.get("checked"):
                        elem_desc += " [CHECKED]"
                        
                    elem_desc += f" -> Selector: \"{elem['selector']}\""
                    lines.append(elem_desc)
                    
                    # Log select options
                    options = elem.get("options", [])
                    if options:
                        opt_strs = [f"\"{o['text']}\" (value: \"{o['value']}\")" for o in options]
                        lines.append(f"    Options: [{', '.join(opt_strs)}]")
            else:
                lines.append("No interactive elements in this bubble.")
            lines.append("") # blank line between items
            
        return "\n".join(lines)
        
    except Exception as e:
        return f"Failed to retrieve Naukri chatbot accessibility details. Error: {str(e)}"

@tool
def click_naukri_apply_button(mode: str = "interactive") -> str:
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
        locator.scroll_into_view_if_needed()
        
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
        rep_header, rep_body = get_representation_header_and_body(current_page, mode)
        
        if current_page != old_page:
            return (
                f"Successfully clicked the Apply element: '{target_info['text']}'.\n"
                f"NOTICE: A new tab was opened and the browser session automatically switched to it.\n"
                f"New Tab URL: '{current_page.url}'\n"
                f"New Tab Title: '{current_page.title()}'\n\n"
                f"{rep_header} of the NEW tab:\n{rep_body}"
            )
        else:
            return (
                f"Successfully clicked the Apply element: '{target_info['text']}'.\n\n"
                f"{rep_header}:\n{rep_body}"
            )
            
    except Exception as e:
        return f"Failed to locate or click the Naukri Apply button. Error: {str(e)}"


