flowchart TD
    Prompt([SYSTEM_PROMPT constant]) --> Role["Role: Expert LaTeX resume formatter"]
    
    Role --> Instructions["Core Instructions"]
    subgraph Instructions["Core Instructions"]
        I1["1. Use provided LaTeX template structure"]
        I2["2. Read extracted plain text resume details"]
        I3["3. Replace placeholders with actual details"]
        I4["4. Maintain exact LaTeX syntax and commands"]
        I5["5. Escape special characters like &, %, $, #, _, {, }"]
        I6["6. Ensure output compiles without errors"]
    end
    
    Role --> Process["Execution Steps"]
    subgraph Process["Execution Steps"]
        P1["Identify placeholder values in template"]
        P2["Map extracted resume values to placeholder fields"]
        P3["Perform safe in-place replacement"]
    end
    
    Role --> Output["Expected Response Format"]
    subgraph Output["Expected Response Format"]
        O1["Return ONLY ready-to-compile LaTeX code"]
        O2["No conversational preamble or explanation"]
        O3["No markdown fences unless requested"]
    end
    
    style Prompt fill:#e1f5e1
    style Instructions fill:#e3f2fd
    style Process fill:#fff3e0
    style Output fill:#f3e5f5
