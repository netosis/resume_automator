# accessibility_tree.py - Token-Efficient Web Navigation

## Overview

`accessibility_tree.py` implements token-efficient web navigation strategies specifically designed to reduce LLM token usage. It provides helper utilities for browser management, accessibility tree extraction, and Chrome DevTools Protocol (CDP) integration.

## Key Components Flow

```mermaid
graph TB
    subgraph Setup["Setup Layer"]
        SetupLogging["setup_logging()"]
        LogConfig["Log Configuration"]
    end
    
    subgraph BrowserHelpers["Browser Helpers"]
        FindBrave["find_brave_path()"]
        GetUserData["get_brave_user_data_dir()"]
        AsyncLaunch["async_launch_browser()"]
    end
    
    subgraph AccessibilityOps["Accessibility Operations"]
        GetSnapshot["get_accessibility_snapshot()"]
        BuildTree["_build_ax_tree_recursively()"]
        ExtractNode["_extract_node_data()"]
    end
    
    subgraph ToolClasses["LangChain Tools"]
        BrowserAction["BrowserAction (Pydantic)"]
        AccessibilityMode["AccessibilityMode (Enum)"]
        AccessibilityInput["AccessibilityInput (Pydantic)"]
        TreeTool["AccessibilityTreeTool (BaseTool)"]
    end
    
    Setup --> BrowserHelpers
    BrowserHelpers --> AsyncLaunch
    AsyncLaunch --> AccessibilityOps
    AccessibilityOps --> GetSnapshot
    GetSnapshot --> ToolClasses
    TreeTool --> BrowserAction
    TreeTool --> AccessibilityInput
```

## 5 Token-Efficient Strategies

### Strategy 1: Accessibility Tree Instead of Full DOM

```mermaid
graph LR
    Full["Full DOM<br/>~10,000 tokens"] --> |Extract| Access["Accessibility Tree<br/>~200 tokens"]
    Access --> |Filter| Interactive["Interactive Only<br/>~100 tokens"]
    
    style Full fill:#ff6b6b
    style Access fill:#ffd43b
    style Interactive fill:#51cf66
```

**Why**: Accessibility trees contain only semantically important elements
- Remove boilerplate HTML
- Keep structured information
- Reduce redundancy

### Strategy 2: Lazy Browser Launch

```mermaid
sequenceDiagram
    participant Script
    participant Browser as PersistentBrowserManager
    participant Playwright
    
    Script->>Script: Load configuration
    Browser->>Browser: Not launched yet
    Script->>Script: Initialize agent (no browser startup)
    Browser->>Browser: Still not launched
    Script->>Browser: First tool call
    Browser->>Playwright: Launch browser
    Playwright->>Browser: Return context
    Browser->>Browser: Reuse for all future calls
```

**Benefit**: Browser only starts when needed, saves resources and time

### Strategy 3: CDP (Chrome DevTools Protocol) for Accessibility

```mermaid
graph TD
    Page["Playwright Page"] --> |Modern API| CDP["Chrome DevTools Protocol"]
    CDP --> |Send| Request["Accessibility.getFullAXTree"]
    Request --> |Receive| Tree["AX Tree JSON"]
    Tree --> |Parse| Nodes["Extract Node Data"]
    Nodes --> |Return| Result["Formatted Result"]
    
    style CDP fill:#4c6ef5
    style Request fill:#748ffc
    style Result fill:#a5d8ff
```

**Advantage**: Replaces deprecated `page.accessibility.snapshot()`

### Strategy 4: Profile-Based Browser Context

```mermaid
graph TB
    Config["Environment Config"] --> |BROWSER_TYPE| Select{Which Browser?}
    Select --> |brave| Brave["Brave Browser"]
    Select --> |firefox| Firefox["Firefox Browser"]
    
    Brave --> |Check| BravePath["Find Brave Executable"]
    BravePath --> |Exists| Launch1["Launch with Persistent Context"]
    
    Firefox --> |Check| FFPath["Find Firefox Profile"]
    FFPath --> |Exists| Copy["Copy Profile to Temp"]
    Copy --> |Use| Launch2["Launch Persistent Context"]
    
    Launch1 --> |Maintains| State1["Cookies, History, Settings"]
    Launch2 --> |Maintains| State2["Cookies, History, Settings"]
```

### Strategy 5: Structured Output Formats

**Instead of raw HTML → Structured JSON**

```json
{
  "type": "accessibility_tree",
  "mode": "interactive",
  "nodes": [
    {
      "role": "button",
      "name": "Search",
      "selector": "button[type='submit']",
      "actions": ["click", "focus"]
    },
    {
      "role": "textbox",
      "name": "Search Query",
      "selector": "input[type='text']",
      "actions": ["type", "clear"]
    }
  ]
}
```

## Accessibility Tree Construction Flow

```mermaid
graph TD
    A["get_accessibility_snapshot()"] --> B["Send CDP command:<br/>Accessibility.getFullAXTree"]
    B --> C["Receive nodes array"]
    C --> D["Build node map"]
    D --> E["Find root node"]
    E --> F["_build_ax_tree_recursively()"]
    F --> |For each child| G["_extract_node_data()"]
    G --> H["Filter by role<br/>textbox, button, link, etc"]
    H --> I["Extract attributes<br/>name, value, disabled"]
    I --> J["Build child tree recursively"]
    J --> K["Return hierarchy"]
    K --> L["Format as JSON/text"]
    L --> M["Return to LLM"]
```

## Browser Launch Decision Tree

```mermaid
graph TD
    A["async_launch_browser()"] --> B{USE_PERSISTENT?}
    
    B -->|true| C{BROWSER_TYPE?}
    B -->|false| D{BROWSER_TYPE?}
    
    C -->|firefox| E["Find Firefox Profile"]
    C -->|brave| F["Find Brave Executable"]
    
    D -->|firefox| G["Launch temp Firefox"]
    D -->|brave| H["Launch temp Brave"]
    
    E --> |Profile found| I["Copy to temp dir"]
    E --> |Not found| J["Use fallback Chromium"]
    
    F --> |Found| K["Launch with user data dir"]
    F --> |Not found| L["Fallback to Playwright Chromium"]
    
    I --> M["Return persistent context"]
    J --> M
    K --> M
    L --> M
    G --> N["Return temp context"]
    H --> N
```

## Logging Architecture

```mermaid
graph TB
    A["setup_logging()"] --> B["Create Logger"]
    B --> C{Handler Configuration}
    C --> |Console| D["StreamHandler"]
    C --> |File| E["FileHandler"]
    
    D --> F["Format: timestamp - name - level - file:line - message"]
    E --> F
    
    G["Debug Code"] --> H["logger.info(), logger.error(), etc"]
    H --> D
    H --> E
    
    style F fill:#c3fae8
    style A fill:#b3e5fc
```

## Pydantic Models for Type Safety

```python
# BrowserAction: Represents a browser action
class BrowserAction(BaseModel):
    action: str  # "click", "type", "scroll", etc
    selector: str  # CSS selector
    value: Optional[str]  # For type action

# AccessibilityMode: Enum for filtering level
class AccessibilityMode(str, Enum):
    INTERACTIVE = "interactive"  # Only clickable elements
    ALL = "all"  # Full tree

# AccessibilityInput: Tool input validation
class AccessibilityInput(BaseModel):
    mode: AccessibilityMode

# AccessibilityTreeTool: LangChain BaseTool implementation
class AccessibilityTreeTool(BaseTool):
    name: str = "accessibility_tree"
    description: str = "Get page structure for navigation"
```

## Code Organization

```
accessibility_tree.py
├── Imports (logging, asyncio, Playwright, Pydantic)
├── setup_logging()
├── find_brave_path()
├── get_brave_user_data_dir()
├── async_launch_browser()
│   ├── Firefox persistent context logic
│   ├── Firefox non-persistent logic
│   ├── Brave persistent context logic
│   └── Brave non-persistent logic
├── get_accessibility_snapshot()
│   ├── CDP command execution
│   ├── Node map building
│   └── Tree hierarchy construction
├── _build_ax_tree_recursively()
│   └── Recursive tree building
├── _extract_node_data()
│   ├── Filter by role
│   ├── Extract attributes
│   └── Collect actions
├── BrowserAction (Pydantic Model)
├── AccessibilityMode (Enum)
├── AccessibilityInput (Pydantic Model)
└── AccessibilityTreeTool (BaseTool)
```

## Token Reduction Examples

### Example 1: Button Discovery

**Without optimization** (Full DOM):
```html
<div class="navbar">
  <nav class="nav-links">
    <div class="nav-item">
      <button class="btn-primary" onclick="search()">Search</button>
    </div>
  </nav>
</div>
<!-- ... 50 more lines ... -->
Tokens: ~500
```

**With optimization** (Accessibility Tree):
```json
{
  "role": "button",
  "name": "Search",
  "selector": "button.btn-primary"
}
Tokens: ~20
```

**Savings: 96%** ✅

### Example 2: Form Field Discovery

**Without optimization**:
- Full form HTML with all styling, nested divs
- ~2000 tokens

**With optimization**:
```json
{
  "fields": [
    {"role": "textbox", "name": "Email", "selector": "input[name='email']"},
    {"role": "textbox", "name": "Password", "selector": "input[type='password']"},
    {"role": "button", "name": "Login", "selector": "button[type='submit']"}
  ]
}
```
- ~100 tokens

**Savings: 95%** ✅

## Reasoning Behind Design Choices

1. **CDP Integration**: Most reliable way to get accessibility tree in modern Playwright
2. **Lazy Initialization**: Don't launch browser until first navigation tool call
3. **Profile Copying**: Allows persistent state without leaving browser open
4. **Pydantic Models**: Type validation for tool inputs, reduces parsing errors
5. **Structured Output**: Consistent format for LLM parsing
6. **Multiple Modes**: Interactive mode for UI automation, All mode for comprehensive analysis
7. **Graceful Fallbacks**: Works even if Brave/Firefox not found

## Performance Considerations

| Operation | Time | Token Impact |
|-----------|------|--------------|
| Browser launch | 2-5s | N/A (one-time) |
| Get accessibility snapshot | <1s | 100-300 tokens |
| Get full page text | <1s | 500-3000 tokens |
| Build tree hierarchy | <1s | Included in snapshot |

## Error Recovery

```mermaid
graph TD
    A["CDP command fails"] --> B{Can fallback?}
    B -->|Yes| C["Fallback to text extraction"]
    B -->|No| D["Return empty result"]
    C --> E["Return to LLM"]
    D --> E
    
    F["Browser launch fails"] --> G{"Browser type?"}
    G -->|Brave| H["Fallback to Chromium"]
    G -->|Firefox| I["Fallback to Chromium"]
    H --> J["Launch succeeded"]
    I --> J
```
