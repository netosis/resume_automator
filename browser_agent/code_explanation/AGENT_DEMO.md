# agent_demo.py - Main Agent Loop

## Overview

`agent_demo.py` implements the core agent execution loop. It orchestrates the interaction between an LLM (Gemini or DeepSeek) and browser automation tools, handling retries, token tracking, and step-by-step task execution.

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
    H --> I["Create Initial Message<br/>with Task Prompt"]
    I --> J["Agent Loop"]
    J --> K["Invoke LLM with retry"]
    K --> L["LLM Response"]
    L --> M{Tool Calls?}
    M -->|Yes| N["Execute Tools"]
    M -->|No| O["Return Final Answer"]
    N --> P["Add Results to Messages"]
    P --> J
    O --> Q["Print Token Summary"]
    Q --> R["Return"]
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
    A["Initial Message"] --> |Task Prompt| B["HumanMessage"]
    B --> C["Agent Loop - Step 1"]
    C --> D["LLM Response<br/>may have tool_calls"]
    D --> E["AIMessage"]
    E --> F["Tool Execution"]
    F --> G["ToolMessage<br/>with result"]
    G --> H["Agent Loop - Step 2"]
    H --> D
    
    style B fill:#c3fae8
    style E fill:#ffd43b
    style G fill:#a5d8ff
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
agent_demo.py
├── Imports
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
│   ├── Import browser tools
│   ├── Create tool list
│   ├── Bind tools to LLM
│   ├── Create initial message
│   ├── Initialize tracking variables
│   ├── Agent loop (max 10 steps)
│   │   ├── Invoke LLM with retry
│   │   ├── Log LLM tokens
│   │   ├── Check for tool calls
│   │   ├── For each tool call:
│   │   │   ├── Count input tokens
│   │   │   ├── Execute tool
│   │   │   ├── Count output tokens
│   │   │   └── Log tool tokens
│   │   └── Add tool results to messages
│   ├── Print final answer
│   └── Print token summary
└── Main execution (if __name__ == "__main__")
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

1. **Exponential Backoff**: Respects API rate limits, increases wait time each attempt
2. **Token Tracking**: Monitors cost per tool and per LLM call for optimization
3. **Retry Logic**: Handles transient failures without failing entire workflow
4. **Step Limit**: Prevents infinite loops (max 10 steps)
5. **Message History**: LLM sees full context of previous interactions
6. **Tool Binding**: Leverages LangChain's built-in tool calling mechanism
7. **Error Isolation**: Tool errors don't crash agent, LLM sees errors and adapts
8. **Provider Flexibility**: Supports multiple LLM providers (Gemini, DeepSeek)

## Token Efficiency Tips

1. **Early Tool Specialization**: Use `naukri_job_fetch()` instead of `get_page_text()` for job pages
2. **Accessibility Mode**: Request "interactive" accessibility tree instead of "all"
3. **Targeted Extraction**: Get specific form fields instead of full page text
4. **Batch Operations**: Perform multiple actions per tool call when possible
5. **Result Truncation**: `get_page_text()` returns max 3000 chars, not unlimited

## Integration Points

- **LangChain**: `BaseTool`, `HumanMessage`, `AIMessage`, `ToolMessage`
- **LLM APIs**: Gemini, DeepSeek (via LangChain integration)
- **Browser**: All tools from `browser_tools.py`
- **Accessibility**: Uses tools defined in `accessibility_tree.py`
- **Configuration**: Reads from `.env` file
