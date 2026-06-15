flowchart TD
    Start([Start: __main__]) --> Main[main Function]
    
    Main --> InitLogging[Configure logging with INFO level]
    InitLogging --> ParseCLI[Parse CLI arguments:<br/>txt_path, output-dir, output-name,<br/>base-latex-path, model, api-key,<br/>provider, api-base]
    
    ParseCLI --> SetupEnv[Apply provider & api-base overrides to environment]
    SetupEnv --> CallConverter[Call txt_to_resume_latex]
    
    subgraph Conversion[txt_to_resume_latex Method]
        CallConverter --> ResolvePaths[Resolve & validate input files:<br/>resolve_txt_path, resolve_latex_template_path]
        ResolvePaths --> ReadFiles[Read plain text resume & LaTeX base template]
        ReadFiles --> LoadEnv[Load environment variables via load_env_file]
        
        LoadEnv --> GetProvider{Determine LLM provider<br/>from environment/config}
        GetProvider -->|deepseek| InitDeepSeek[Initialize ChatDeepSeek:<br/>Determine model, resolve API key,<br/>set API base, temperature=0]
        GetProvider -->|google/gemini| InitGemini[Initialize ChatGoogleGenerativeAI:<br/>Determine model, resolve API key]
        
        InitDeepSeek --> BuildPrompt[Build User Prompt:<br/>Base template structure + Resume text]
        InitGemini --> BuildPrompt
        
        BuildPrompt --> LogSizes[Calculate & log prompt characters/tokens size estimates]
        LogSizes --> InvokeLLM[Call LLM.invoke with SYSTEM_PROMPT & User Prompt]
        
        InvokeLLM --> LogUsage[Extract & log API token usage metrics]
        LogUsage --> StripFences[Call strip_code_fences on response content]
        
        StripFences --> MakeDir[Resolve output directory & create if needed]
        MakeDir --> SaveFile[Write clean LaTeX code to output path]
        SaveFile --> ReturnPath[Return generated LaTeX file Path]
    end
    
    ReturnPath --> Success[Success: Return generated file path]
    Success --> End
    
    Conversion -.->|Exception Raised| HandleException[Catch error in main]
    HandleException --> LogError[Log failure & Exit with code 1]
    LogError --> End
    
    End([End])
    
    style Start fill:#e1f5e1
    style End fill:#ffe1e1
    style Conversion fill:#e3f2fd
