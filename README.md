# Resume Utilities

This repository currently contains CLI tools for resume parsing, LaTeX generation, tailoring, and compilation:

- `resume_parser.py` uses PyMuPDF to extract PDF data and write it to a `.txt` file.
- `resume_to_latex.py` converts a resume PDF into LaTeX using Gemini.
- `modify_latex_asper_jd.py` tailors an existing resume `.tex` to a job description when alignment with existing expertise is strong.
- `latex_engine.py` compiles an existing `.tex` file into a PDF.

## Prerequisites

- Python 3.10+ recommended
- `pip` for installing Python dependencies
- A LaTeX distribution for PDF generation with `latex_engine.py`

### System dependency for LaTeX compilation

`latex_engine.py` requires a working TeX compiler such as `pdflatex`, `xelatex`, or `lualatex`.

On Windows, install one of the following before running the script:

- MiKTeX
- TeX Live

Example installation with `winget`:

```powershell
winget install --id MiKTeX.MiKTeX --exact --accept-package-agreements --accept-source-agreements
```

If MiKTeX is installed in a standard Windows location, `latex_engine.py` will also try to find it even when `PATH` has not been updated yet.

## Setup

Create and activate a virtual environment if desired:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install Python dependencies:

```powershell
pip install -r requirements.txt
```

## Python dependencies

Install the packages listed in `requirements.txt` before running the PDF conversion scripts.

`resume_parser.py` uses `PyMuPDF` (`fitz`) for local data extraction.

`resume_to_latex.py` requires a Google Gemini API key through `GOOGLE_API_KEY`, `GEMINI_API_KEY`, or the `--api-key` option.

## Usage

### PDF data extractor

Run with a PDF path:

```powershell
python resume_parser.py path\to\resume.pdf
```

Write to a custom output text file:

```powershell
python resume_parser.py path\to\resume.pdf output\resume_data.txt
```

Or run interactively:

```powershell
python resume_parser.py
```

Expected output:

```text
Extracted data saved to C:\path\to\resume.txt
```

### PDF to LaTeX converter

Run with explicit arguments:

```powershell
python resume_to_latex.py path\to\resume.pdf output\resume.tex
```

### LaTeX to PDF compiler

Run with explicit arguments:

```powershell
python latex_engine.py path\to\resume.tex --output-dir output --output-name resume
```

Or run interactively:

```powershell
python latex_engine.py
```

Optional arguments:

- `--output-dir` writes the generated PDF and compiler artifacts to a chosen directory
- `--output-name` sets the output PDF file name without the extension
- `--compiler` selects a specific LaTeX compiler executable

### Job-description-based LaTeX tailoring

Use this to conservatively adapt an existing resume `.tex` file for a specific job description.

Behavior:

- Modifies resume content only when the job description aligns with the candidate's current expertise.
- Keeps edits minimal and focused on skills/experience wording.
- Suggests only quick-learn or adjacent skills (about 4-7 hours to learn from scratch).
- Preserves LaTeX structure and returns an unchanged result when alignment is insufficient.

Run with a job description file:

```powershell
python modify_latex_asper_jd.py --latex-path generated_latex\My_resume.tex --jd-path resume\sample_jd.txt
```

Run with inline job description text:

```powershell
python modify_latex_asper_jd.py --latex-path generated_latex\My_resume.tex --jd-text "Python ML engineer with MLOps, Docker, Kubernetes, CI/CD"
```

Optional arguments:

- `--output-dir` directory to save modified `.tex` file (default: `generated_latex`)
- `--output-name` custom output file name without extension
- `--model` Gemini model name (default: `gemini-2.0-flash`)
- `--api-key` Gemini API key (or set `GOOGLE_API_KEY`/`GEMINI_API_KEY`)

## Behavior

`resume_parser.py` raises an error if:

- No file path is provided
- The file does not exist
- The file is not a `.pdf`
- No extractable data is found in the PDF

`latex_engine.py` raises an error if:

- No file path is provided
- The file does not exist
- The file is not a `.tex`
- No LaTeX compiler is available
- The LaTeX compiler fails to produce a PDF

`resume_to_latex.py` raises an error if:

- No file path is provided
- The file does not exist
- The file is not a `.pdf`
- No Gemini API key is provided
