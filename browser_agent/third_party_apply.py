import os
import sys
import time
import random
import json
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
    update_agent_memory,
    adjust_spinner_value,
    os_level_mouse_keyboard_action,
    close_browser_on_interrupt
)
from naukri_tools import (
    naukri_job_fetch,
    search_naukri_via_url
)
from js_templates import GET_FORM_FIELDS_JS

# 1. Force Browser Persistent Mode
os.environ["BROWSER_INCOGNITO"] = "false"

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

def is_workday_portal(url: str) -> bool:
    """Checks if the target URL points to a Workday job portal."""
    is_workday = "myworkdayjobs.com" in url.lower() or "workday" in url.lower()
    print(f"[Workday Detector] URL check completed. Is Workday: {is_workday} (URL: {url})")
    return is_workday

def search_input_fields_via_regex(html_content: str) -> list:
    """Uses regex to find all input, select, and textarea fields in the HTML content."""
    import re
    input_pattern = re.compile(r'<(?:input|select|textarea)\b[^>]*>', re.IGNORECASE)
    input_elements = [m.group(0) for m in input_pattern.finditer(html_content)]
    print(f"[Regex Search] Found {len(input_elements)} input/form fields on the page.")
    return input_elements

def search_apply_buttons_via_regex(html_content: str) -> list:
    """Uses regex to find potential Apply, Submit, or similar buttons/links in the HTML."""
    import re
    # Regex search for button-like elements containing "Apply", "Apply Now" or similar text
    button_pattern = re.compile(r'<(?:button|a)\b[^>]*>([\s\S]*?)</(?:button|a)>', re.IGNORECASE)
    button_elements = []
    
    # 1. Parse button/anchor tags and check content/attributes
    for m in button_pattern.finditer(html_content):
        full_tag = m.group(0)
        inner_text = m.group(1)
        if re.search(r'apply|submit|register|continue|sign[- ]?up|easy[- ]?apply', inner_text + full_tag, re.IGNORECASE):
            button_elements.append(full_tag)
            
    # 2. Parse input fields with button/submit types or values
    input_btn_pattern = re.compile(
        r'<input\b[^>]*(?:type=["\'](?:submit|button)["\']|value=["\'][^"\']*(?:apply|submit|register|continue)[^"\']*["\'])[^>]*>', 
        re.IGNORECASE
    )
    for m in input_btn_pattern.finditer(html_content):
        button_elements.append(m.group(0))
        
    print(f"[Regex Search] Found {len(button_elements)} potential 'Apply' or similar buttons.")
    return button_elements

def take_page_screenshot(page, prefix: str = "third_party_apply") -> str:
    """Takes a screenshot of the current page and returns the file path."""
    import time
    log_dir = Path(__file__).parent.parent / "logs"
    screenshot_dir = log_dir / "screenshots"
    screenshot_dir.mkdir(exist_ok=True, parents=True)
    screenshot_path = screenshot_dir / f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    try:
        page.screenshot(path=str(screenshot_path))
        print(f"[Screenshot Logger] Saved page screenshot to: {screenshot_path}")
        return str(screenshot_path)
    except Exception as e:
        print(f"[Screenshot Logger Warning] Failed to take page screenshot: {e}")
        return ""

def save_for_manual_apply(url: str, reason: str):
    """
    Saves the target URL to logs/manual_applications.txt for the user to handle manually.
    """
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True, parents=True)
    manual_file = log_dir / "manual_applications.txt"
    try:
        with open(manual_file, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] URL: {url} | Reason: {reason}\n")
        print(f"[Manual Handoff] Job application URL saved for manual processing at: {manual_file}")
    except Exception as e:
        print(f"[Manual Handoff Warning] Failed to save manual application URL: {e}")

def detect_captcha(page) -> bool:
    """
    Checks if the page contains a captcha challenge (reCAPTCHA, hCaptcha, Cloudflare turnstile, etc.).
    If detected, logs the URL to logs/manual_applications.txt, closes the tab, and returns True.
    """
    try:
        current_url = page.url
        # 1. Check page text for common captcha patterns
        body_text = page.locator("body").inner_text().lower()
        captcha_keywords = [
            "i am not a robot",
            "verify you are human",
            "verify that you are human",
            "prove you are not a robot",
            "complete the captcha",
            "security check to access",
            "confirm you're a human"
        ]
        for kw in captcha_keywords:
            if kw in body_text:
                print(f"[Captcha Detector] Captcha keyword detected: '{kw}'")
                save_for_manual_apply(current_url, f"Captcha detected (keyword: '{kw}')")
                page.close()
                return True

        # 2. Check iframes for captcha sources
        iframes = page.locator("iframe").all()
        for iframe in iframes:
            try:
                src = iframe.get_attribute("src") or ""
                src_lower = src.lower()
                if any(x in src_lower for x in ["recaptcha", "hcaptcha", "turnstile", "captcha"]):
                    print(f"[Captcha Detector] Captcha iframe detected (src: '{src}')")
                    save_for_manual_apply(current_url, "Captcha iframe detected")
                    page.close()
                    return True
            except Exception:
                pass

        # 3. Check element selectors for captcha classes/IDs
        captcha_selectors = [
            "div.g-recaptcha",
            "#recaptcha",
            "#hcaptcha",
            ".cf-turnstile",
            ".h-captcha",
            "[id*='captcha']",
            "[class*='captcha']"
        ]
        for sel in captcha_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible():
                    print(f"[Captcha Detector] Captcha element detected (selector: '{sel}')")
                    save_for_manual_apply(current_url, f"Captcha element detected: {sel}")
                    page.close()
                    return True
            except Exception:
                pass
                
    except Exception as e:
        print(f"[Captcha Detector Warning] Error checking captcha: {e}")
        
    return False

def load_resume_info_dict(resume_txt_path: str = None) -> dict:
    """
    Parses resume details from My_resume.txt or returns defaults if unable.
    """
    if resume_txt_path is None:
        resume_txt_path = Path(__file__).parent.parent / "resume" / "My_resume.txt"
    
    info = {
        "name": "Aaryan Bansal",
        "first_name": "Aaryan",
        "last_name": "Bansal",
        "email": "aaryanbansal976@gmail.com",
        "phone": "+91 8920567198",
        "linkedin": "https://www.linkedin.com/in/aaryan-bansal/",
        "github": "https://github.com/netosis",
        "current_company": "Telaverge Communications Pvt. Ltd.",
        "current_role": "Research and Development Engineer",
        "experience": "2 years",
    }
    
    if not os.path.exists(resume_txt_path):
        print(f"[Resume Loader] {resume_txt_path} not found. Using default profile.")
        return info
        
    try:
        with open(resume_txt_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        import re
        # Parse Email
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', content)
        if email_match:
            info["email"] = email_match.group(0)
            
        # Parse Phone
        phone_match = re.search(r'\+?\d{2,3}[\s-]?\d{10}', content)
        if phone_match:
            info["phone"] = phone_match.group(0)
        else:
            phone_match = re.search(r'(\+?\d[\d\s-]{8,12}\d)', content)
            if phone_match:
                info["phone"] = phone_match.group(0).strip()
                
        # Parse LinkedIn
        li_match = re.search(r'https?://(?:www\.)?linkedin\.com/in/[\w-]+', content)
        if li_match:
            info["linkedin"] = li_match.group(0)
            
        # Parse GitHub
        gh_match = re.search(r'https?://(?:www\.)?github\.com/[\w-]+', content)
        if gh_match:
            info["github"] = gh_match.group(0)
            
        # Parse Name (usually the first text line under PAGE 1)
        page1_idx = content.find("=== PAGE 1 ===")
        if page1_idx != -1:
            lines = content[page1_idx:].splitlines()
            for line in lines:
                line = line.strip()
                if line and not line.startswith("===") and not line.startswith("Rotation:") and not line.startswith("Size:") and not line.startswith("Links found:") and not line.startswith("Link "):
                    # The first non-meta line should be the name
                    if re.match(r'^[a-zA-Z\s]+$', line):
                        info["name"] = line
                        parts = line.split()
                        if parts:
                            info["first_name"] = parts[0]
                            info["last_name"] = parts[-1] if len(parts) > 1 else ""
                        break
        print(f"[Resume Loader] Successfully parsed profile from {resume_txt_path}: {info}")
    except Exception as e:
        print(f"[Resume Loader Warning] Failed to parse resume file: {e}. Using default profile.")
        
    return info

def map_fields_with_resume_data(form_fields: list, resume_info: dict, resume_path: str = None) -> tuple[dict, list]:
    """
    Maps form fields to resume info using regex on labels/placeholders.
    Returns:
        mapped_values: dict of selector -> value
        unmapped_fields: list of field dicts that couldn't be mapped
    """
    mapped_values = {}
    unmapped_fields = []
    
    for field in form_fields:
        label = (field.get("labelText") or "").lower()
        placeholder = (field.get("placeholder") or "").lower()
        selector = field.get("selector")
        field_type = (field.get("type") or "").lower()
        
        # We search both label and placeholder for matches
        search_text = f"{label} {placeholder}"
        
        matched = False
        
        # Check for resume upload
        if field_type == "file" or "resume" in search_text or "cv" in search_text or "upload" in search_text:
            if resume_path:
                mapped_values[selector] = resume_path
                matched = True
            elif "resume" in resume_info:
                mapped_values[selector] = resume_info["resume"]
                matched = True
        
        # Check for Email
        elif "email" in search_text:
            if "email" in resume_info:
                mapped_values[selector] = resume_info["email"]
                matched = True
                
        # Check for Phone/Mobile
        elif "phone" in search_text or "mobile" in search_text or "contact" in search_text:
            if "phone" in resume_info:
                mapped_values[selector] = resume_info["phone"]
                matched = True
                
        # Check for Full Name
        elif "full name" in search_text or "name" in search_text:
            # check if separate first/last name fields
            if "first name" in search_text:
                if "first_name" in resume_info:
                    mapped_values[selector] = resume_info["first_name"]
                    matched = True
            elif "last name" in search_text:
                if "last_name" in resume_info:
                    mapped_values[selector] = resume_info["last_name"]
                    matched = True
            else:
                if "name" in resume_info:
                    mapped_values[selector] = resume_info["name"]
                    matched = True
                    
        # Check for First Name specifically if 'name' matched above didn't catch it
        elif "first name" in search_text or "firstname" in search_text:
            if "first_name" in resume_info:
                mapped_values[selector] = resume_info["first_name"]
                matched = True
                
        # Check for Last Name specifically
        elif "last name" in search_text or "lastname" in search_text:
            if "last_name" in resume_info:
                mapped_values[selector] = resume_info["last_name"]
                matched = True

        # Check for current company
        elif "company" in search_text or "employer" in search_text:
            if "current_company" in resume_info:
                mapped_values[selector] = resume_info["current_company"]
                matched = True

        # Check for current role/title
        elif "role" in search_text or "title" in search_text or "designation" in search_text:
            if "current_role" in resume_info:
                mapped_values[selector] = resume_info["current_role"]
                matched = True
                
        # Check for experience
        elif "experience" in search_text or "years" in search_text:
            if "experience" in resume_info:
                mapped_values[selector] = resume_info["experience"]
                matched = True

        if not matched:
            unmapped_fields.append(field)
            
    return mapped_values, unmapped_fields

def fill_mapped_fields_locally(page, mapped_values: dict):
    """
    Fills form fields locally on the page using Playwright locators without LLM interaction.
    """
    for selector, value in mapped_values.items():
        try:
            print(f"[Local Form Filler] Filling field '{selector}' with value: '{value}'")
            locator = page.locator(selector).first
            locator.scroll_into_view_if_needed()
            
            # Determine how to fill based on element properties
            element_type = locator.evaluate("el => el.type || el.tagName.toLowerCase()")
            if element_type == "file":
                # Ensure the path is absolute and upload
                abs_path = os.path.abspath(value)
                locator.set_input_files(abs_path)
                print(f"[Local Form Filler] Uploaded file: {abs_path}")
            elif element_type in ["checkbox", "radio"]:
                if value in [True, "true", "True", 1, "yes", "checked"]:
                    locator.check()
                else:
                    locator.uncheck()
                print(f"[Local Form Filler] Checked: {value}")
            elif element_type == "select" or locator.evaluate("el => el.tagName.toLowerCase()") == "select":
                # For select tags, select by option value or text label
                # Let's check available options first to avoid timeout
                options = locator.evaluate("el => Array.from(el.options).map(o => ({value: o.value, text: o.text}))")
                matched_option = None
                for opt in options:
                    if opt["value"].lower() == value.lower() or opt["text"].lower() == value.lower():
                        matched_option = opt["value"]
                        break
                
                # Also try partial matching
                if not matched_option:
                    for opt in options:
                        if value.lower() in opt["value"].lower() or value.lower() in opt["text"].lower() or opt["value"].lower() in value.lower() or opt["text"].lower() in value.lower():
                            matched_option = opt["value"]
                            break
                            
                if matched_option:
                    locator.select_option(matched_option)
                    print(f"[Local Form Filler] Selected option value: '{matched_option}' for value: '{value}'")
                else:
                    print(f"[Local Form Filler Warning] No matching option found in select dropdown for '{value}'. Skipping selector '{selector}'.")
            else:
                # Text inputs, textareas, etc.
                # First focus and clear, then type
                locator.click()
                # Clear content
                locator.evaluate("el => el.value = ''")
                locator.fill(value)
                # Wait 500ms after typing
                page.wait_for_timeout(500)
        except Exception as e:
            print(f"[Local Form Filler Warning] Error filling field '{selector}': {e}")

def vision_find_apply_button_text(page, model) -> str:
    """
    Captures a screenshot of the current page, sends it to the multimodal LLM,
    and returns the text/label of the Apply button to click.
    """
    import base64
    from langchain_core.messages import HumanMessage
    
    screenshot_path = take_page_screenshot(page, prefix="vision_find_apply")
    if not screenshot_path or not os.path.exists(screenshot_path):
        return ""
        
    try:
        with open(screenshot_path, "rb") as f:
            base64_data = base64.b64encode(f.read()).decode("utf-8")
            
        prompt = (
            "Analyze the screenshot of the job page. Identify the text label of the main button "
            "used to apply or start the application (e.g., 'Apply', 'Apply Now', 'Register', 'Easy Apply'). "
            "Return ONLY the exact text on the button, with no other text, punctuation, or explanations."
        )
        
        messages = [
            HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_data}"}
                    }
                ]
            )
        ]
        
        print("[Vision Fallback] Sending page screenshot to model to identify apply button text...")
        response = invoke_model_with_retry(model, messages)
        button_text = response.content.strip()
        print(f"[Vision Fallback] Model identified button text: '{button_text}'")
        return button_text
    except Exception as e:
        print(f"[Vision Fallback Warning] Failed vision parsing: {e}")
        return ""

def run_apply_agent(target_url: str, resume_path: str):
    """Runs the LangChain Agent loop using the browser tools to apply for a job."""
    # Check if the target URL is a Workday URL
    if is_workday_portal(target_url):
        print(f"\n[Handoff]: Handing off control to Workday Agent...")
        from workday_agent import run_workday_agent
        run_workday_agent(resume_path=resume_path, target_url=target_url)
        return

    # First initialize LLM model (since we might need it for vision fallback)
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

    # Inspect the page
    print("\n[Inspection]: Starting non-Workday page analysis...")
    manager = PersistentBrowserManager.get_instance()
    page = manager.get_page()
    page.goto(target_url, wait_until="load")
    page.wait_for_timeout(3000)  # Wait for page to settle

    # Capture initial screenshot
    take_page_screenshot(page, prefix="third_party_apply_initial")

    # Captcha check 1
    if detect_captcha(page):
        return

    html_content = page.content()

    # Call search functions
    import re
    input_elements = search_input_fields_via_regex(html_content)
    button_elements = search_apply_buttons_via_regex(html_content)

    visible_fields = page.evaluate(GET_FORM_FIELDS_JS) or []
    print(f"[Inspection] Visible form fields count: {len(visible_fields)}")

    # If only an Apply button is found (no input fields)
    button_clicked_automatically = False
    if len(visible_fields) <= 2:
        print("[Inspection] Very few visible input fields found. Attempting to locate 'Apply' button...")
        
        # Determine click target
        target_selector = None
        if len(button_elements) == 0:
            print("[Inspection] No apply buttons found via regex. Triggering vision fallback...")
            btn_text = vision_find_apply_button_text(page, model)
            if btn_text:
                # Search DOM for an interactive element containing this text
                locators = [
                    page.locator(f"button:has-text('{btn_text}')"),
                    page.locator(f"a:has-text('{btn_text}')"),
                    page.locator(f"[role='button']:has-text('{btn_text}')"),
                    page.locator(f"text='{btn_text}'")
                ]
                for loc in locators:
                    try:
                        if loc.first.is_visible():
                            target_selector = loc.first
                            print(f"[Vision Fallback] Found matching element for text '{btn_text}'")
                            break
                    except Exception:
                        pass
        else:
            # We have regex button elements, try to click the first one or click_apply_button tool logic
            print("[Inspection] Found potential apply buttons. Clicking the main Apply button...")
            try:
                # Call underlying click_apply_button tool logic directly
                click_res = click_apply_button.invoke({})
                print(f"[Inspection] Click Apply Result: {click_res[:200]}")
                page.wait_for_timeout(3000)
                button_clicked_automatically = True
            except Exception as e:
                print(f"[Inspection Warning] Direct click tool execution failed: {e}")

        # If vision search gave us a locator, click it
        if not button_clicked_automatically and target_selector:
            try:
                print(f"[Vision Fallback] Clicking vision-identified button...")
                target_selector.scroll_into_view_if_needed()
                target_selector.click()
                page.wait_for_timeout(3000)
                button_clicked_automatically = True
            except Exception as e:
                print(f"[Vision Fallback Warning] Failed to click vision-identified button: {e}")

        # If we failed to find/click any button, save for manual review and exit
        if not button_clicked_automatically and len(button_elements) == 0:
            save_for_manual_apply(target_url, "Could not locate or click any 'Apply Now' button on the page.")
            try:
                page.close()
            except Exception:
                pass
            return

    # Check captcha again after click/load
    if detect_captcha(page):
        return

    # ----------------------------------------------------
    # Iterative local form filling & multi-step processing
    # ----------------------------------------------------
    resume_info = load_resume_info_dict()
    local_fill_success = True
    local_step = 0
    max_local_steps = 5
    handoff_reason = ""
    
    print("\n--- Starting Local Form Filling Loop ---")
    
    while local_step < max_local_steps:
        local_step += 1
        print(f"[Local Form Filler] Step {local_step} of {max_local_steps}")
        
        # Check captcha before each local scan
        if detect_captcha(page):
            return
            
        form_fields = page.evaluate(GET_FORM_FIELDS_JS)
        if not form_fields:
            print("[Local Form Filler] No form fields detected. Checking if successfully applied...")
            page_text = page.locator("body").inner_text().lower()
            if any(x in page_text for x in ["applied successfully", "application submitted", "successfully applied"]):
                print("[Local Form Filler Success] Job application submitted successfully!")
                return
            else:
                handoff_reason = "No form fields found, but no submission confirmation detected either."
                local_fill_success = False
                break
                
        print(f"[Local Form Filler] Found {len(form_fields)} fields on current page.")
        
        # Map fields
        mapped_values, unmapped_fields = map_fields_with_resume_data(form_fields, resume_info, resume_path)
        print(f"[Local Form Filler] Mapped fields: {len(mapped_values)}, Unmapped fields: {len(unmapped_fields)}")
        
        # If there are fields we couldn't map, we must hand off to the LLM agent
        if unmapped_fields:
            unmapped_labels = [f"{f.get('labelText')} ({f.get('type')})" for f in unmapped_fields]
            handoff_reason = f"Unmapped fields present: {', '.join(unmapped_labels)}"
            print(f"[Local Form Filler] Unmapped fields found: {unmapped_labels}. Handing off to LLM agent...")
            local_fill_success = False
            # Fill the mapped ones locally before handing off so the LLM agent doesn't have to repeat the work!
            if mapped_values:
                fill_mapped_fields_locally(page, mapped_values)
                take_page_screenshot(page, prefix=f"local_fill_partial_step_{local_step}")
            break
            
        # Fill mapped fields
        if mapped_values:
            fill_mapped_fields_locally(page, mapped_values)
            take_page_screenshot(page, prefix=f"local_fill_success_step_{local_step}")
            
        # Attempt to proceed (find Next/Continue/Submit button)
        # Search page text for "next", "continue", "submit", "apply" buttons
        html_content = page.content()
        button_pattern = re.compile(r'<(?:button|input|a)\b[^>]*>([\s\S]*?)</(?:button|input|a)>', re.IGNORECASE)
        
        # Let's find Next/Submit button locator
        next_button = None
        
        # Look for buttons containing "next", "continue", "submit", "apply"
        buttons = page.locator("button, input[type='button'], input[type='submit'], a.btn, a.button").all()
        for btn in buttons:
            try:
                btn_text = (btn.inner_text() or btn.get_attribute("value") or "").lower()
                if "submit" in btn_text or "apply" in btn_text:
                    next_button = btn
                    # Prefer submit/apply over next
                    break
                elif "next" in btn_text or "continue" in btn_text:
                    next_button = btn
            except Exception:
                pass
                
        if next_button:
            try:
                btn_text = next_button.inner_text() or next_button.get_attribute("value") or "Button"
                print(f"[Local Form Filler] Clicking '{btn_text}' to proceed...")
                next_button.scroll_into_view_if_needed()
                next_button.click()
                page.wait_for_timeout(3000)
                
                # Take post-click screenshot
                take_page_screenshot(page, prefix=f"local_step_{local_step}_clicked")
            except Exception as e:
                handoff_reason = f"Failed to click next button: {e}"
                local_fill_success = False
                break
        else:
            print("[Local Form Filler] No Next/Submit button found.")
            handoff_reason = "No Next or Submit button could be identified."
            local_fill_success = False
            break

    # If local filling succeeded and we didn't break out
    if local_fill_success:
        print("[Local Form Filler Success] All steps completed locally!")
        return

    # ----------------------------------------------------
    # LLM Agent Fallback/Handoff
    # ----------------------------------------------------
    print(f"\n[Handoff to LLM Agent]: Reason: {handoff_reason}")

    # Core set of browser tools (includes adjust_spinner_value)
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
        fill_entire_form,
        adjust_spinner_value,
        os_level_mouse_keyboard_action
    ]

    model_with_tools = model.bind_tools(tools)

    print("\n--- Starting Apply Agent Execution (LLM Mode) ---")
    print(f"Incognito Mode: INACTIVE (Persistent Context)")
    print(f"Target URL: {target_url}\n")

    # Build the prompt
    prompt = (
        f"You are a helpful browser automation agent. Your task is to apply for the job on the page: {target_url}\n\n"
        "Here are the instructions to guide you:\n"
        "1. We have already opened the page and filled some fields locally. Do NOT restart. Retrieve the current page state.\n"
        "2. Once the form is visible, call the `get_form_fields` tool to scan all remaining fields.\n"
        "3. Fill out the application form using browser tools like `fill_entire_form`, `input_text_into_element`, `adjust_spinner_value`, etc. with the correct details:\n"
        f"   - Full Name: {resume_info.get('name')}\n"
        f"   - Email Address: {resume_info.get('email')}\n"
        f"   - Phone Number: {resume_info.get('phone')}\n"
        f"   - GitHub: {resume_info.get('github')}\n"
        f"   - LinkedIn: {resume_info.get('linkedin')}\n"
        f"   - Current Company: {resume_info.get('current_company')}\n"
        f"   - Current Role: {resume_info.get('current_role')}\n"
        f"   - Experience: {resume_info.get('experience')}\n"
        f"   - Upload Resume (file type): Upload the file located at: {resume_path}\n"
        "4. Submit the application by clicking the submit button.\n"
        "5. Do not close the browser context. Keep the browser open so the final submission screen can be inspected.\n\n"
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
        "  \"completed_steps\": [\"Opened job page\", \"Filled contact info\"],\n"
        "  \"extracted_data\": {\"job_title\": \"Software Engineer\"},\n"
        "  \"next_immediate_step\": \"Submit application\"\n"
        "}\n"
        "</scratchpad>\n"
        "Do not omit this block from your response! Always output it."
    )

    state_summary = {
        "completed_steps": ["Completed local pre-filling", handoff_reason],
        "extracted_data": {},
        "next_immediate_step": "Scan remaining form fields"
    }

    messages = [
        HumanMessage(content=prompt),
        SystemMessage(content=f"### CURRENT AGENT STATE SUMMARY:\n{json.dumps(state_summary, indent=2)}")
    ]
    llm_call_token_logs = []
    
    session_id = getattr(manager, "session_id", None) or time.strftime("%Y%m%d_%H%M%S")

    try:
        max_steps = 15
        last_response_content = None
        for step in range(max_steps):
            # Dynamic check for redirection to Workday/Captcha
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
                        
                    # Check for captcha challenge before LLM call
                    if detect_captcha(manager.page):
                        print("[LLM Loop] Captcha detected. Exiting agent loop.")
                        return
            except Exception as e:
                print(f"[Handoff Warning]: Failed to check browser state for Workday/Captcha: {e}")

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
            with open(llm_log_filename, "w", encoding="utf-8") as f:
                json.dump(llm_call_token_logs, f, indent=4)
            print(f"[Apply Agent Token Logger] Dedicated LLM call token usage logged to: {llm_log_filename}")
        except Exception as e:
            print(f"[Apply Agent Token Logger Warning] Failed to save token log to file: {e}")
        close_browser_on_interrupt()
        raise KeyboardInterrupt

    # Write log file containing LLM call token usage
    try:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        llm_log_filename = log_dir / f"llm_call_token_usage_apply_{time.strftime('%Y%m%d_%H%M%S')}.json"
        with open(llm_log_filename, "w", encoding="utf-8") as f:
            json.dump(llm_call_token_logs, f, indent=4)
        print(f"[Apply Agent Token Logger] Dedicated LLM call token usage logged to: {llm_log_filename}")
    except Exception as e:
        print(f"[Apply Agent Token Logger Warning] Failed to save token log to file: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Apply for jobs automatically using Browser Agent")
    parser.add_argument("--url", nargs="?", help="The job application page URL")
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
