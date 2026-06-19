flowchart TD
    Start([Start: __main__]) --> ParseCLI[Parse target URL CLI argument]
    ParseCLI --> CheckURL{URL provided?}
    
    CheckURL -->|No| LocalMock[Resolve local mock_form.html file URI]
    CheckURL -->|Yes| SetTarget[Use provided URL]
    
    LocalMock --> DummyResume[Call ensure_dummy_resume]
    SetTarget --> DummyResume
    
    subgraph SetupDummy[Dummy Resume Preparation]
        DummyResume --> CheckDummyExists{Dummy file exists?}
        CheckDummyExists -->|Yes| ReturnResumePath[Return dummy resume path]
        CheckDummyExists -->|No| CreateDummy[Write minimal binary structure PDF to testcode/dummy_resume.pdf]
        CreateDummy --> ReturnResumePath
    end
    
    ReturnResumePath --> CallAgent[Call run_apply_agent]
    
    subgraph ApplyAgent[run_apply_agent Loop]
        CallAgent --> ResolveLLM[Determine provider & load API keys]
        ResolveLLM --> InitLLM[Initialize model: ChatDeepSeek or ChatGoogleGenerativeAI]
        InitLLM --> BindTools[Bind application tools list to model]
        
        BindTools --> BuildPrompt[Construct specialized job application prompt:<br/>1. Open target URL<br/>2. Click Apply Now/Apply button<br/>3. Call get_form_fields to scan inputs<br/>4. Fill form inputs with static candidate details<br/>5. Upload dummy resume<br/>6. Check privacy policy checkboxes<br/>7. Submit form]
        
        BuildPrompt --> StartLoop[Start Step Loop: 1 to 15]
        StartLoop --> InvokeModel[Invoke LLM with retry backoff]
        InvokeModel --> CheckToolCalls{Does response contain<br/>tool calls?}
        
        CheckToolCalls -->|No| SuccessExit[Stop: Application completed]
        CheckToolCalls -->|Yes| ExecuteTools[Execute proposed browser tool calls]
        ExecuteTools --> AppendResponses[Append tool results to message history]
        AppendResponses --> NextStep{Remaining step<br/>count > 0?}
        
        NextStep -->|Yes| StartLoop
        NextStep -->|No| MaxStepsExit[Stop: Reached step limit]
    end
    
    SuccessExit --> End([End])
    MaxStepsExit --> End
    
    style Start fill:#e1f5e1
    style End fill:#ffe1e1
    style SetupDummy fill:#e8f5e9
    style ApplyAgent fill:#e3f2fd
