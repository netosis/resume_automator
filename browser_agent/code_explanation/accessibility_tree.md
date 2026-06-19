flowchart TD
    Start([Start: AccessibilityTree instance]) --> EnsureBrowser[Call _ensure_browser]
    
    subgraph BrowserSetup[Browser Lifecycle Setup]
        EnsureBrowser --> CheckBrowser{Browser active?}
        CheckBrowser -->|Yes| LaunchComplete[Ready]
        CheckBrowser -->|No| FindBrave[Search candidate paths for Brave browser]
        FindBrave --> FindUserDir[Resolve Brave user data directory]
        FindUserDir --> LaunchPlaywright[Start Playwright & launch persistent browser context]
        LaunchPlaywright --> LaunchComplete
    end
    
    LaunchComplete --> Action{Method called?}
    
    Action -->|_run / _arun| OpenURL[Load target URL in page]
    OpenURL --> Settle[Wait for page content to load & settle]
    Settle --> CallAXSnapshot[Call get_accessibility_snapshot]
    
    subgraph CDP[CDP AX Tree Capture]
        CallAXSnapshot --> CDPSession[Establish CDP Session with Page]
        CDPSession --> FullTree[Execute Accessibility.getFullAXTree command]
        FullTree --> BuildMap[Construct nodeId-to-node mapping dictionary]
        BuildMap --> BuildHierarchy[Recursively build hierarchical tree structure]
        BuildHierarchy --> ReturnSnapshot[Return hierarchy starting at RootWebArea]
    end
    
    ReturnSnapshot --> PruneCall[Call _prune_tree with selected mode]
    
    subgraph Pruning[Tree Filtering & Pruning]
        PruneCall --> CheckNode{Depth > 25?}
        CheckNode -->|Yes| SkipNode[Return empty list]
        CheckNode -->|No| FilterMode{Mode?}
        
        FilterMode -->|interactive| FilterInteractive[Keep buttons, inputs, links, dropdowns]
        FilterMode -->|reading| FilterReading[Keep headings, paragraphs, document roles]
        FilterMode -->|full| FilterAll[Keep all nodes]
        
        FilterInteractive --> KeepNode
        FilterReading --> KeepNode
        FilterAll --> KeepNode
        
        KeepNode[Compact node fields: role, name, properties] --> ProcessChildren[Recursively prune children and flatten list]
        ProcessChildren --> ReturnPrunedList[Return pruned nodes list]
    end
    
    ReturnPrunedList --> SaveJSON[Write results to accessibility_tree.json]
    SaveJSON --> OutputFormatted[Return JSON formatted string]
    
    Action -->|find_element_by_name| SearchNodes[Load/get current accessibility tree]
    SearchNodes --> SearchHierarchy[Recursively filter nodes matching element name substring]
    SearchHierarchy --> ReturnMatches[Return matching nodes list]
    
    Action -->|cleanup| CloseBrowser[Close Playwright contexts & browser]
    
    style CDP fill:#e3f2fd
    style BrowserSetup fill:#e8f5e9
    style Pruning fill:#fff3e0
