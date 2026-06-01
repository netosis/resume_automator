import argparse
import logging
import os
import sys
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from resume_to_latex.txt_to_latex_system_prompt import SYSTEM_PROMPT


LOGGER = logging.getLogger(__name__)


def load_env_file(env_path: str = ".env") -> None:
    path = Path(env_path).expanduser().resolve()
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_api_key(api_key: str | None = None) -> str:
    if api_key:
        return api_key

    # Load optional .env values before reading process environment variables.
    load_env_file()

    env_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if env_api_key:
        return env_api_key

    raise ValueError(
        "Missing API key. Pass --api-key or set GOOGLE_API_KEY (or GEMINI_API_KEY)."
    )


def resolve_txt_path(txt_path: str) -> Path:
    path = Path(txt_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input text file not found: {path}")
    if path.suffix.lower() != ".txt":
        raise ValueError(f"Expected a .txt file, got: {path.name}")
    return path


def resolve_latex_template_path(template_path: str) -> Path:
    path = Path(template_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Base LaTeX template not found: {path}")
    if path.suffix.lower() != ".tex":
        raise ValueError(f"Expected a .tex template file, got: {path.name}")
    return path


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 2:
            cleaned = "\n".join(lines[1:-1]).strip()
    return cleaned


def get_token_usage(response: object) -> tuple[int | None, int | None]:
    usage_metadata = getattr(response, "usage_metadata", None) or {}
    if isinstance(usage_metadata, dict):
        input_tokens = usage_metadata.get("input_tokens")
        output_tokens = usage_metadata.get("output_tokens")
        if input_tokens is not None or output_tokens is not None:
            return input_tokens, output_tokens

    response_metadata = getattr(response, "response_metadata", None) or {}
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage") or {}
        if isinstance(token_usage, dict):
            input_tokens = token_usage.get("prompt_token_count")
            output_tokens = token_usage.get("candidates_token_count")
            if input_tokens is not None or output_tokens is not None:
                return input_tokens, output_tokens

    return None, None


def txt_to_resume_latex(
    txt_path: str,
    output_dir: str = "generated_latex",
    output_name: str | None = None,
    base_latex_path: str = "base_reference/resume_reference_1.tex",
    model: str = "gemini-2.0-flash",
    api_key: str | None = None,
) -> Path:
    """Convert resume content from a .txt file into a compiled-style LaTeX resume template."""
    input_path = resolve_txt_path(txt_path)
    template_path = resolve_latex_template_path(base_latex_path)
    resume_text = input_path.read_text(encoding="utf-8", errors="replace").strip()
    base_template = template_path.read_text(encoding="utf-8", errors="replace").strip()

    if not resume_text:
        raise ValueError(f"Input text file is empty: {input_path}")
    if not base_template:
        raise ValueError(f"Base LaTeX template file is empty: {template_path}")

    resolved_api_key = resolve_api_key(api_key)
    llm = ChatGoogleGenerativeAI(model=model, google_api_key=resolved_api_key)

    prompt = (
        "Use the provided base LaTeX resume template as the structure to fill with the resume data. "
        "Replace template/default values with relevant values from the resume text while preserving LaTeX syntax and formatting.\n\n"
        "Base LaTeX template:\n"
        f"{base_template}\n\n"
        "Resume text input:\n"
        f"{resume_text}"
    )

    try:
        system_chars = len(SYSTEM_PROMPT)
        user_chars = len(prompt)
        total_chars = system_chars + user_chars
        estimated_tokens = total_chars // 4
        LOGGER.info(
            "Prompt sizes: system=%d chars, user=%d chars, total=%d chars (~%d estimated tokens)",
            system_chars, user_chars, total_chars, estimated_tokens,
        )
        if estimated_tokens > 8000:
            LOGGER.warning(
                "Prompt is large (~%d estimated tokens). Base template=%d chars, resume text=%d chars.",
                estimated_tokens, len(base_template), len(resume_text),
            )

        LOGGER.info(f"Invoking {model} to convert txt resume to Base LaTeX...")
        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        
        input_tokens, output_tokens = get_token_usage(response)
        if input_tokens is not None or output_tokens is not None:
            LOGGER.info("Token usage - input tokens: %s, output tokens: %s", input_tokens, output_tokens)
        else:
            LOGGER.info("Token usage metadata was not returned by the model response.")

        latex_code = strip_code_fences(str(response.content))

        target_dir = Path(output_dir).expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        file_name = output_name or input_path.stem
        output_path = target_dir / f"{file_name}.tex"
        output_path.write_text(latex_code, encoding="utf-8")

        LOGGER.info(f"LaTeX code saved successfully to {output_path}")
        return output_path

    except Exception as e:
        LOGGER.error(f"Failed to generate base LaTeX resume from txt: {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    parser = argparse.ArgumentParser(description="Convert a TXT resume to LaTeX")
    parser.add_argument("--txt_path", help="Path to the input .txt resume file")
    parser.add_argument("--output-dir", default="generated_latex", help="Directory to save generated .tex")
    parser.add_argument("--output-name", default=None, help="Output file name without extension")
    parser.add_argument(
        "--base-latex-path",
        default="base_reference/resume_reference_1.tex",
        help="Path to the base .tex resume template used as reference",
    )
    parser.add_argument("--model", default="gemini-2.0-flash", help="Gemini model name")
    parser.add_argument("--api-key", dest="api_key", default=None, help="Google/Gemini API key")
    args = parser.parse_args()

    try:
        txt_to_resume_latex(
            txt_path=args.txt_path,
            output_dir=args.output_dir,
            output_name=args.output_name,
            base_latex_path=args.base_latex_path,
            model=args.model,
            api_key=args.api_key,
        )
    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)
