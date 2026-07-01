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
    INDEED_JOB_FETCH_JS,
    INDEED_HEADER_INFO_JS,
    INDEED_DESC_TEXT_JS,
    INDEED_APPLY_BUTTONS_JS,
    INDEED_RIGHT_PANE_TEXT_JS,
    FIND_INDEED_APPLY_BUTTON_JS,
    REMOVE_CLICK_TARGET_ATTR_JS
)


@tool
def search_indeed_via_url(job_title: str) -> str:
    """
    Searches for jobs on indeed.com (India domain in.indeed.com) by directly formatting 
    the search URL query (replacing spaces with '+' and capitalizing words).
    Returns confirmation of navigation and the updated accessibility tree of the page.
    """
    mode = "interactive"
    try:
        # Standardize job title: capitalize each word and join with +
        words = job_title.strip().split()
        capitalized_words = [word.capitalize() for word in words]
        query = "+".join(capitalized_words)
        
        url = f"https://in.indeed.com/jobs?q={query}"
        
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        print(f"[Tool: search_indeed_via_url] Navigating to Indeed search URL: {url}")
        page.goto(url, wait_until="load")
        
        # Wait a small moment for dynamic loads
        page.wait_for_timeout(random.randint(1750, 2250))
        
        title = page.title()
        current_url = page.url
        
        rep_header, rep_body = get_representation_header_and_body(page, mode)
        return (
            f"Successfully navigated to Indeed search URL: {current_url}. Page Title: '{title}'.\n\n"
            f"{rep_header}:\n{rep_body}"
        )
    except Exception as e:
        return f"Failed to search Indeed via URL. Error: {str(e)}"

@tool
def indeed_job_fetch() -> str:
    """
    Retrieves job details from the current page by locating and cleaning elements for Indeed job listings.
    Only use this on indeed.com search result pages.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        url = page.url
        title = page.title()
        
        # Evaluate Javascript in page to extract clean job card listings
        jobs_json = page.evaluate(INDEED_JOB_FETCH_JS)
        
        if not jobs_json:
            return "No job cards found on the current page."
            
        formatted_jobs = []
        for job in jobs_json:
            formatted_jobs.append(
                f"Job Listing {job['index']}:\n"
                f"Title: {job['title']}\n"
                f"Company: {job['company']}\n"
                f"Location: {job['location']}\n"
                f"Snippet: {job['summary']}"
            )
            
        return (
            f"Indeed Job Page URL: {url}\n"
            f"Page Title: {title}\n\n"
            f"Job Details from Indeed cards:\n" + "\n\n".join(formatted_jobs)
        )
    except Exception as e:
        return f"Failed to fetch Indeed jobs. Error: {str(e)}"

@tool
def fetch_indeed_job_details() -> str:
    """
    Retrieves the detailed job description and key details of the currently selected/open job on indeed.com.
    Use this after selecting a job card to read the full description and check the application options before applying.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # 1. Extract Job Info Header (Title, Company, etc.)
        header_info = page.evaluate(INDEED_HEADER_INFO_JS)
        
        # 2. Extract Description Text
        desc_text = page.evaluate(INDEED_DESC_TEXT_JS)
        
        # 3. Check for Apply button presence and type
        apply_buttons = page.evaluate(INDEED_APPLY_BUTTONS_JS)
        
        if not desc_text and header_info["title"] == "N/A":
            # If nothing specific was found, fall back to general text extraction of the viewport/right-pane
            right_pane_text = page.evaluate(INDEED_RIGHT_PANE_TEXT_JS)
            if right_pane_text:
                desc_text = right_pane_text
            else:
                desc_text = "No detailed description element found. Please make sure a job listing is selected and open on the right."
        
        cleaned_desc = clean_page_text(desc_text)
        truncated_desc = cleaned_desc[:4000] + ("..." if len(cleaned_desc) > 4000 else "")
        
        apply_buttons_str = "\n".join([f"- Button Text: '{b['text']}' (Tag: {b['tag']}, ID: {b['id']})" for b in apply_buttons]) if apply_buttons else "None found"
        
        return (
            f"=== Indeed Job Details ===\n"
            f"Title: {header_info['title']}\n"
            f"Company: {header_info['company']}\n"
            f"Location: {header_info['location']}\n"
            f"URL: {page.url}\n\n"
            f"Detected Apply Option(s):\n{apply_buttons_str}\n\n"
            f"Job Description (truncated):\n{truncated_desc}"
        )
    except Exception as e:
        return f"Failed to fetch Indeed job details. Error: {str(e)}"

@tool
def click_indeed_apply_button(mode: str = "interactive") -> str:
    """
    Searches the current page for visible Indeed 'Apply', 'Apply with Indeed', 'Apply now', or similar buttons/links and clicks them.
    Automatically detects if a new tab was opened, switches the active browser session to the new tab, and returns its content.
    Returns confirmation and the updated pruned accessibility tree if it has changed, otherwise False.
    """
    try:
        manager = PersistentBrowserManager.get_instance()
        page = manager.get_page()
        
        # Scan page for a visible apply button/link using JS
        target_info = page.evaluate(FIND_INDEED_APPLY_BUTTON_JS)
        
        if not target_info:
            return "No matching Indeed 'Apply' button or link was found on the current page."
            
        selector = '[data-automation-click-target="true"]'
        locator = page.locator(selector).first
        locator.scroll_into_view_if_needed()
        
        # Keep track of active page before click
        old_page = page
        
        print(f"[Tool: click_indeed_apply_button] Clicking apply element: <{target_info['tagName']}> with text '{target_info['text']}'")
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
        return f"Failed to locate or click the Indeed Apply button. Error: {str(e)}"


