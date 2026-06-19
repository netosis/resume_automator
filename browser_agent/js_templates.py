# JavaScript code templates for browser automation

# Used in browser_tools.py
GET_COMPRESSED_DOM_JS = r'''
(mode) => {
    function cleanText(text) {
        return text.replace(/\s+/g, ' ').trim();
    }
    
    function isInteractive(el) {
        const tagName = el.tagName.toLowerCase();
        const role = el.getAttribute('role');
        const interactiveRoles = new Set([
            'button', 'link', 'checkbox', 'radio', 'combobox', 
            'listbox', 'menuitem', 'tab', 'slider', 'searchbox', 
            'spinbutton', 'switch', 'option', 'textbox'
        ]);
        const interactiveTags = new Set([
            'button', 'a', 'input', 'select', 'textarea', 'option', 'details', 'summary'
        ]);
        
        if (interactiveTags.has(tagName)) return true;
        if (role && interactiveRoles.has(role.toLowerCase())) return true;
        if (el.onclick || el.getAttribute('onclick')) return true;
        return false;
    }
    
    function getUniqueSelector(el) {
        if (el.id) {
            return `#${el.id}`;
        }
        let attrTests = ['data-testid', 'data-test-id', 'data-qa', 'name', 'placeholder'];
        for (let attr of attrTests) {
            let val = el.getAttribute(attr);
            if (val) {
                let safeVal = val.replace(/"/g, '\\"');
                let sel = `[${attr}="${safeVal}"]`;
                try {
                    if (document.querySelectorAll(sel).length === 1) {
                        return sel;
                    }
                } catch(e) {}
            }
        }
        
        let path = [];
        let parent = el;
        while (parent && parent.nodeType === Node.ELEMENT_NODE) {
            let tag = parent.tagName.toLowerCase();
            if (parent.id) {
                path.unshift(`#${parent.id}`);
                break;
            } else {
                let siblings = Array.from(parent.parentNode ? parent.parentNode.children : []);
                let index = siblings.indexOf(parent) + 1;
                path.unshift(`${tag}:nth-child(${index})`);
            }
            parent = parent.parentNode;
        }
        return path.join(' > ');
    }
    
    const results = [];
    const ignoredTags = new Set([
        'script', 'style', 'noscript', 'iframe', 'svg', 'path', 'g', 'meta', 'head', 'link'
    ]);
    
    function traverse(el) {
        const tagName = el.tagName.toLowerCase();
        if (ignoredTags.has(tagName)) return;
        
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        if (window.getComputedStyle(el).display === 'none' || window.getComputedStyle(el).visibility === 'hidden') return;
        
        let directText = "";
        for (let child of el.childNodes) {
            if (child.nodeType === Node.TEXT_NODE) {
                directText += child.nodeValue;
            }
        }
        directText = cleanText(directText);
        
        const isSelfInteractive = isInteractive(el);
        
        let isRelevant = false;
        if (mode === 'interactive') {
            isRelevant = isSelfInteractive;
        } else if (mode === 'reading') {
            const contentTags = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'span', 'div']);
            isRelevant = isSelfInteractive || (contentTags.has(tagName) && directText.length > 5);
        } else { // full
            isRelevant = isSelfInteractive || directText.length > 0;
        }
        
        if (isRelevant) {
            const selector = getUniqueSelector(el);
            const item = {
                tag: tagName,
                selector: selector
            };
            
            if (directText) {
                item.text = directText.slice(0, 100);
            }
            
            if (tagName === 'input') {
                item.type = el.type || 'text';
                if (el.placeholder) item.placeholder = el.placeholder;
                if (el.value) item.value = el.value;
                if (el.checked) item.checked = true;
                if (el.disabled) item.disabled = true;
            } else if (tagName === 'textarea') {
                if (el.placeholder) item.placeholder = el.placeholder;
                if (el.value) item.value = el.value;
                if (el.disabled) item.disabled = true;
            } else if (tagName === 'select') {
                if (el.value) item.value = el.value;
                if (el.disabled) item.disabled = true;
            }
            
            if (el.getAttribute('placeholder') && !item.placeholder) item.placeholder = el.getAttribute('placeholder');
            if (el.getAttribute('aria-label')) item.ariaLabel = el.getAttribute('aria-label');
            if (el.getAttribute('name')) item.name = el.getAttribute('name');
            if (el.getAttribute('role')) item.role = el.getAttribute('role');
            if (el.disabled) item.disabled = true;
            
            results.push(item);
        }
        
        for (let child of el.children) {
            traverse(child);
        }
    }
    
    traverse(document.body);
    return results;
}
'''

SCROLL_DOWN_JS = "window.scrollBy(0, window.innerHeight);"

SCROLL_UP_JS = "window.scrollBy(0, -window.innerHeight);"

FIND_APPLY_BUTTON_JS = r'''
() => {
    const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'));
    const patterns = [
        /^apply$/i,
        /^apply\s+now$/i,
        /apply\s+with\s+indeed/i,
        /submit\s+your\s+application/i,
        /submit\s+application/i,
        /apply\s+on\s+(company\s+)?site/i,
        /easy\s+apply/i,
        /apply\s+on\s+company\s+website/i,
        /continue/i,
        /next/i,
        /apply/i
    ];
    
    const visible = candidates.filter(el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
    });
    
    for (const pattern of patterns) {
        for (const el of visible) {
            const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
            if (pattern.test(text)) {
                el.setAttribute('data-automation-click-target', 'true');
                return { text: text, tagName: el.tagName.toLowerCase() };
            }
        }
    }
    return null;
}
'''

REMOVE_CLICK_TARGET_ATTR_JS = '''
() => {
    const el = document.querySelector('[data-automation-click-target="true"]');
    if (el) el.removeAttribute('data-automation-click-target');
}
'''

GET_FORM_FIELDS_JS = r'''
() => {
    const fields = Array.from(document.querySelectorAll('input, select, textarea, [role="checkbox"], [role="radio"]'));
    const result = [];
    
    fields.forEach((el, index) => {
        // Skip hidden elements
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        if (window.getComputedStyle(el).display === 'none' || window.getComputedStyle(el).visibility === 'hidden') return;
        
        const tagName = el.tagName.toLowerCase();
        const type = el.type || '';
        const id = el.id || '';
        const name = el.name || '';
        const value = el.value || '';
        const placeholder = el.placeholder || '';
        const isChecked = el.checked || false;
        const isRequired = el.required || false;
        
        // Find associated label text
        let labelText = '';
        if (id) {
            const labelEl = document.querySelector(`label[for="${id}"]`);
            if (labelEl) {
                labelText = labelEl.innerText.trim();
            }
        }
        if (!labelText) {
            // Try surrounding label
            const parentLabel = el.closest('label');
            if (parentLabel) {
                labelText = parentLabel.innerText.trim();
            }
        }
        if (!labelText) {
            // Try aria-label or title
            labelText = el.getAttribute('aria-label') || el.getAttribute('title') || '';
        }
        labelText = labelText.replace(/\s+/g, ' ').trim();
        
        // Collect dropdown options
        let options = [];
        if (tagName === 'select') {
            options = Array.from(el.options).map(opt => ({
                text: opt.text.trim(),
                value: opt.value
            }));
        }
        
        // Generate unique CSS selectors
        let selector = '';
        if (id) {
            selector = `#${id}`;
        } else if (name) {
            selector = `${tagName}[name="${name}"]`;
        } else if (type && type !== 'text') {
            selector = `${tagName}[type="${type}"]`;
        } else {
            // Unique path-based selector logic
            let path = [];
            let curr = el;
            while (curr && curr !== document.body) {
                let sibIdx = Array.from(curr.parentElement?.children || []).indexOf(curr) + 1;
                path.unshift(`${curr.tagName.toLowerCase()}:nth-child(${sibIdx})`);
                curr = curr.parentElement;
            }
            selector = path.join(' > ');
        }
        
        result.push({
            index: index + 1,
            tagName,
            type,
            id,
            name,
            labelText,
            placeholder,
            value,
            isChecked,
            isRequired,
            options,
            selector
        });
    });
    
    return result;
}
'''

GET_TAG_NAME_AND_ROLE_JS = "el => ({ tagName: el.tagName.toLowerCase(), role: el.getAttribute('role') })"

GET_TAG_NAME_JS = "el => el.tagName.toLowerCase()"


# Used in indeed_tools.py
INDEED_JOB_FETCH_JS = r'''
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
'''

INDEED_HEADER_INFO_JS = r'''
() => {
    const header = document.querySelector('.jobsearch-JobInfoHeader-title-container, .jobsearch-JobInfoHeader-title, h1[class*="jobsearch-JobInfoHeader-title"]');
    const title = header ? header.innerText.trim() : "N/A";
    
    const companyEl = document.querySelector('[data-testid="inlineHeader-companyName"] a, [data-testid="inlineHeader-companyName"]');
    const company = companyEl ? companyEl.innerText.trim() : "N/A";
    
    const locationEl = document.querySelector('[data-testid="inlineHeader-companyLocation"], .jobsearch-JobInfoHeader-subtitle [class*="location"]');
    const location = locationEl ? locationEl.innerText.trim() : "N/A";
    
    return { title, company, location };
}
'''

INDEED_DESC_TEXT_JS = r'''
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
'''

INDEED_APPLY_BUTTONS_JS = r'''
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
'''

INDEED_RIGHT_PANE_TEXT_JS = r'''
() => {
    const pane = document.querySelector('#jobsearch-ViewJobLayout-jobDetails, .jobsearch-ViewJobLayout-jobDetails, #vjs-container');
    return pane ? pane.innerText.trim() : "";
}
'''


# Used in naukri_agent_demo.py
NAUKRI_JOB_STATUS_CHECK_JS = r'''
() => {
    // Check for already applied
    const allElements = Array.from(document.querySelectorAll('button, a, span, div, p'));
    let isApplied = false;
    for (const el of allElements) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const text = (el.innerText || '').trim();
        if (/^(applied|already\s+applied|applied\s+successfully)$/i.test(text)) {
            isApplied = true;
            break;
        }
        if (/^(you\s+applied|applied\s+on\s+\d+)/i.test(text)) {
            isApplied = true;
            break;
        }
    }
    
    // Check for third-party apply buttons
    const clickableElements = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'));
    let isThirdParty = false;
    let buttonText = "";
    
    const thirdPartyPatterns = [
        /apply\s+on\s+company\s+site/i,
        /apply\s+on\s+company\s+website/i,
        /apply\s+on\s+employer\s+site/i,
        /apply\s+on\s+employer\s+website/i,
        /apply\s+on\s+external\s+site/i,
        /apply\s+on\s+advertiser\s+site/i
    ];

    for (const el of clickableElements) {
        const rect = el.getBoundingClientRect();
        const isVisible = rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
        if (!isVisible) continue;
        const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
        for (const pattern of thirdPartyPatterns) {
            if (pattern.test(text)) {
                isThirdParty = true;
                buttonText = text;
                break;
            }
        }
        if (isThirdParty) break;
    }

    return {
        isApplied: isApplied,
        isThirdParty: isThirdParty,
        buttonText: buttonText
    };
}
'''


# Used in naukri_tools.py
DETECT_NAUKRI_POPUP_JS = r'''
() => {
    const inputEl = document.querySelector("input[placeholder*='Type message'], textarea[placeholder*='Type message'], input[placeholder*='Type your answer'], textarea[placeholder*='Type your answer']");
    if (!inputEl) {
        return { detected: false };
    }
    
    const parentContainer = inputEl.closest("div[class*='modal'], div[class*='container'], div[class*='dialog'], body");
    let questionText = "";
    
    if (parentContainer) {
        const elements = Array.from(parentContainer.querySelectorAll("div, p, span, h1, h2, h3, h4, li"));
        const questionCandidates = elements.filter(el => {
            const text = el.innerText ? el.innerText.trim() : "";
            if (text.length > 5 && text.length < 250 && text.includes("?") && !el.querySelector("input, textarea, button")) {
                return true;
            }
            return false;
        });
        
        if (questionCandidates.length > 0) {
            const visibleQuestions = questionCandidates.filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
            });
            if (visibleQuestions.length > 0) {
                questionText = visibleQuestions[visibleQuestions.length - 1].innerText.trim();
            }
        }
    }
    
    if (!questionText) {
        const siblings = Array.from(document.querySelectorAll("div, p, span"));
        const textBubbles = siblings.filter(el => {
            const text = el.innerText ? el.innerText.trim() : "";
            return text.length > 5 && text.length < 200 && !el.querySelector("input, textarea, button") && 
                   (el.className.includes("msg") || el.className.includes("bubble") || el.className.includes("text") || el.className.includes("question"));
        });
        if (textBubbles.length > 0) {
            questionText = textBubbles[textBubbles.length - 1].innerText.trim();
        } else {
            questionText = "Recruiter question popup detected (unable to parse exact question text).";
        }
    }
    
    return {
        detected: true,
        question: questionText,
        placeholder: inputEl.placeholder || ""
    };
}
'''

GET_NEXT_NAUKRI_POPUP_QUESTION_JS = r'''
() => {
    const inputEl = document.querySelector("input[placeholder*='Type message'], textarea[placeholder*='Type message'], input[placeholder*='Type your answer'], textarea[placeholder*='Type your answer']");
    if (!inputEl) {
        return null;
    }
    const parentContainer = inputEl.closest("div[class*='modal'], div[class*='container'], div[class*='dialog'], body");
    let questionText = "";
    
    if (parentContainer) {
        const elements = Array.from(parentContainer.querySelectorAll("div, p, span, h1, h2, h3, h4, li"));
        const questionCandidates = elements.filter(el => {
            const text = el.innerText ? el.innerText.trim() : "";
            if (text.length > 5 && text.length < 250 && text.includes("?") && !el.querySelector("input, textarea, button")) {
                return true;
            }
            return false;
        });
        
        if (questionCandidates.length > 0) {
            const visibleQuestions = questionCandidates.filter(el => {
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
            });
            if (visibleQuestions.length > 0) {
                questionText = visibleQuestions[visibleQuestions.length - 1].innerText.trim();
            }
        }
    }
    return { question: questionText || "Next question bubble" };
}
'''
