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
    
    subgraph ApplyAgent[run_apply_agent Flow]
        CallAgent --> CheckWorkday{Is Workday URL?}
        CheckWorkday -->|Yes| HandoffWorkday[Handoff to workday_agent]
        HandoffWorkday --> End
        CheckWorkday -->|No| LoadLLM[Load LLM Provider & Keys]
        
        LoadLLM --> NavigateTarget[Open Page & Take Initial Screenshot]
        NavigateTarget --> CheckCaptcha1{Captcha Detected?}
        CheckCaptcha1 -->|Yes| SaveManual[Log to manual_applications.txt & Exit]
        
        CheckCaptcha1 -->|No| FindApply[Search Apply Buttons via Regex]
        FindApply --> ApplyCheck{Buttons Found?}
        ApplyCheck -->|No| VisionFallback[vision_find_apply_button_text]
        VisionFallback --> VisionCheck{Text Identified?}
        VisionCheck -->|No| SaveManual
        VisionCheck -->|Yes| ClickApplyBtn[Click identified element]
        ApplyCheck -->|Yes| ClickApplyBtn
        
        ClickApplyBtn --> LocalLoopStart[Start Local Form Filler Loop (up to 5 steps)]
        
        subgraph LocalFiller[Local Multi-Step Form Filler]
            LocalLoopStart --> LocalCaptcha{Captcha Detected?}
            LocalCaptcha -->|Yes| SaveManual
            LocalCaptcha -->|No| GetFields[Evaluate GET_FORM_FIELDS_JS]
            GetFields --> MapFields[map_fields_with_resume_data]
            MapFields --> UnmappedCheck{Unmapped Fields?}
            
            UnmappedCheck -->|Yes| PartialFill[fill_mapped_fields_locally (partial)]
            PartialFill --> HandoffLLM[Break loop -> Handoff to LLM Agent]
            
            UnmappedCheck -->|No| FullLocalFill[fill_mapped_fields_locally (full)]
            FullLocalFill --> FindNext[Search Next/Submit Button]
            FindNext --> NextCheck{Next Button Found?}
            NextCheck -->|Yes| ClickNext[Click Next & Wait]
            ClickNext --> LocalLoopStart
            NextCheck -->|No| LocalSuccessCheck[Check if Successfully Applied]
        end
        
        HandoffLLM --> SetupLLMAgent[Bind tools & Setup Stateful Scratchpad]
        SetupLLMAgent --> LLMLoop[Start LLM Agent Loop: 1 to 15]
        
        subgraph LLM_Loop[LLM Fallback Agent]
            LLMLoop --> AgentCaptcha{Captcha/Workday?}
            AgentCaptcha -->|Yes| ExitAgent[Exit Loop]
            AgentCaptcha -->|No| InvokeLLM[Invoke LLM with retry]
            InvokeLLM --> ToolCallCheck{Tool Calls?}
            ToolCallCheck -->|No| SuccessLLM[Stop: Application Complete]
            ToolCallCheck -->|Yes| ExecTools[Execute Tools (adjust_spinner_value, etc)]
            ExecTools --> AppendLLM[Append Results]
            AppendLLM --> NextLLMStep{Steps Left?}
            NextLLMStep -->|Yes| LLMLoop
            NextLLMStep -->|No| MaxLLM[Stop: Max Steps]
        end
    end
    
    SaveManual --> End([End])
    LocalSuccessCheck --> End
    ExitAgent --> End
    SuccessLLM --> End
    MaxLLM --> End
    
    style Start fill:#e1f5e1
    style End fill:#ffe1e1
    style SetupDummy fill:#e8f5e9
    style LocalFiller fill:#fff3e0
    style LLM_Loop fill:#e3f2fd
