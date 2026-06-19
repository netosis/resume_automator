flowchart TD
    Start([Start: __main__]) --> Welcome[Display welcome message]
    Welcome --> GetPrompt[Prompt user for custom task description or use default]
    GetPrompt --> CallAgent[Call run_browser_agent]
    
    subgraph AgentLoop[run_browser_agent Execution]
        CallAgent --> ResolveLLM[Determine provider: google or deepseek]
        ResolveLLM --> InitLLM{Provider choice?}
        
        InitLLM -->|deepseek| InitDeepSeek[Initialize ChatDeepSeek:<br/>Set base URL, model name,<br/>key, temperature=0]
        InitLLM -->|google/gemini| InitGemini[Initialize ChatGoogleGenerativeAI:<br/>Set model name, key,<br/>temperature=0]
        
        InitDeepSeek --> BindTools[Bind browser tools library to LLM instance]
        InitGemini --> BindTools
        
        BindTools --> InitMessages[Construct system prompt instructions<br/>and initialize messages list]
        InitMessages --> StartStep[Start Step Loop: 1 to 10]
        
        StartStep --> InvokeLLM[Invoke LLM with exponential retry backoff]
        InvokeLLM --> LogUsage[Track LLM call input/output token usage]
        LogUsage --> PrintThoughts[Display LLM response content/thoughts]
        
        PrintThoughts --> CheckToolCalls{Does response contain<br/>tool calls?}
        CheckToolCalls -->|No| SuccessExit[Stop: Task complete]
        
        CheckToolCalls -->|Yes| IterateCalls[Iterate through proposed tool calls]
        IterateCalls --> GetTool[Find matching function in registered browser tools]
        GetTool --> RunTool[Invoke tool function with arguments]
        RunTool --> TrackToolTokens[Measure and log tool input/output token metrics]
        TrackToolTokens --> AppendToolMessage[Append ToolMessage response to history]
        
        AppendToolMessage --> NextStep{Remaining step<br/>count > 0?}
        NextStep -->|Yes| StartStep
        NextStep -->|No| MaxStepsExit[Stop: Reached max steps limit]
    end
    
    SuccessExit --> LogSession[Aggregrate total token metrics<br/>Save logs to logs/session_token_usage_TIMESTAMP.json]
    MaxStepsExit --> LogSession
    
    LogSession --> End([End])
    
    style Start fill:#e1f5e1
    style End fill:#ffe1e1
    style AgentLoop fill:#e3f2fd
