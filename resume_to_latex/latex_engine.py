import argparse
import logging
import subprocess
import shutil
from pathlib import Path


LOGGER = logging.getLogger(__name__)


def _prompt_if_missing(value, message):
    if value is not None:
        return value

    response = input(message).strip()
    return response or None


class LatexEngine:
    """A LaTeX engine that compiles .tex files to PDF."""

    def __init__(self, latex_compiler=None):
        """
        Initialize the LaTeX engine.

        Args:
            latex_compiler: The LaTeX compiler to use. If omitted, auto-detects
                one from PATH.
        """
        self.compiler = latex_compiler or self._detect_compiler()
        LOGGER.debug("Initialized LatexEngine with compiler setting: %s", self.compiler)

    @staticmethod
    def _candidate_compiler_paths(compiler_name):
        executable = compiler_name if compiler_name.endswith('.exe') else f"{compiler_name}.exe"
        windows_roots = [
            Path.home() / 'AppData' / 'Local' / 'Programs' / 'MiKTeX' / 'miktex' / 'bin' / 'x64',
            Path.home() / 'AppData' / 'Local' / 'Programs' / 'MiKTeX' / 'miktex' / 'bin',
            Path('C:/Program Files/MiKTeX/miktex/bin/x64'),
            Path('C:/Program Files/MiKTeX/miktex/bin'),
            Path('C:/Program Files (x86)/MiKTeX/miktex/bin/x64'),
            Path('C:/Program Files (x86)/MiKTeX/miktex/bin'),
        ]
        return [root / executable for root in windows_roots]

    @classmethod
    def _find_compiler_executable(cls, compiler_name):
        resolved = shutil.which(compiler_name)
        if resolved:
            LOGGER.debug("Resolved compiler %s from PATH: %s", compiler_name, resolved)
            return resolved

        for candidate in cls._candidate_compiler_paths(compiler_name):
            if candidate.exists():
                LOGGER.debug("Resolved compiler %s from fallback path: %s", compiler_name, candidate)
                return str(candidate)

        LOGGER.debug("Could not resolve compiler: %s", compiler_name)
        return None

    @classmethod
    def _detect_compiler(cls):
        for compiler in ('pdflatex', 'xelatex', 'lualatex'):
            resolved = cls._find_compiler_executable(compiler)
            if resolved:
                return resolved
        return None

    def _require_compiler(self):
        if self.compiler:
            resolved = self._find_compiler_executable(self.compiler)
            if resolved:
                LOGGER.info("Using LaTeX compiler: %s", resolved)
                return resolved
            raise RuntimeError(
                f"LaTeX compiler '{self.compiler}' is not available on PATH. "
                "Install MiKTeX or TeX Live, or configure latex_compiler to a working engine."
            )

        raise RuntimeError(
            "No LaTeX compiler was detected on PATH. Install MiKTeX or TeX Live so "
            "pdflatex, xelatex, or lualatex is available."
        )

    @staticmethod
    def _run_compiler(command, working_directory):
        LOGGER.info("Running compiler in %s: %s", working_directory, command[0])
        result = subprocess.run(
            command,
            cwd=working_directory,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            details = (result.stdout or '') + (result.stderr or '')
            LOGGER.error("LaTeX compiler failed with exit code %s", result.returncode)
            raise RuntimeError(details.strip() or 'LaTeX compiler returned a non-zero exit code.')
        LOGGER.debug("LaTeX compiler completed successfully")
    
    def render(self, tex_file, output_name=None, output_dir=None):
        """
        Render a LaTeX file to PDF.
        
        Args:
            tex_file: Path to the .tex file
            output_name: Name for the output PDF (without extension)
            output_dir: Directory to save the PDF (default: same as input)
        
        Returns:
            Path to the generated PDF file
        
        Raises:
            FileNotFoundError: If the .tex file doesn't exist
            subprocess.CalledProcessError: If compilation fails
        """
        tex_path = Path(tex_file).expanduser().resolve()
        LOGGER.info("Starting LaTeX render for %s", tex_path)
        
        if not tex_path.exists():
            raise FileNotFoundError(f"LaTeX file not found: {tex_file}")
        
        if tex_path.suffix.lower() != '.tex':
            raise ValueError(f"File must be a .tex file: {tex_file}")
        
        output_dir = tex_path.parent if output_dir is None else Path(output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        output_name = output_name or tex_path.stem
        LOGGER.debug("Resolved output directory=%s output_name=%s", output_dir, output_name)
        compiler = self._require_compiler()

        command = [
            compiler,
            '-interaction=nonstopmode',
            '-halt-on-error',
            f'-output-directory={output_dir}',
            f'-jobname={output_name}',
            tex_path.name,
        ]

        for pass_index in range(2):
            LOGGER.debug("Running LaTeX pass %s/2", pass_index + 1)
            self._run_compiler(command, tex_path.parent)

        try:
            pdf_path = output_dir / f"{output_name}.pdf"
            if not pdf_path.exists():
                raise RuntimeError(f"Expected PDF was not created: {pdf_path}")

            LOGGER.info("Successfully compiled PDF: %s", pdf_path)
            # print(f"Successfully compiled: {pdf_path}")
            return str(pdf_path)

        except Exception as e:
            LOGGER.error(f"LaTeX compilation workflow failed: {e}")
            raise RuntimeError(f"LaTeX compilation failed: {e}") from e


def main():
    """Main function to compile a LaTeX file from user input."""
    parser = argparse.ArgumentParser(description="Compile a LaTeX .tex file to PDF")
    parser.add_argument("tex_file", nargs="?", help="Path to the LaTeX .tex file")
    parser.add_argument("--output-dir", dest="output_dir", help="Directory for generated files")
    parser.add_argument("--output-name", dest="output_name", help="Output PDF name without extension")
    parser.add_argument("--compiler", dest="compiler", help="LaTeX compiler to use, such as pdflatex or xelatex")
    parser.add_argument("--log-level", default="INFO", help="Logging level: DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format='%(levelname)s:%(name)s:%(message)s',
    )

    tex_file = args.tex_file or input("Enter the path to the LaTeX file: ").strip()

    if not tex_file:
        print("Error: No file path provided.")
        return

    output_dir = _prompt_if_missing(args.output_dir, "Enter the output directory (press Enter for same as input): ")
    output_name = _prompt_if_missing(args.output_name, "Enter the output PDF name without extension (press Enter for default): ")

    engine = LatexEngine(latex_compiler=args.compiler)
    try:
        pdf_path = engine.render(tex_file, output_name=output_name, output_dir=output_dir)
        print(f"Successfully compiled: {pdf_path}")
    except Exception as e:
        LOGGER.error("CLI execution failed: %s", e)
        print(f"Error: {e}")


if __name__ == "__main__":
    main()

