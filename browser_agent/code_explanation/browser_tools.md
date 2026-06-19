flowchart TD
    subgraph BrowserManager[PersistentBrowserManager Singleton]
        GetInstance[get_instance Method] --> CheckInstance{Instance exists?}
        CheckInstance -->|No| CreateInstance[Create manager instance]
        CheckInstance -->|Yes| ReturnInstance[Return existing manager]
        CreateInstance --> ReturnInstance
        
        GetPage[get_page Method] --> CheckPage{Active page exists<br/>& not closed?}
        CheckPage -->|Yes| ReturnPage[Return active page]
        CheckPage -->|No| CheckPlaywright{Playwright running?}
        
        CheckPlaywright -->|No| StartPlaywright[Start sync_playwright]
        CheckPlaywright -->|Yes| CheckContext{Context exists?}
        StartPlaywright --> CheckContext
        
        CheckContext -->|No| CheckIncognito{Incognito Mode?}
        CheckContext -->|Yes| CreateNewPage[Create new page under context]
        
        CheckIncognito -->|Yes| LaunchIncognito[Launch Brave/Firefox in incognito/non-persistent mode]
        CheckIncognito -->|No| LaunchPersistent[Launch persistent browser context using profile directory]
        
        LaunchIncognito --> CreateNewPage
        LaunchPersistent --> CreateNewPage
        CreateNewPage --> ReturnPage
    end

    subgraph LangChainTools[LangChain Browser Tools Library]
        ToolCall[Tool Request from LLM / Script] --> GetPageObj[Call manager.get_page]
        
        GetPageObj --> ToolSelect{Tool Type?}
        
        ToolSelect -->|open_website| ToolOpen[Navigate to URL<br/>Wait for dynamic content<br/>Return accessibility snapshot]
        ToolSelect -->|get_page_text| ToolText[Extract and clean page text content]
        ToolSelect -->|click_on_element| ToolClick[Locate element and perform click]
        ToolSelect -->|input_text_into_element| ToolInput[Type text into selector/field]
        ToolSelect -->|scroll_page| ToolScroll[Scroll page up, down, or home]
        ToolSelect -->|get_form_fields| ToolForm[Scan and return form fields & details]
        ToolSelect -->|select_dropdown_option| ToolSelectOpt[Select option in dropdown selection list]
        ToolSelect -->|set_checkbox_state| ToolCheck[Toggle checkbox check/uncheck status]
        ToolSelect -->|upload_file| ToolUpload[Upload local file to file selector element]
        ToolSelect -->|click_apply_button| ToolApply[Scan page for Apply/Apply Now text, click, and track new tabs]
        ToolSelect -->|close_browser_session| ToolClose[Close page, context, and browser session]
    end
    
    ReturnPage --> ToolOpen
    ReturnPage --> ToolText
    ReturnPage --> ToolClick
    ReturnPage --> ToolInput
    ReturnPage --> ToolScroll
    ReturnPage --> ToolForm
    ReturnPage --> ToolSelectOpt
    ReturnPage --> ToolCheck
    ReturnPage --> ToolUpload
    ReturnPage --> ToolApply
    ReturnPage --> ToolClose
    
    style BrowserManager fill:#e3f2fd
    style LangChainTools fill:#fff3e0
