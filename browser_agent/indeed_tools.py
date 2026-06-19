import os
import re
import json
import time
from typing import Optional, Dict, List, Any, Union
from langchain_core.tools import tool
from browser_tools import (
    PersistentBrowserManager,
    get_representation_header_and_body,
    clean_page_text
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
        page.wait_for_timeout(2000)
        
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
        jobs_json = page.evaluate(r'''
            () => {
                const cards = Array.from(document.querySelectorAll('.job_seen_beacon, td.resultContent, .cardOutline'));
                return cards.map((card, index) => {
                    // Extract Title
                    const titleEl = card.querySelector('h2.jobTitle, a.jcs-JobTitle, a[id^="job_"]');
                    const titleText = titleEl ? titleEl.innerText.trim() : "N/A";
                    
                    // Extract Company
                    const companyEl = card.querySelector('[data-testid="company-name"], .companyName, .company_location [class*="company"]');
                    const companyText = companyEl ? companyEl.innerText.trim() : "N/A";
                    
                    // Extract Location
                    const locationEl = card.querySelector('[data-testid="text-location"], .companyLocation, .location');
                    const locationText = locationEl ? locationEl.innerText.trim() : "N/A";
                    
                    // Extract Snippet
                    const snippetEl = card.querySelector('.job-snippet, [class*="snippet"], .summary');
                    const snippetText = snippetEl ? snippetEl.innerText.trim() : "N/A";
                    
                    return {
                        index: index + 1,
                        title: titleText,
                        company: companyText,
                        location: locationText,
                        summary: snippetText
                    };
                });
            }
        ''')
        
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
        header_info = page.evaluate(r'''
            () => {
                const header = document.querySelector('.jobsearch-JobInfoHeader-title-container, .jobsearch-JobInfoHeader-title, h1[class*="jobsearch-JobInfoHeader-title"]');
                const title = header ? header.innerText.trim() : "N/A";
                
                const companyEl = document.querySelector('[data-testid="inlineHeader-companyName"] a, [data-testid="inlineHeader-companyName"]');
                const company = companyEl ? companyEl.innerText.trim() : "N/A";
                
                const locationEl = document.querySelector('[data-testid="inlineHeader-companyLocation"], .jobsearch-JobInfoHeader-subtitle [class*="location"]');
                const location = locationEl ? locationEl.innerText.trim() : "N/A";
                
                return { title, company, location };
            }
        ''')
        
        # 2. Extract Description Text
        desc_text = page.evaluate(r'''
            () => {
                const descEl = document.querySelector('#jobDescriptionText, .jobsearch-jobDescriptionText');
                if (descEl) {
                    return descEl.innerText.trim();
                }
                
                // Fallback to searching containers that look like descriptions
                const containers = Array.from(document.querySelectorAll('div[class*="description"], div[class*="Description"]'));
                for (const container of containers) {
                    const rect = container.getBoundingClientRect();
                    if (rect.width > 100 && rect.height > 100 && window.getComputedStyle(container).visibility !== 'hidden') {
                        return container.innerText.trim();
                    }
                }
                return "";
            }
        ''')
        
        # 3. Check for Apply button presence and type
        apply_buttons = page.evaluate(r'''
            () => {
                const buttons = Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"]'));
                const applyInfo = [];
                
                for (const btn of buttons) {
                    const text = (btn.innerText || btn.value || '').trim();
                    const isVisible = btn.getBoundingClientRect().width > 0 && btn.getBoundingClientRect().height > 0 && window.getComputedStyle(btn).visibility !== 'hidden';
                    
                    if (isVisible && (
                        text.toLowerCase().includes('apply now') || 
                        text.toLowerCase().includes('apply with indeed') || 
                        text.toLowerCase().includes('apply on company site') ||
                        text.toLowerCase().includes('apply on company\'s website') ||
                        btn.id.includes('indeedApplyButton') ||
                        btn.className.includes('IndeedApplyButton')
                    )) {
                        applyInfo.push({
                            text: text,
                            tag: btn.tagName.toLowerCase(),
                            id: btn.id || "N/A"
                        });
                    }
                }
                return applyInfo;
            }
        ''')
        
        if not desc_text and header_info["title"] == "N/A":
            # If nothing specific was found, fall back to general text extraction of the viewport/right-pane
            right_pane_text = page.evaluate(r'''
                () => {
                    const pane = document.querySelector('#jobsearch-ViewJobLayout-jobDetails, .jobsearch-ViewJobLayout-jobDetails, #vjs-container');
                    return pane ? pane.innerText.trim() : "";
                }
            ''')
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

