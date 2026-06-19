# Browser Agent - Code Explanation Guide

## Quick Navigation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System overview and component interactions
- **[BROWSER_TOOLS.md](BROWSER_TOOLS.md)** - Browser automation tools and PersistentBrowserManager
- **[ACCESSIBILITY_TREE.md](ACCESSIBILITY_TREE.md)** - Token-efficient navigation strategies
- **[AGENT_DEMO.md](AGENT_DEMO.md)** - Main agent loop and LLM orchestration

## What is the Browser Agent?

The Browser Agent is an AI-powered web automation system that combines:
- **Language Models** (Gemini 2.5 Flash or DeepSeek) for decision-making
- **Browser Automation** (Playwright with Brave/Firefox) for web interaction
- **Token Optimization** (5 strategies) for cost-effective API usage
- **Tool Binding** (LangChain) for seamless LLM-tool integration

### Key Capability
The agent can understand complex tasks in natural language and autonomously execute them on websites by deciding which actions to take and when.

## System Architecture

```
User Request
    ↓
[Agent Loop]
    ↓
LLM (Gemini/DeepSeek) - Decides what to do
    ↓
Tool Selection - "I should click the search button"
    ↓
Browser Tools - Executes the action
    ↓
Persistent Browser - Maintains state
    ↓
Website - Receives user interaction
    ↓
Result Back to LLM - "Button clicked, new page loaded"
    ↓
LLM Decides Next Action or Returns Final Answer
```

## The 5 Token-Saving Strategies

### 1. **Accessibility Tree (vs Full DOM)**
- **Old**: Send entire HTML to LLM (500-5000 tokens)
- **New**: Send only interactive elements (50-200 tokens)
- **Savings**: 80-90% reduction

### 2. **Lazy Browser Launch**
- Browser only starts when first tool calls for it
- Avoids startup overhead if not needed
- Saves ~2-5 seconds per invocation

### 3. **Smart Text Truncation**
- `get_page_text()` returns max 3000 characters
- Prevents unlimited token consumption from long pages
- LLM learns to handle summaries

### 4. **Specialized Tools**
- `naukri_job_fetch()` extracts job data as JSON
- Generic `get_page_text()` extracts full text
- Domain-specific tools are 10-50% cheaper

### 5. **Persistent Context**
- Browser state maintained across operations
- Cookies, session storage preserved
- Avoid re-authentication or page reloads

## How It Works - A Real Example

### Task: "Find 3 Python jobs on Naukri.com with salary > 15 LPA"

**Step 1: User Input**
```
run_browser_agent("Find 3 Python jobs on Naukri with salary > 15 LPA")
```

**Step 2: Agent Decides**
```
LLM: "I need to:
  1. Open Naukri.com
  2. Search for 'Python Developer'
  3. Filter by salary
  4. Extract job details"
```

**Step 3: Execute Actions**
```
Tool 1: search_naukri_via_url("Python Developer")
Result: Search results loaded (500 tokens)

Tool 2: naukri_job_fetch()
Result: [
  {job_title: "Python Developer", company: "TCS", salary: "16 LPA"},
  {job_title: "Senior Python Dev", company: "Google", salary: "25 LPA"},
  ...
] (300 tokens)
```

**Step 4: Final Answer**
```
LLM sees results, filters by salary, returns:
"Found 3 matching jobs:
1. Python Developer at TCS - 16 LPA
2. Senior Python Dev at Google - 25 LPA
3. Lead Python Dev at Microsoft - 30 LPA"
```

**Token Cost**: ~1000 tokens
**Time**: ~5-10 seconds
**Success**: ✅

## Core Components Explained

### 1. PersistentBrowserManager (Singleton)
**Purpose**: Manage a single browser instance across all tool calls

**Why**: 
- Avoids launching browser 10+ times
- Maintains cookies and session state
- Reduces startup overhead

**Flow**:
```python
# First call
manager = PersistentBrowserManager.get_instance()
page = manager.get_page()  # Launches browser

# Second call
manager = PersistentBrowserManager.get_instance()  # Same instance!
page = manager.get_page()  # Returns cached page
```

### 2. Browser Tools (14+ functions)
**Categories**:
- **Navigation**: `open_website()`, `search_naukri_via_url()`
- **Interaction**: `click_on_element()`, `input_text_into_element()`, `scroll_page()`
- **Form Handling**: `select_dropdown_option()`, `set_checkbox_state()`, `upload_file()`
- **Information**: `get_page_text()`, `get_accessibility_tree()`, `get_form_fields()`
- **Specialized**: `naukri_job_fetch()`, `click_apply_button()`, `fetch_job_details()`

### 3. Accessibility Tools
**Purpose**: Token-efficient page analysis

**Techniques**:
- CDP (Chrome DevTools Protocol) for AX tree extraction
- Role-based filtering (button, textbox, link, etc.)
- Lazy browser launch with persistence

### 4. Agent Loop
**Process**:
1. LLM receives task + tools
2. LLM decides which tool to call
3. Tool executes, returns result
4. LLM sees result, decides next action
5. Repeat until done (max 10 steps)

**Retry Logic**: 
- Handles rate limits (429)
- Handles service errors (503)
- Exponential backoff (2s, 4s, 8s, 16s, 32s)

## File Organization

```
browser_agent/
├── browser_tools.py
│   ├── PersistentBrowserManager (singleton browser control)
│   ├── 14+ tool functions (automation tools)
│   ├── Accessibility helpers
│   └── Text/tree processing utilities
│
├── accessibility_tree.py
│   ├── Logging setup
│   ├── Browser launch helpers
│   ├── CDP-based AX tree extraction
│   ├── Pydantic models for type safety
│   └── AccessibilityTreeTool (LangChain integration)
│
├── agent_demo.py
│   ├── retry logic (exponential backoff)
│   ├── LLM provider initialization (Gemini/DeepSeek)
│   ├── Agent loop (10 steps max)
│   ├── Tool binding & calling
│   ├── Token tracking
│   └── Error handling
│
├── code_explanation/
│   ├── ARCHITECTURE.md (this directory)
│   ├── BROWSER_TOOLS.md
│   ├── ACCESSIBILITY_TREE.md
│   ├── AGENT_DEMO.md
│   └── README.md (you are here)
│
└── agent_code/ (test directory)
    └── Custom_Chrome_Profile/ (browser profile)
```

## Key Design Patterns

### 1. Singleton Pattern
**Used in**: `PersistentBrowserManager`
**Why**: Ensure only one browser instance exists
**Benefit**: Memory efficiency, state persistence

### 2. Tool Provider Pattern
**Used in**: LangChain tool binding
**Why**: Let LLM autonomously decide which tool to use
**Benefit**: Flexible, adaptable workflows

### 3. Retry Strategy
**Used in**: `invoke_model_with_retry()`
**Why**: Handle transient API failures
**Benefit**: Resilient, production-ready

### 4. Accessibility-First
**Used in**: Page analysis
**Why**: Semantic content, not visual noise
**Benefit**: 80% token reduction

## Error Handling Philosophy

```
Tool Call Fails?
    ↓
Catch and log error
    ↓
LLM sees error message
    ↓
LLM decides: Retry, use different approach, or give up
    ↓
Continue workflow or report to user
```

**Why**: Errors are informative, not fatal. LLM adapts.

## Performance Metrics

| Metric | Typical Value |
|--------|---------------|
| Browser startup | 2-5 seconds |
| Tool execution | 0.5-3 seconds |
| LLM invocation | 1-5 seconds |
| Page load | 2-5 seconds |
| **Total per step** | **5-15 seconds** |
| **Tokens per step** | **100-500 tokens** |
| **Cost (Gemini)** | **$0.0005-0.002 per step** |

## Configuration via Environment Variables

```bash
# LLM Selection
export LLM_PROVIDER=deepseek          # or "google"
export GEMINI_API_KEY=...             # or GOOGLE_API_KEY
export DEEPSEEK_API_KEY=...
export DEEPSEEK_MODEL=deepseek-chat   # optional

# Browser Configuration
export BROWSER_TYPE=brave              # or "firefox"
export BROWSER_HEADLESS=false          # show browser window
export BROWSER_INCOGNITO=false         # don't use private mode
export USE_PERSISTENT_CONTEXT=true     # reuse profile

# Logging
export LOG_LEVEL=INFO                  # debug logging
```

## When to Use Each Tool

| Goal | Tool | Token Cost |
|------|------|------------|
| See page structure | `get_accessibility_tree()` | 100 |
| See page text | `get_page_text()` | 200-500 |
| Extract form fields | `get_form_fields()` | 100-300 |
| Get buttons | `get_interactable_buttons()` | 100-200 |
| Click button | `click_on_element()` | 50 |
| Type text | `input_text_into_element()` | 50 |
| Get job data | `naukri_job_fetch()` | 200-400 |
| General page data | `fetch_job_details()` | 300-500 |

## Debugging Tips

### Enable Debug Logging
```python
from accessibility_tree import setup_logging
import logging
logger = setup_logging(level=logging.DEBUG)
```

### Monitor Token Usage
- Agent prints token count per step
- Use for cost estimation
- Identify expensive operations

### Check Browser State
- `get_page_text()` to see current state
- `get_accessibility_tree()` to see interactive elements
- Visual verification: browser window shows real-time actions

### Common Issues

**Issue**: "Chrome executable not found"
- **Solution**: Install Brave or set `BROWSER_TYPE=firefox`

**Issue**: "Browser timeout"
- **Solution**: Ensure all Chrome/Brave processes are closed

**Issue**: "API rate limit"
- **Solution**: Agent automatically retries with backoff

**Issue**: "High token usage"
- **Solution**: Use specialized tools (e.g., `naukri_job_fetch()` vs `get_page_text()`)

## Future Improvements

1. **Multi-step planning**: Break complex tasks into sub-goals
2. **Visual understanding**: Add vision capabilities to accessibility tree
3. **Caching**: Remember previously visited pages
4. **Screenshot recording**: Capture agent's work for audit trails
5. **Custom tools**: Domain-specific extractors for unique websites
6. **Parallelization**: Run multiple agent instances in parallel

## Integration Example

```python
from agent_demo import run_browser_agent

# Task 1: Job search
result = run_browser_agent(
    "Find 5 Python jobs with salary > 20 LPA on Naukri"
)

# Task 2: Form filling
result = run_browser_agent(
    "Go to example.com/apply and fill form with provided data"
)

# Task 3: Data extraction
result = run_browser_agent(
    "Extract all product prices from amazon.com/search?q=laptop"
)
```

## Learning Path

1. **Start**: Read [ARCHITECTURE.md](ARCHITECTURE.md) for overview
2. **Understand Tools**: Read [BROWSER_TOOLS.md](BROWSER_TOOLS.md) for available operations
3. **Token Optimization**: Read [ACCESSIBILITY_TREE.md](ACCESSIBILITY_TREE.md) for cost-saving
4. **Agent Logic**: Read [AGENT_DEMO.md](AGENT_DEMO.md) for execution flow
5. **Experiment**: Create small tasks and monitor token usage

## Resources

- **Playwright Docs**: https://playwright.dev/python/
- **LangChain Docs**: https://python.langchain.com/
- **Gemini API**: https://ai.google.dev/
- **DeepSeek API**: https://www.deepseek.com/

## Summary

The Browser Agent is a powerful system for web automation that combines:
- ✅ AI decision-making (LLM)
- ✅ Autonomous tool selection
- ✅ Token-efficient operations (80% reduction)
- ✅ Error resilience (retries + adaptation)
- ✅ Multi-provider support (Gemini, DeepSeek)
- ✅ Cost tracking per operation

**Key Insight**: Instead of sending full pages to LLM, send only semantically important elements. This reduces tokens by 80% while improving accuracy.

---

**Last Updated**: June 2026  
**Status**: Production Ready  
**Maintainer**: Browser Agent Team
