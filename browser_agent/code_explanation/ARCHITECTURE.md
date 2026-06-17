# Browser Agent Architecture

## System Overview

The browser agent is a multi-component system that automates web browser interactions using AI language models (Gemini or DeepSeek). It combines token-efficient navigation strategies with LangChain's tool-calling capabilities to accomplish complex web automation tasks.

## Component Diagram

```mermaid
graph TB
    subgraph Agent["Agent Layer"]
        AgentDemo["agent_demo.py<br/>Main Agent Loop"]
        RetryLogic["Retry Logic<br/>Exponential Backoff"]
        TokenTracking["Token Counter<br/>Cost Analytics"]
    end
    
    subgraph LLM["Language Model Layer"]
        Gemini["Gemini API<br/>gemini-2.0-flash"]
        DeepSeek["DeepSeek API<br/>deepseek-chat"]
    end
    
    subgraph Tools["Tool Layer"]
        BrowserTools["browser_tools.py<br/>14+ Browser Automation Tools"]
        AccessibilityTools["accessibility_tree.py<br/>Browser Helpers & Utilities"]
    end
    
    subgraph Browser["Browser Layer"]
        PersistentMgr["PersistentBrowserManager<br/>Singleton Pattern"]
        Playwright["Playwright SDK<br/>Chromium/Firefox/Brave"]
        OS["Operating System<br/>Browser Executables"]
    end
    
    subgraph Target["Target Website"]
        Website["web.site.com<br/>HTML/DOM"]
    end
    
    AgentDemo -->|Calls| Gemini
    AgentDemo -->|Calls| DeepSeek
    Gemini -->|Tool Calls| BrowserTools
    DeepSeek -->|Tool Calls| BrowserTools
    BrowserTools -->|Uses| AccessibilityTools
    BrowserTools -->|Uses| PersistentMgr
    AccessibilityTools -->|Uses| PersistentMgr
    PersistentMgr -->|Controls| Playwright
    Playwright -->|Launches| OS
    OS -->|Interacts with| Website
```

## Data Flow Diagram

```mermaid
sequenceDiagram
    participant User
    participant Agent as agent_demo.py
    participant LLM as LLM (Gemini/DeepSeek)
    participant Tools as browser_tools.py
    participant Manager as PersistentBrowserManager
    participant Browser as Browser Instance
    
    User->>Agent: run_browser_agent(prompt)
    Agent->>Agent: Initialize LLM & bind tools
    Agent->>LLM: Invoke with task prompt
    LLM->>Agent: Return with tool calls
    loop For each tool call
        Agent->>Tools: Invoke tool (e.g., click, input)
        Tools->>Manager: Get current page
        Manager->>Browser: Execute action
        Browser->>Browser: Interact with DOM
        Browser-->>Manager: Return result
        Manager-->>Tools: Page updated
        Tools-->>Agent: Tool result
        Agent->>LLM: Feed result back
    end
    LLM->>Agent: Final response
    Agent->>User: Task complete
```

## Key Design Patterns

### 1. **Singleton Pattern** (PersistentBrowserManager)
- Ensures only one browser instance exists across the application
- Reuses browser context and page for all tool calls
- Reduces resource consumption

### 2. **Tool Provider Pattern** (LangChain)
- Browser tools are registered with the LLM
- LLM decides which tools to call based on task
- Enables autonomous decision-making

### 3. **Retry Strategy** (agent_demo.py)
- Exponential backoff for rate limiting (429, 503 errors)
- Graceful handling of transient failures
- Configurable retry attempts

### 4. **Accessibility-First Approach**
- Uses accessibility tree instead of full DOM
- Reduces token usage by 80%+
- More reliable element identification

## Execution Flow

```
1. Initialize Agent
   ├─ Load environment variables
   ├─ Initialize LLM (Gemini or DeepSeek)
   └─ Register browser tools
   
2. Agent Loop
   ├─ Send task + messages to LLM
   ├─ LLM decides: Continue or Call Tool
   │  ├─ If Continue: Return final answer
   │  └─ If Tool Call:
   │     ├─ Execute tool via browser
   │     ├─ Get tool result
   │     ├─ Add to message history
   │     └─ Loop back to LLM
   
3. Cleanup
   ├─ Keep browser open (per instructions)
   ├─ Print token usage summary
   └─ Return final response
```

## Environment Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Gemini authentication | None |
| `DEEPSEEK_API_KEY` | DeepSeek authentication | None |
| `LLM_PROVIDER` | Which LLM to use | `deepseek` (if available), else `google` |
| `BROWSER_TYPE` | Browser to launch | `brave` |
| `BROWSER_INCOGNITO` | Launch in private mode | `false` |
| `USE_PERSISTENT_CONTEXT` | Reuse browser profile | `true` |
| `BROWSER_HEADLESS` | Hide browser window | `false` |

## Token Optimization Strategies

The system implements 5 key strategies to reduce token usage:

1. **Accessibility Tree Pruning**: Only returns interactive elements (buttons, inputs, links)
2. **Page Text Truncation**: Limits content to 3000 characters
3. **Structured Output**: Uses JSON for consistent, compact results
4. **Session Persistence**: Reuses browser state across multiple operations
5. **Smart Tool Selection**: Specialized tools for specific tasks (e.g., `naukri_job_fetch` for job pages)

## Error Handling Strategy

```mermaid
graph TD
    A["Tool Call"] -->|Success| B["Return Result"]
    A -->|Browser Error| C["Log Error"]
    A -->|Element Not Found| D["Check Selector"]
    A -->|Network Timeout| E["Retry"]
    A -->|API Rate Limit| F["Exponential Backoff"]
    C --> B
    D --> B
    E -->|Success| B
    E -->|Failed| G["Report Failure"]
    F -->|Success| B
    F -->|Failed| G
```
