# Resume Automator & Job Application Agent

This repository provides an automated pipeline for parsing resumes, converting them to LaTeX, tailoring them to specific job descriptions, compiling them back to PDF, and executing browser-based job applications.

---

## Table of Contents
1. [Project Structure](#project-structure)
2. [Key Features](#key-features)
3. [Prerequisites](#prerequisites)
4. [Setup & Installation](#setup--installation)
5. [Configuration](#configuration)
6. [Usage Guide](#usage-guide)
   - [Unified End-to-End Workflow](#unified-end-to-end-workflow)
   - [Individual Sub-Components](#individual-sub-components)
   - [Browser Automation Agent](#browser-automation-agent)
7. [Behavior & Error Handling](#behavior--error-handling)
8. [Visualizing Code Explanations](#visualizing-code-explanations)

---

## Project Structure

The project is structured into three main modules:

```text
resume_automator/
├── main.py                          # Unified end-to-end workflow entrypoint
├── requirements.txt                 # Python dependencies
├── resume_to_latex/                 # PDF extraction and LaTeX generation
│   ├── resume_parser.py             # Parses PDF resumes locally using PyMuPDF
│   ├── txt_resume_to_latex_resume.py# Converts plain text resumes to LaTeX using LLMs
│   ├── txt_to_latex_system_prompt.py# System prompts for base LaTeX generation
│   └── latex_engine.py              # Compiles LaTeX (.tex) files to PDF
├── jd_to_latex/                     # Job-description-based tailoring
│   ├── resume_tailoring_workflow.py # Core logic for tailoring decision and edits
│   ├── modify_latex_asper_jd.py     # CLI wrapper for the tailoring workflow
│   └── jd_latex_modifier_system_prompt.py # System prompts for planning and section editing
├── browser_agent/                   # Browser automation and job application agents
│   ├── naukri_agent_demo.py         # Demonstration script for naukri.com job searching/applying
│   ├── indeed_agent_demo.py         # Demonstration script for indeed.com job searching/applying
│   ├── third_party_apply.py         # Automated job application form-filling script
│   ├── browser_tools.py             # Playwright browser integration and general tools
│   ├── naukri_tools.py              # Naukri-specific tools and question handling
│   ├── indeed_tools.py              # Indeed-specific tools and search handling
│   └── accessibility_tree.py        # Web page accessibility tree parsing and pruning
├── base_reference/                  # Reference LaTeX templates
│   └── resume_reference_1.tex       # Standard LaTeX resume template
├── pdf_to_txt/                      # Output directory for parsed PDF text
├── generated_latex/                 # Output directory for generated LaTeX and final PDFs
└── logs/                            # Output directory for token logs and execution history
```

---

## Key Features

- **Local PDF Parsing**: Extracts clean text from PDF resumes using PyMuPDF in [resume_parser.py](file:///D:/LLM%20Projects/resume_automator/resume_to_latex/resume_parser.py).
- **Base LaTeX Reformatting**: Converts plain text resumes into structured, professional LaTeX documents using a reference template in [txt_resume_to_latex_resume.py](file:///D:/LLM%20Projects/resume_automator/resume_to_latex/txt_resume_to_latex_resume.py).
- **Intelligent Tailoring**: Evaluates a LaTeX resume against a job description in [resume_tailoring_workflow.py](file:///D:/LLM%20Projects/resume_automator/jd_to_latex/resume_tailoring_workflow.py) to make a `MODIFY` or `SKIP` decision. When modifying, it targets specific sections (like Experience, Summary, or Skills) using LLMs, suggesting quick-learn skills (4-7 hour study time) while preserving the original LaTeX structure.
- **LaTeX Compilation**: Automatically resolves local TeX compilers (e.g., `pdflatex`, `xelatex`, `lualatex`) to build PDFs in [latex_engine.py](file:///D:/LLM%20Projects/resume_automator/resume_to_latex/latex_engine.py).
- **Autonomous Job Application**: A browser agent in [browser_agent/](file:///D:/LLM%20Projects/resume_automator/browser_agent) powered by LangChain and Playwright that opens websites, searches for job roles, extracts job descriptions, and automatically uploads resumes and fills out application forms.

---

## Prerequisites

### 1. Python 3.10+
Ensure Python is installed on your system.

### 2. LaTeX Compiler (For PDF Generation)
A working TeX distribution is required for compilation.
- **Windows**: Install MiKTeX or TeX Live. You can install MiKTeX via `winget`:
  ```powershell
  winget install --id MiKTeX.MiKTeX --exact --accept-package-agreements --accept-source-agreements
  ```
  *Note: The compiler will be auto-detected if installed in standard locations.*

### 3. Playwright Browsers (For Browser Agent)
The browser agent runs Playwright. By default, it supports **Brave** and **Firefox**. Ensure you have Brave or Firefox installed on your system, or let Playwright download its bundled browsers.

---

## Setup & Installation

1. Create and activate a virtual environment:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

2. Install python dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

3. Install Playwright browser binaries:
   ```powershell
   playwright install
   ```

---

## Configuration

Configure the providers in a `.env` file at the root of the project:

```env
# --- LLM CONFIGURATION ---
# Set to 'google', 'deepseek', or 'local'
LLM_PROVIDER=google

# For Google Gemini:
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash

# For DeepSeek:
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# For Local Models (Ollama, LM Studio, vLLM, etc.):
LOCAL_API_BASE=http://localhost:11434/v1
LOCAL_MODEL=qwen2.5
LOCAL_API_KEY=local

# --- BROWSER CONFIGURATION ---
# Set to 'brave' or 'firefox'
BROWSER_TYPE=brave
# Enable/disable incognito mode
BROWSER_INCOGNITO=true
```

To verify your configuration, you can run the test scripts:
- Gemini: `python gemini_test.py`
- DeepSeek: `python deepseek_test.py`

---

## Usage Guide

### Unified End-to-End Workflow

The [main.py](file:///D:/LLM%20Projects/resume_automator/main.py) script automates the complete pipeline. It reads a raw resume PDF, converts it to base LaTeX, tailors it against a job description, and compiles it into a final PDF.

```powershell
python main.py --resume-pdf path/to/resume.pdf
```

Optional Arguments:
- `--provider`: LLM provider (`google`, `deepseek`, or `local`)
- `--model`: Specific model name (e.g., `gemini-2.5-flash`, `qwen2.5`)
- `--api-key`: API key for the chosen provider (or `local` if bypassed)
- `--api-base`: Custom base URL (useful for local servers or DeepSeek)

Output files are stored under `generated_latex/<Company_Name>/<Job_Role>/`.

---

### Individual Sub-Components

If you want to run stages of the pipeline individually, use the following commands:

#### 1. PDF Resume Parser
Extracts plain text from a resume PDF:
```powershell
python resume_to_latex/resume_parser.py path/to/resume.pdf [output/resume.txt]
```

#### 2. Text to LaTeX Converter
Converts extracted text to a LaTeX document based on a reference template:
```powershell
python resume_to_latex/txt_resume_to_latex_resume.py --txt_path pdf_to_txt/resume.txt --output-dir generated_latex --output-name base_resume
```

#### 3. Job Description Tailoring
Tailors an existing LaTeX resume (`.tex`) to a job description file or raw text:
```powershell
# Tailoring using a job description text file:
python jd_to_latex/modify_latex_asper_jd.py --latex-path generated_latex/base_resume.tex --jd-path jd_to_latex/job_description.txt

# Tailoring using raw text description:
python jd_to_latex/modify_latex_asper_jd.py --latex-path generated_latex/base_resume.tex --jd-text "Python Developer with experience in ML and FastAPI"
```

#### 4. LaTeX Compiler
Compiles a LaTeX file into a PDF:
```powershell
python resume_to_latex/latex_engine.py generated_latex/tailored_resume.tex --output-dir output_pdf --output-name final_resume
```

---

### Browser Automation Agent

The browser agent operates in the [browser_agent/](file:///D:/LLM%20Projects/resume_automator/browser_agent) directory.

#### 1. Browser Agent Job Search Demos
Demonstrates the agent opening a browser, searching for job listings, clicking listings, reading detail pages, and submitting applications.

- **Naukri Job Search Demo**:
```powershell
python browser_agent/naukri_agent_demo.py
```

- **Indeed Job Search Demo**:
```powershell
python browser_agent/indeed_agent_demo.py
```
*You will be prompted to enter a custom query or press enter to run the default workflow.*

#### 2. Automated Job Form Applier
Automatically navigates to a job application page (or local mock form), extracts inputs, uploads a resume, fills out information, and prepares to submit:
```powershell
# Run against a specific application URL:
python browser_agent/third_party_apply.py https://example-job-portal.com/apply/123

# Run against the local mock form for testing:
python browser_agent/third_party_apply.py
```

---

## Behavior & Error Handling

### PDF Extraction (`resume_parser.py`)
Fails with errors if:
- No input path is provided or the file is missing.
- The file is not a `.pdf`.
- No extractable text is found in the PDF.

### LaTeX Generation & Tailoring
- Plans section modifications dynamically and only updates sections where modification is necessary.
- If the job description does not align well with the resume profile, it outputs a `SKIP` decision and uses the base resume.
- Details of LLM input and output token consumption are aggregated and saved into the `logs/` folder.

### LaTeX Compilation (`latex_engine.py`)
Fails with errors if:
- No LaTeX compiler is found on the system.
- Compilation fails due to LaTeX syntax errors (returns stdout/stderr logs from compiler).

---

## Visualizing Code Explanations

Detailed explanations of the internal module workflows are documented in Markdown using Mermaid flowcharts in `resume_to_latex/code_explaination/` (e.g., [latex_engine.md](file:///D:/LLM%20Projects/resume_automator/resume_to_latex/code_explaination/latex_engine.md)).

You can render and preview these flowcharts using:
- **VS Code Extensions**: *Markdown Preview Mermaid Support* or *Mermaid Chart*.
- **Web Browsers**: Uploading/opening the files on GitHub or copying the block into the [Mermaid Live Editor](https://mermaid.live).
