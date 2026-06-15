flowchart TD
    Start([Start: __main__]) --> Main[main Function]
    
    Main --> InitLogging[Configure logging with INFO level]
    InitLogging --> CheckArgs{pdf_path<br/>argument provided?}
    
    CheckArgs -->|No| PromptPath[Prompt user for PDF path]
    PromptPath --> GetPath[Read path from input]
    CheckArgs -->|Yes| ResolvePath[Call resolve_pdf_path]
    GetPath --> ResolvePath
    
    subgraph PathResolution[Path Resolution & Validation]
        ResolvePath --> PathObj[Convert to absolute Path object]
        PathObj --> CheckExists{File exists?}
        CheckExists -->|No| RaiseFileNotFound[Raise FileNotFoundError]
        CheckExists -->|Yes| CheckSuffix{Has .pdf suffix?}
        CheckSuffix -->|No| RaiseValueError[Raise ValueError]
        CheckSuffix -->|Yes| ReturnPath[Return Path object]
    end
    
    RaiseFileNotFound --> LogMainError
    RaiseValueError --> LogMainError
    
    ReturnPath --> CallExtract[Call extract_pdf_data]
    
    subgraph Extraction[extract_pdf_data Method]
        CallExtract --> ResolvePDFInExtract[Call resolve_pdf_path]
        ResolvePDFInExtract --> InitSections[Initialize sections list]
        InitSections --> OpenPDF[Open PDF via fitz.open]
        
        OpenPDF --> GetMetadata[Extract Metadata: File, Pages, Title, Author, etc.]
        GetMetadata --> AppendInfo[Append Metadata & Info to sections]
        
        AppendInfo --> IteratePages[Iterate through pages: Page 1 to N]
        IteratePages --> PageHeaders[Append Page header, Rotation, Size]
        PageHeaders --> GetLinks[Get page hyperlinks via get_links]
        GetLinks --> AppendLinks[Append found URLs & indices to sections]
        
        AppendLinks --> GetText[Extract plain text via page.get_text]
        GetText --> CleanLines[Split text and collapse whitespace per line]
        CleanLines --> CheckLines{Are there<br/>lines?}
        CheckLines -->|Yes| AppendText[Append cleaned lines to sections]
        CheckLines -->|No| AppendEmpty[Append 'No text extracted' placeholder]
        
        AppendText --> CheckMorePages{More pages?}
        AppendEmpty --> CheckMorePages
        CheckMorePages -->|Yes| IteratePages
        CheckMorePages -->|No| JoinSections[Join sections into single data string]
        
        JoinSections --> CheckData{Is data empty?}
        CheckData -->|Yes| RaiseExtractError[Raise ValueError: No extractable data]
        CheckData -->|No| LogSuccess[Log success and return data]
    end
    
    RaiseExtractError --> LogMainError
    LogSuccess --> CallWrite[Call write_extracted_data]
    
    subgraph Writing[write_extracted_data Method]
        CallWrite --> ResolveOutPath[Resolve absolute output path]
        ResolveOutPath --> CreateDirs[Create parent directories if missing]
        CreateDirs --> WriteFile[Write data string to file in UTF-8]
        WriteFile --> ReturnOutPath[Return output Path object]
    end
    
    ReturnOutPath --> LogOutputSaved[Log output saved filepath]
    LogOutputSaved --> End
    
    LogMainError[Log Error & print traceback] --> End
    
    End([End])
    
    style Start fill:#e1f5e1
    style End fill:#ffe1e1
    style PathResolution fill:#fff3e0
    style Extraction fill:#e3f2fd
    style Writing fill:#f3e5f5
