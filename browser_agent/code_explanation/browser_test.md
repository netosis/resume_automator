flowchart TD
    Start([Start: __main__]) --> CallLaunch[Call launch_spotify_with_profile]
    
    subgraph BrowserTest[Brave Launch Profile Test]
        CallLaunch --> PredefinePaths[Define list of standard Brave Windows installation paths]
        PredefinePaths --> LoopPaths[Search paths for brave.exe]
        
        LoopPaths --> CheckExists{Found Brave path?}
        CheckExists -->|No| RaiseError[Raise FileNotFoundError: Brave not found]
        CheckExists -->|Yes| ResolveUserData[Resolve local AppData/Brave User Data directory path]
        
        ResolveUserData --> StartPlaywright[Initialize sync_playwright]
        StartPlaywright --> LaunchBrave[Launch Chromium persistent context:<br/>Set Brave path, user data directory,<br/>set profile-directory=Default, headless=False]
        
        LaunchBrave --> NewPage[Open new page tab]
        NewPage --> Navigate[Navigate to https://open.spotify.com]
        Navigate --> WaitTimeout[Keep page open using wait_for_timeout]
        
        WaitTimeout --> CatchInterrupt{KeyboardInterrupt<br/>Ctrl+C?}
        CatchInterrupt -->|Yes| CloseContext[Close persistent context & Playwright]
        CatchInterrupt -->|No/Timeout| CloseContext
    end
    
    CloseContext --> End([End])
    RaiseError --> End
    
    style Start fill:#e1f5e1
    style End fill:#ffe1e1
    style BrowserTest fill:#e3f2fd
