# Agent Execution Loops (naukri_agent_demo.py / indeed_agent_demo.py)

## Overview

The browser agent scripts (`naukri_agent_demo.py` and `indeed_agent_demo.py`) implement the main agent execution loop. They orchestrate interaction between LLMs (Gemini/DeepSeek) and browser automation tools, incorporating:
1. **Programmatic Pre-filtering & Tab Preparation** (to minimize LLM navigation work).
2. **Stateful Scratchpad Memory** (to maintain compact structured state).
3. **Tool Output Pruning** (to prevent message context bloat).
4. **Retry Strategies** (to handle transient API failures).

## High-Level Agent Flow

```mermaid
graph TD
    A["run_browser_agent(prompt)"] --> B["Load Environment"]
    B --> C{Which Provider?}
    C -->|LLM_PROVIDER set| D["Use specified provider"]
    C -->|DEEPSEEK_API_KEY| E["Initialize DeepSeek"]
    C -->|GOOGLE_API_KEY| F["Initialize Gemini"]
    D --> G{LLM Provider}
    G -->|deepseek| E
    G -->|google| F
    E --> H["Bind Tools to LLM"]
    F --> H
    
    H --> Prep["Programmatic Job Openings Prep<br/>(Navigate search URL, sift through listings, check Applied / Third-Party status, open direct links in tabs)"]
    Prep --> I["Initialize Message History & Stateful Scratchpad"]
    I --> J["Agent Loop"]
    J --> Mem["Update Agent Memory:<br/>1. Parse scratchpad from last response<br/>2. Update state summary SystemMessage<br/>3. Prune older ToolMessage outputs"]
    Mem --> K["Invoke LLM with retry"]
    K --> L["LLM Response"]
    L --> M{Tool Calls?}
    M -->|Yes| N["Execute Tools (e.g. fill_entire_form, close_current_tab)"]
    M -->|No| O["Return Final Answer"]
    N --> P["Add Results to Messages"]
    P --> J
    O --> Q["Print Token Summary"]
    Q --> R["Return"]
```

## Programmatic Pre-Filtering Flow (Naukri)

```mermaid
graph TD
    Start["Start Prep Phase"] --> Ext["Extract Job Role from prompt"]
    Ext --> Nav["Open Naukri Search Page URL"]
    Nav --> Cards["Locate srp-jobtuple-wrapper elements"]
    Cards --> Count{Card Count > 0?}
    Count -->|No| Wait["Wait & Retry once"]
    Wait --> Cards
    Count -->|Yes| Loop["For each Job Card (1 to N)"]
    
    Loop --> Delay["Random Delay (1-2s)"]
    Delay --> Move["Move mouse slowly to link coordinates"]
    Move --> Click["Click title link to open in new tab"]
    Click --> Check["Evaluate job status on new tab (JS)"]
    
    Check --> Status{Job Status?}
    Status -->|Already Applied| Skip1["Skip listing & close tab (delay 5-7s)"]
    Status -->|Third-Party Site| Skip2["Log URL to skipped_third_party_jobs.txt<br/>& close tab (delay 5-7s)"]
    Status -->|Direct & Unapplied| Keep["Keep tab open for LLM processing"]
    
    Skip1 --> Front["Switch search tab to front"]
    Skip2 --> Front
    Keep --> Front
    
    Front --> Next{More cards?}
    Next -->|Yes| Loop
    Next -->|No| Close["Close search listings page tab"]
    Close --> Handoff["Hand off remaining open tabs to LLM Agent"]
```

## Retry Logic Flow

```mermaid
graph TD
    A["invoke_model_with_retry()"] --> B["Attempt: 1"]
    B --> C{Success?}
    C -->|Yes| D["Return Response"]
    C -->|No| E["Check Error Type"]
    
    E --> F{Is Transient Error?}
    F -->|Rate Limit 429| G["exponential_backoff"]
    F -->|Service Unavailable 503| G
    F -->|Other| H["Raise Exception"]
    
    G --> I["Calculate Backoff:<br/>delay = 2^attempt + random"]
    I --> J["Sleep duration"]
    J --> K["Attempt: 2/3/4/5"]
    K --> C
    
    H --> L["Fail immediately"]
    L --> M["Log Error"]
    
    style G fill:#ffd43b
    style H fill:#ff6b6b
    style D fill:#51cf66
```

## Tool Execution Loop

```mermaid
sequenceDiagram
    participant LLM
    participant Agent as Agent Loop
    participant Tools as Tool Registry
    participant Tool as Specific Tool
    
    LLM->>Agent: Response with tool_calls
    Agent->>Agent: For each tool_call
    activate Agent
    Agent->>Tools: Find matching tool
    Tools->>Tool: Get tool reference
    Tool-->>Agent: Tool found
    
    Agent->>Agent: Count input tokens
    Agent->>Tool: Invoke with args
    activate Tool
    Tool->>Tool: Execute (click, input, etc)
    Tool-->>Agent: Return result
    deactivate Tool
    
    Agent->>Agent: Count output tokens
    Agent->>Agent: Log tokens
    Agent->>LLM: Add ToolMessage to history
    deactivate Agent
    
    LLM->>Agent: Next LLM call
```

## Token Tracking Architecture

```mermaid
graph TB
    subgraph Tracking["Token Tracking"]
        LLMTokens["LLM Tokens"]
        ToolTokens["Tool Tokens"]
        TotalTokens["Total Tokens"]
    end
    
    subgraph Logging["Logging]
        LLMLog["LLM Token Log"]
        ToolLog["Tool Token Log"]
    end
    
    subgraph Reporting["Summary Report"]
        Report["Total Tokens Consumed"]
        Breakdown["Cost Breakdown by Component"]
    end
    
    LLMTokens --> |input + output| LLMLog
    ToolTokens --> |input + output| ToolLog
    LLMLog --> TotalTokens
    ToolLog --> TotalTokens
    TotalTokens --> Report
    LLMLog --> Breakdown
    ToolLog --> Breakdown
```

## Message History Structure

```mermaid
graph TD
    A["Initial Instructions (HumanMessage)"] --> B["State Summary (SystemMessage)<br/>Index 1 - Updated dynamically"]
    B --> C["Agent Loop Step"]
    C --> D["LLM Response (AIMessage)<br/>includes <scratchpad> JSON block"]
    D --> E["Tool Execution"]
    E --> F["Tool Outputs (ToolMessage)<br/>Last 2 fully intact, older ones pruned"]
    F --> C
    
    style A fill:#c3fae8
    style B fill:#ffd43b
    style D fill:#a5d8ff
```

## LLM Provider Configuration

```mermaid
graph TD
    A["Check Configuration"] --> B{LLM_PROVIDER set?}
    
    B -->|deepseek| C["Use DeepSeek"]
    B -->|google| D["Use Gemini"]
    B -->|not set| E{DEEPSEEK_API_KEY?}
    
    C --> F["Load DEEPSEEK_API_KEY"]
    F --> G["Get model name:<br/>deepseek-chat"]
    G --> H["Create ChatDeepSeek"]
    H --> I["Initialize LLM"]
    
    D --> J["Load GOOGLE_API_KEY"]
    J --> K["Get model name:<br/>gemini-2.5-flash"]
    K --> L["Create ChatGoogleGenerativeAI"]
    L --> I
    
    E -->|Yes| C
    E -->|No| D
```

## Code Structure

```
naukri_agent_demo.py / indeed_agent_demo.py
├── Imports (SystemMessage, update_agent_memory)
├── invoke_model_with_retry()
│   ├── Loop: max_retries times
│   ├── Try: Call model.invoke()
│   ├── Catch: Check error type
│   ├── If transient: exponential backoff
│   └── Return response or raise
├── run_browser_agent(prompt)
│   ├── Load .env
│   ├── Determine LLM provider
│   ├── Initialize LLM
│   ├── Bind tools to LLM
│   ├── Initialize state_summary & message history
│   ├── Agent loop (max 35 steps)
│   │   ├── Update Agent Memory (prunes old tool outputs & updates state summary)
│   │   ├── Invoke LLM with retry
│   │   ├── Log LLM tokens
│   │   ├── Check for tool calls
│   │   └── For each tool call:
│   │       ├── Count tokens & execute tool
│   │       └── Add tool results to messages
│   └── Print final answer & token summary
```

## Token Counting Strategy

```mermaid
graph TB
    A["Tool Input Args"] --> B["model.get_num_tokens()"]
    C["Tool Result"] --> D["model.get_num_tokens()"]
    
    B --> E["Count Input Tokens"]
    D --> F["Count Output Tokens"]
    
    E --> G["Sum: input + output"]
    F --> G
    
    G --> H["Add to total_tool_tokens"]
    
    I["LLM Response"] --> J{Has usage_metadata?}
    J -->|Yes| K["Extract input_tokens"]
    J -->|Yes| L["Extract output_tokens"]
    J -->|No| M["Set to 0"]
    
    K --> N["Add to total_llm_input"]
    L --> O["Add to total_llm_output"]
    M --> P["Skip logging"]
```

## Error Handling Flow

```mermaid
graph TD
    A["invoke_model_with_retry()"] --> B["Attempt API call"]
    B --> C{Exception?}
    
    C -->|No| D["Return response"]
    C -->|Yes| E["Parse error message"]
    
    E --> F{Error Type?}
    F -->|429 Rate Limit| G["Transient Error"]
    F -->|503 Unavailable| G
    F -->|quota exceeded| G
    F -->|unavailable| G
    F -->|Other| H["Permanent Error"]
    
    G --> I{Retry count?}
    I -->|< max| J["Sleep + Backoff"]
    I -->|= max| H
    
    J --> K["Increment delay"]
    K --> B
    
    H --> L["Raise exception"]
    L --> M["Agent catches error"]
    M --> N["Break loop"]
    N --> O["Return error message"]
    
    style G fill:#ffd43b
    style H fill:#ff6b6b
```

## Tool Binding and Calling

```python
# Tool binding creates callable versions
model_with_tools = model.bind_tools(tools)

# When LLM calls a tool, it returns:
response.tool_calls = [
    {
        "name": "tool_name",      # str
        "args": {...},            # dict
        "id": "call_123"          # str (for async tracking)
    },
    ...
]

# We then:
# 1. Find matching tool by name
# 2. Call tool.invoke(args)
# 3. Get result as string
# 4. Create ToolMessage with result and call id
# 5. Add to message history
# 6. LLM sees result and decides next action
```

## Agent Loop Termination Conditions

```mermaid
graph TD
    A["Agent Loop"] --> B{Tool Calls?}
    B -->|Yes| C["Execute Tools"]
    B -->|No| D["STOP: Agent Done"]
    C --> E["Add Results"]
    E --> F["Next Iteration"]
    F --> B
    
    G["Max Steps: 10"] --> |Reached| D
    H["API Error"] --> |Caught| D
    I["Tool Exception"] --> |Not caught| D
    
    style D fill:#51cf66
```

## Step-by-Step Execution Example

```
Step 1: LLM Input
  Task: "Search for Python jobs on Naukri"
  Tools: [open_website, search_naukri, get_page_text, ...]

Step 2: LLM Output
  Thought: "I need to search for Python jobs. Let me use search_naukri_via_url"
  Tool Call: search_naukri_via_url("Python Developer")

Step 3: Tool Execution
  Tool: search_naukri_via_url
  Input: {"job_title": "Python Developer"}
  Result: "Naukri search page loaded with 5000+ results"

Step 4: LLM Receives Result
  Sees: Tool result added to message history
  Thought: "Great! Now let me get the job details from the search results"
  Tool Call: naukri_job_fetch()

Step 5: Tool Execution
  Tool: naukri_job_fetch
  Result: JSON array of 10 job listings with title, company, salary

Step 6: LLM Receives Data
  Thought: "I have the job information. Let me provide final answer"
  No more tool calls

Step 7: Final Answer
  Returns complete list with formatting to user
```

## Reasoning Behind Design Choices

1. **Exponential Backoff**: Respects API rate limits, increases wait time each attempt.
2. **Token Tracking**: Monitors cost per tool and per LLM call for optimization.
3. **Stateful Scratchpad**: Replaces verbose message history with a single dynamically updated SystemMessage tracking goals, data, and steps.
4. **Tool Output Pruning**: Keeps only the last 2 steps of tool results intact, avoiding context limits and reducing token costs.
5. **Step Limit**: Set at a generous max 35 steps to allow thorough workflows.
6. **Tool Binding**: Leverages LangChain's built-in tool calling mechanism.
7. **Error Isolation**: Tool errors don't crash the agent; the LLM sees the error message and adapts.
8. **Provider Flexibility**: Supports multiple LLM providers (Gemini, DeepSeek).

## Token Efficiency Tips

1. **Memory Pruning**: Automatically prunes older, massive tool outputs (like DOM accessibility trees) to keep context tokens minimal.
2. **Stateful Scratchpad**: Restores context summary without needing the model to re-analyze historical turns.
3. **Early Tool Specialization**: Use `naukri_job_fetch()` instead of `get_page_text()` for job listings.
4. **Accessibility Mode**: Employs structural accessibility trees for 80%+ reduction in page data size.
5. **Batch Operations**: Uses `fill_entire_form` to fill forms in one call instead of field-by-field.

## Integration Points

- **LangChain**: `BaseTool`, `HumanMessage`, `AIMessage`, `ToolMessage`
- **LLM APIs**: Gemini, DeepSeek (via LangChain integration)
- **Browser**: All tools from `browser_tools.py`
- **Accessibility**: Uses tools defined in `accessibility_tree.py`
- **Configuration**: Reads from `.env` file
