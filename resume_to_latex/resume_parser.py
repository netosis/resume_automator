import argparse
import logging
from pathlib import Path

import fitz

LOGGER = logging.getLogger(__name__)

def resolve_pdf_path(pdf_path: str) -> Path:
	path = Path(pdf_path).expanduser().resolve()

	if not path.exists():
		raise FileNotFoundError(f"PDF file not found: {path}")
	if path.suffix.lower() != ".pdf":
		raise ValueError(f"Expected a .pdf file, got: {path.name}")

	return path


def extract_pdf_data(pdf_path: str) -> str:
	try:
		path = resolve_pdf_path(pdf_path)
		LOGGER.debug(f"Opening PDF file: {path}")

		sections: list[str] = []
		with fitz.open(path) as doc:
			metadata = doc.metadata or {}
			sections.append("=== DOCUMENT INFO ===")
			sections.append(f"File: {path.name}")
			sections.append(f"Pages: {doc.page_count}")
			for key in sorted(metadata.keys()):
				value = metadata.get(key)
				if value:
					sections.append(f"{key}: {value}")

			for index, page in enumerate(doc, start=1):
				sections.append("")
				sections.append(f"=== PAGE {index} ===")
				sections.append(f"Rotation: {page.rotation}")
				sections.append(f"Size: {page.rect.width:.2f} x {page.rect.height:.2f}")

				links = page.get_links() or []
				sections.append(f"Links found: {len(links)}")
				for link_index, link in enumerate(links, start=1):
					uri = link.get("uri") or ""
					if uri:
						sections.append(f"Link {link_index}: {uri}")

				text = page.get_text("text") or ""
				clean_lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
				sections.append("Text:")
				if clean_lines:
					sections.extend(clean_lines)
				else:
					sections.append("[No text extracted from this page]")

		data = "\n".join(sections).strip()
		if not data:
			raise ValueError("No extractable data was found in the PDF.")

		LOGGER.info(f"Successfully extracted {len(data)} characters of text from PDF.")
		return data
	except Exception as e:
		LOGGER.error(f"Failed to extract PDF data from {pdf_path}: {e}")
		raise


def write_extracted_data(output_path: str, data: str) -> Path:
	path = Path(output_path).expanduser().resolve()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(data, encoding="utf-8")
	return path


def main() -> None:
	logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
	parser = argparse.ArgumentParser(description="Extract PDF data with PyMuPDF and write it to a txt file")
	parser.add_argument("pdf_path", nargs="?", help="Path to the PDF file")
	args = parser.parse_args()

	try:
		pdf_path = args.pdf_path or input("Enter PDF file path: ").strip()
		if not pdf_path:
			raise ValueError("No PDF file path provided.")

		pdf_file = resolve_pdf_path(pdf_path)
		output_path = Path("pdf_to_txt") / f"{pdf_file.stem}.txt"

		data = extract_pdf_data(str(pdf_file))
		output_file = write_extracted_data(str(output_path), data)
		LOGGER.info(f"Extracted data saved to {output_file}")
	except Exception as e:
		LOGGER.error(f"Error during PDF extraction workflow: {e}")


# if __name__ == "__main__":
# 	main()
