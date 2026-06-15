import argparse
import logging
import os
import sys
from pathlib import Path

# Setup paths to ensure modules from other directories can be imported
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.append(str(PROJECT_ROOT / "resume_to_latex"))
sys.path.append(str(PROJECT_ROOT / "jd_to_latex"))

from resume_parser import extract_pdf_data
from txt_resume_to_latex_resume import txt_to_resume_latex
from resume_tailoring_workflow import tailor_resume_from_job_description, DEFAULT_JD_PATH, DEFAULT_OUTPUT_DIR
from latex_engine import LatexEngine

LOGGER = logging.getLogger(__name__)

def run_workflow(
    resume_pdf: str,
    model: str | None = None,
    api_key: str | None = None,
    provider: str | None = None,
    api_base: str | None = None,
):
    """
    Executes the end-to-end resume modification process:
      1. Parses text out of the resume PDF.
      2. Generates a base LaTeX resume.
      3. Tailors the LaTeX resume based on the Job Description.
      4. Compiles the modified LaTeX into a final PDF.
    """
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    if api_base:
        os.environ["DEEPSEEK_API_BASE"] = api_base

    kwargs = {}
    if model:
        kwargs["model"] = model
    if api_key:
        kwargs["api_key"] = api_key

    resume_pdf_path = Path(resume_pdf).expanduser().resolve()
    if not resume_pdf_path.exists():
        raise FileNotFoundError(f"Resume PDF not found: {resume_pdf_path}")
        
    jd_file_path = Path(PROJECT_ROOT / DEFAULT_JD_PATH).resolve()
    if not jd_file_path.exists():
        raise FileNotFoundError(f"Job Description file not found: {jd_file_path}")

    user_name_sanitized = resume_pdf_path.stem.replace(" ", "_")
    output_dir = str(PROJECT_ROOT / DEFAULT_OUTPUT_DIR)

    # --- Step 1: Extract text from PDF ---
    LOGGER.info("Step 1: Extracting text from PDF...")
    extracted_text = extract_pdf_data(str(resume_pdf_path))
    
    # Save the extracted text to a text file because txt_to_resume_latex requires a real path
    temp_txt_path = PROJECT_ROOT / "pdf_to_txt" / f"{resume_pdf_path.stem}.txt"
    temp_txt_path.parent.mkdir(parents=True, exist_ok=True)
    temp_txt_path.write_text(extracted_text, encoding="utf-8")
    LOGGER.info(f"Extracted PDF text saved to file: {temp_txt_path}")
    
    # --- Step 2: Creating base LaTeX file from resume text ---
    LOGGER.info("Step 2: Creating base LaTeX file from resume text...")
    base_latex_file = txt_to_resume_latex(
        txt_path=str(temp_txt_path),
        output_dir=output_dir,
        output_name=f"{user_name_sanitized}_base_resume",
        base_latex_path=str(PROJECT_ROOT / "base_reference" / "resume_reference_1.tex"),
        **kwargs
    )
    LOGGER.info(f"Base LaTeX file generated at: {base_latex_file}")
    
    # --- Step 3: Tailoring resume based on Job Description ---
    LOGGER.info("Step 3: Tailoring resume based on Job Description...")
    result = tailor_resume_from_job_description(
        latex_path=str(base_latex_file),
        jd_path=str(jd_file_path),
        output_dir=output_dir,
        output_name=f"{user_name_sanitized}_tailored_resume",
        **kwargs
    )
    
    decision = result.get("decision")
    LOGGER.info(f"Model decision on tailoring: {decision}")
    
    if decision == "SKIP":
        LOGGER.info("Skipping modification due to insufficient JD alignment. Will use the base generated latex.")
        final_tex_file = base_latex_file
        job_role = str(result.get("job_role", "TargetRole")).replace(" ", "_")
    else:
        final_tex_file = result["output_path"]
        LOGGER.info(f"Tailored LaTeX file saved to: {final_tex_file}")
        job_role = str(result.get("job_role", "TargetRole")).replace(" ", "_")
        
    # --- Step 4: Generating final PDF from the LaTeX file ---
    LOGGER.info("Step 4: Generating final PDF from the LaTeX file...")
    engine = LatexEngine()
    
    # The generated pdf must be stored in the same directory where the latex was generated
    # with the user's name and the job role as the pdf name
    final_pdf_name = f"{user_name_sanitized}_{job_role}"
    
    pdf_path = engine.render(
        tex_file=str(final_tex_file),
        output_name=final_pdf_name,
        output_dir=str(final_tex_file.parent)
    )
    
    LOGGER.info(f"Final PDF successfully generated at: {pdf_path}")
    print(f"\nWorkflow complete! Here is your finalized resume PDF: {pdf_path}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
    
    parser = argparse.ArgumentParser(description="End-to-end Resume Tailoring Workflow")
    parser.add_argument("--resume-pdf", required=True, help="Path to the user's resume PDF")
    parser.add_argument("--model", default=None, help="Model name")
    parser.add_argument("--api-key", default=None, help="API key")
    parser.add_argument("--provider", default=None, help="LLM provider: 'google' or 'deepseek'")
    parser.add_argument("--api-base", default=None, help="Custom API base URL")
    
    args = parser.parse_args()
    
    try:
        run_workflow(
            resume_pdf=args.resume_pdf,
            model=args.model,
            api_key=args.api_key,
            provider=args.provider,
            api_base=args.api_base,
        )
    except Exception as e:
        LOGGER.error(f"Workflow failed: {e}")
        sys.exit(1)
