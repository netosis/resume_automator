flowchart TD
    Start([Start: __main__]) --> Main[main Function]
    
    Main --> ParseArgs[Parse Command Line Arguments:<br/>tex_file, output_dir, output_name,<br/>compiler, log_level]
    ParseArgs --> SetupLogging[Configure Logging with Specified Level]
    
    SetupLogging --> CheckTexFile{tex_file<br/>provided?}
    CheckTexFile -->|No| PromptTex[Prompt User for TeX File Path]
    PromptTex --> ValidateTex{Path<br/>entered?}
    ValidateTex -->|No| ErrorExit1[Print Error & Exit]
    ValidateTex -->|Yes| CheckOutputDir
    
    CheckTexFile -->|Yes| CheckOutputDir{output_dir<br/>provided?}
    CheckOutputDir -->|No| PromptOutputDir[Prompt User for Output Directory]
    CheckOutputDir -->|Yes| CheckOutputName
    PromptOutputDir --> CheckOutputName
    
    CheckOutputName{output_name<br/>provided?} -->|No| PromptOutputName[Prompt User for Output Name]
    CheckOutputName -->|Yes| CreateEngine
    PromptOutputName --> CreateEngine
    
    CreateEngine[Create LatexEngine Instance<br/>with Optional Compiler] --> InitEngine
    
    subgraph EngineInit[LatexEngine.__init__]
        InitEngine[Initialize Engine] --> CheckCompiler{compiler<br/>provided?}
        CheckCompiler -->|Yes| UseProvided[Use Provided Compiler]
        CheckCompiler -->|No| AutoDetect[_detect_compiler Method]
    end
    
    AutoDetect --> TryCompilers{Try Compilers:<br/>pdflatex, xelatex, lualatex}
    
    subgraph CompilerDetection[Compiler Detection Process]
        TryCompilers --> TryResolve[Try _find_compiler_executable]
        TryResolve --> CheckPATH{Found on<br/>System PATH?}
        CheckPATH -->|Yes| Resolved[Return Compiler Path]
        CheckPATH -->|No| CheckWindows[Check Windows MiKTeX<br/>Installation Paths]
        CheckWindows -->|Found| Resolved
        CheckWindows -->|Not Found| TryNext{More compilers<br/>to try?}
        TryNext -->|Yes| TryResolve
        TryNext -->|No| NoCompiler[Return None]
    end
    
    UseProvided --> RenderCall
    Resolved --> RenderCall
    NoCompiler --> EngineReady[Engine Ready]
    
    CreateEngine --> RenderCall[Call engine.render]
    
    subgraph RenderProcess[render Method]
        RenderCall --> ValidateFile{File exists and<br/>is .tex?}
        ValidateFile -->|No| RaiseFileError[Raise FileNotFoundError<br/>or ValueError]
        ValidateFile -->|Yes| SetupOutput[Resolve Output Directory<br/>Create if Needed]
        
        SetupOutput --> GetCompiler[_require_compiler Method]
        
        GetCompiler --> CheckCompilerAvail{Compiler<br/>available?}
        CheckCompilerAvail -->|No| RaiseRuntimeError[Raise RuntimeError]
        CheckCompilerAvail -->|Yes| BuildCommand[Build Compiler Command:<br/>-interaction=nonstopmode<br/>-halt-on-error<br/>-output-directory<br/>-jobname]
        
        BuildCommand --> PassLoop[Run 2 Passes of Compilation]
        
        PassLoop --> Pass1[Pass 1/2:<br/>_run_compiler]
        
        subgraph CompilerRun[Compiler Execution]
            Pass1 --> RunSubprocess[Run subprocess.run<br/>with Capture Output]
            RunSubprocess --> CheckReturn{Return<br/>Code = 0?}
            CheckReturn -->|No| LogError[Log Error & Raise RuntimeError]
            CheckReturn -->|Yes| Pass2{Pass<br/>Count < 2?}
        end
        
        Pass2 -->|Yes| RunPass2[Pass 2/2:<br/>_run_compiler]
        RunPass2 --> RunSubprocess
        Pass2 -->|No| CheckPDF{PDF file<br/>created?}
        
        CheckPDF -->|No| RaisePDFError[Raise RuntimeError:<br/>Expected PDF not created]
        CheckPDF -->|Yes| ReturnPDF[Return PDF Path]
    end
    
    ReturnPDF --> Success[Print Success Message]
    RaiseFileError --> CatchError
    RaiseRuntimeError --> CatchError
    RaisePDFError --> CatchError
    
    CatchError{Exception<br/>Caught?} -->|Yes| LogCLIError[Log Error & Print to Console]
    CatchError -->|No| End
    
    Success --> End
    LogCLIError --> End
    ErrorExit1 --> End
    
    End([End])
    
    style Start fill:#e1f5e1
    style End fill:#ffe1e1
    style RenderProcess fill:#e3f2fd
    style CompilerDetection fill:#fff3e0
    style CompilerRun fill:#f3e5f5
    style EngineInit fill:#e8f5e9