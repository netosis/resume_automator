import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from jd_latex_modifier_system_prompt import (
    SECTION_PLANNING_SYSTEM_PROMPT,
    SECTION_EDIT_SYSTEM_PROMPT,
    SKILL_EXTRACTION_SYSTEM_PROMPT,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_LATEX_PATH = "generated_latex/My_resume.tex"
DEFAULT_JD_PATH = "jd_to_latex/job_description.txt"
DEFAULT_OUTPUT_DIR = "generated_latex"
DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_LOG_LEVEL = "INFO"

ALLOWED_SECTION_NAMES = ("summary", "education", "experience", "skills", "other_parameters")
EDITABLE_SECTION_NAMES = ("summary", "education", "experience", "other_parameters")

# Approximate chars-per-token ratio for logging estimates (conservative for English text)
_CHARS_PER_TOKEN_ESTIMATE = 4
# Warn if a single prompt (system + user) exceeds this estimated token count
_PROMPT_SIZE_WARNING_THRESHOLD = 8000

@dataclass
class IterationRecord:
	iteration: int
	phase: str
	input_tokens: int | None
	output_tokens: int | None


@dataclass
class ResumeSections:
	latex_path: Path
	original_latex: str
	summary_original: str
	education_original: str
	experience_original: str
	other_parameters_original: str
	summary: str
	education: str
	experience: str
	skills: str
	other_parameters: str
	skill_keywords: list[str] = field(default_factory=list)
	has_explicit_skills_section: bool = False
	education_blocks: list[str] = field(default_factory=list)
	experience_blocks: list[str] = field(default_factory=list)

	@classmethod
	def load(cls, latex_path: str, agent: "ResumeTailoringAgent" = None) -> "ResumeSections":
		path = resolve_tex_path(latex_path)
		original_latex = path.read_text(encoding="utf-8", errors="replace")
		if not original_latex.strip():
			raise ValueError(f"Input LaTeX resume is empty: {path}")

		summary_original = extract_between_markers(
			original_latex,
			r"\begin{center}",
			r"\end{center}",
		)
		education_original, experience_original, education_blocks, experience_blocks = cls._extract_employment_sections(original_latex)
		other_parameters_original = extract_between_markers(
			original_latex,
			r"\section{PROJECTS}",
			r"\end{document}",
		)

		extracted_skills: list[str] = []
		if agent:
			extracted_skills = agent.extract_skills(experience_original)

		return cls(
			latex_path=path,
			original_latex=original_latex,
			summary_original=summary_original,
			education_original=education_original,
			experience_original=experience_original,
			other_parameters_original=other_parameters_original,
			summary=summary_original.strip(),
			education=education_original.strip(),
			experience=experience_original.strip(),
			skills=format_skill_list(extracted_skills),
			other_parameters=other_parameters_original.strip(),
			skill_keywords=extracted_skills,
			has_explicit_skills_section=bool(re.search(r"\\section\*?\{SKILLS\}", original_latex, flags=re.IGNORECASE)),
			education_blocks=education_blocks,
			experience_blocks=experience_blocks,
		)

	@staticmethod
	def _extract_employment_sections(original_latex: str) -> tuple[str, str, list[str], list[str]]:
		employment_body = extract_between_markers(
			original_latex,
			r"\section{EXPERIENCE}",
			r"\section{PROJECTS}",
		)
		education_body = extract_between_markers(
			original_latex,
			r"\section{EDUCATION}",
			r"\section{SKILLS}",
		)
		
		# Merge if needed, but since it returns blocks, we can just process both
		block_pattern = re.compile(
			r"(\\noindent\s*.*?|\\resumeSubheading\s*.*?)(?=\n\s*\\noindent|\n\s*\\resumeSubheading|\n\s*%------------------------|\n\s*\\section|\Z)",
			re.DOTALL,
		)
		
		exp_blocks = [match.group(1).rstrip() for match in block_pattern.finditer(employment_body)]
		ed_blocks = [match.group(1).rstrip() for match in block_pattern.finditer(education_body)]
		
		experience_blocks: list[str] = [b.strip() for b in exp_blocks if b.strip()]
		education_blocks: list[str] = [b.strip() for b in ed_blocks if b.strip()]

		education_text = education_body.strip()
		experience_text = employment_body.strip()
		return education_text, experience_text, education_blocks, experience_blocks

	def preview_map(self) -> dict[str, str]:
		return {
			"summary": preview_text(self.summary, 700),
			"education": preview_text(self.education, 900),
			"experience": preview_text(self.experience, 1200),
			"skills": preview_text(self.skills, 500),
			"other_parameters": preview_text(self.other_parameters, 900),
		}

	def get_section_text(self, section_name: str) -> str:
		if section_name == "summary":
			return self.summary_original
		if section_name == "education":
			return self.education_original
		if section_name == "experience":
			return self.experience_original
		if section_name == "skills":
			return self.skills
		if section_name == "other_parameters":
			return self.other_parameters_original
		raise ValueError(f"Unsupported section name: {section_name}")

	def apply_updates(self, section_updates: dict[str, str]) -> str:
		updated_latex = self.original_latex
		if "summary" in section_updates:
			updated_latex = replace_between_markers(
				updated_latex,
				r"\begin{center}",
				r"\end{center}",
				section_updates["summary"],
			)
		if "education" in section_updates and self.education_original:
			updated_latex = updated_latex.replace(self.education_original, section_updates["education"], 1)
		if "experience" in section_updates and self.experience_original:
			updated_latex = updated_latex.replace(self.experience_original, section_updates["experience"], 1)
		if "other_parameters" in section_updates and self.other_parameters_original:
			updated_latex = updated_latex.replace(self.other_parameters_original, section_updates["other_parameters"], 1)
		return updated_latex

	def save_artifacts(
		self,
		updated_latex: str,
		output_dir: str,
		company_name: str,
		job_role: str,
		output_name: str | None,
		change_report_text: str,
	) -> tuple[Path, Path]:
		target_dir = Path(output_dir).expanduser().resolve() / company_name / job_role
		target_dir.mkdir(parents=True, exist_ok=True)
		stem = output_name or f"{self.latex_path.stem}_jd_tailored"
		latex_path = target_dir / f"{stem}.tex"
		changes_path = target_dir / f"{stem}_changes.txt"
		latex_path.write_text(updated_latex, encoding="utf-8")
		changes_path.write_text(change_report_text, encoding="utf-8")
		return latex_path, changes_path


class ResumeTailoringAgent:
	def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
		resolved_api_key = resolve_api_key(api_key)
		self.llm = ChatGoogleGenerativeAI(model=model, google_api_key=resolved_api_key)
		self.iteration_counter = 0
		self.iteration_records: list[IterationRecord] = []

	def _invoke(self, system_prompt: str, user_prompt: str, phase: str):
		self.iteration_counter += 1

		# Log prompt sizes to help diagnose high token usage
		system_chars = len(system_prompt)
		user_chars = len(user_prompt)
		total_chars = system_chars + user_chars
		estimated_tokens = total_chars // _CHARS_PER_TOKEN_ESTIMATE
		LOGGER.info(
			"Phase '%s' (Iteration %s) - prompt sizes: system=%d chars, user=%d chars, total=%d chars (~%d estimated tokens)",
			phase, self.iteration_counter, system_chars, user_chars, total_chars, estimated_tokens,
		)
		if estimated_tokens > _PROMPT_SIZE_WARNING_THRESHOLD:
			LOGGER.warning(
				"Phase '%s' prompt is large (~%d estimated tokens). This may cause high token usage.",
				phase, estimated_tokens,
			)

		LOGGER.info(f"Invoking {self.llm.model} for phase '{phase}' (Iteration {self.iteration_counter})...")
		try:
			response = self.llm.invoke([
				SystemMessage(content=system_prompt),
				HumanMessage(content=user_prompt),
			])
			input_tokens, output_tokens = get_token_usage(response)
			record = IterationRecord(
				iteration=self.iteration_counter,
				phase=phase,
				input_tokens=input_tokens,
				output_tokens=output_tokens,
			)
			self.iteration_records.append(record)
			if input_tokens is not None or output_tokens is not None:
				LOGGER.info(
					"Iteration %s (%s) token usage - input tokens: %s, output tokens: %s",
					self.iteration_counter,
					phase,
					input_tokens,
					output_tokens,
				)
			else:
				LOGGER.info(
					"Iteration %s (%s) token usage metadata was not returned by the model response.",
					self.iteration_counter,
					phase,
				)
			return response, record
		except Exception as e:
			LOGGER.error(f"Error invoking LLM during phase '{phase}': {e}")
			raise

	def plan_sections(self, job_description: str, resume: ResumeSections) -> dict[str, object]:
		user_prompt = build_planning_prompt(resume.preview_map(), job_description)
		response, record = self._invoke(SECTION_PLANNING_SYSTEM_PROMPT, user_prompt, "plan")
		parsed = parse_planning_response(str(response.content))
		parsed["iteration"] = record.iteration
		parsed["input_tokens"] = record.input_tokens
		parsed["output_tokens"] = record.output_tokens
		return parsed

	def edit_section(self, section_name: str, section_text: str, job_description: str) -> dict[str, object]:
		user_prompt = build_section_edit_prompt(section_name, section_text, job_description)
		response, record = self._invoke(SECTION_EDIT_SYSTEM_PROMPT, user_prompt, f"edit:{section_name}")
		parsed = parse_section_edit_response(str(response.content))
		parsed["iteration"] = record.iteration
		parsed["input_tokens"] = record.input_tokens
		parsed["output_tokens"] = record.output_tokens
		parsed["section_name"] = section_name
		return parsed

	def extract_skills(self, document_text: str) -> list[str]:
		if len(document_text) > 6000:
			LOGGER.warning(
				"extract_skills: experience text is %d chars; consider trimming to reduce token cost.",
				len(document_text),
			)
		response, _ = self._invoke(SKILL_EXTRACTION_SYSTEM_PROMPT, f"Resume Text:\n{document_text}", "extract_skills")
		content = str(response.content).strip()
		content = strip_code_fences(content)
		skills = [s.strip() for s in content.split(",") if s.strip()]
		LOGGER.info("Extracted %d skills from experience text.", len(skills))
		return skills

	def token_summary(self) -> list[dict[str, object]]:
		return [
			{
				"iteration": record.iteration,
				"phase": record.phase,
				"input_tokens": record.input_tokens,
				"output_tokens": record.output_tokens,
			}
			for record in self.iteration_records
		]

	def log_total_usage(self) -> None:
		"""Log aggregated token usage across all iterations."""
		total_input = sum(r.input_tokens for r in self.iteration_records if r.input_tokens is not None)
		total_output = sum(r.output_tokens for r in self.iteration_records if r.output_tokens is not None)
		LOGGER.info(
			"Total token usage across %d iterations - input: %d, output: %d, combined: %d",
			len(self.iteration_records), total_input, total_output, total_input + total_output,
		)


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

	load_env_file()

	env_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
	if env_api_key:
		return env_api_key

	raise ValueError(
		"Missing API key. Pass --api-key or set GOOGLE_API_KEY (or GEMINI_API_KEY)."
	)


def resolve_tex_path(tex_path: str) -> Path:
	path = Path(tex_path).expanduser().resolve()
	if not path.exists():
		raise FileNotFoundError(f"LaTeX file not found: {path}")
	if path.suffix.lower() != ".tex":
		raise ValueError(f"Expected a .tex file, got: {path.name}")
	return path


def resolve_jd_path(jd_path: str) -> Path:
	path = Path(jd_path).expanduser().resolve()
	if not path.exists():
		raise FileNotFoundError(f"Job description file not found: {path}")
	return path


def read_job_description(jd_path: str | None, jd_text: str | None) -> str:
	if jd_text and jd_text.strip():
		return jd_text.strip()

	resolved_path = resolve_jd_path(jd_path or DEFAULT_JD_PATH)
	return resolved_path.read_text(encoding="utf-8", errors="replace").strip()


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


def extract_tag(text: str, tag: str) -> str:
	pattern = rf"<{tag}>\s*(.*?)\s*</{tag}>"
	match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
	if not match:
		raise ValueError(f"Model response is missing <{tag}>...</{tag}> block.")
	return match.group(1).strip()


def extract_optional_tag(text: str, tag: str) -> str | None:
	pattern = rf"<{tag}>\s*(.*?)\s*</{tag}>"
	match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
	if not match:
		return None
	value = match.group(1).strip()
	return value or None


def parse_bulleted_section(text: str) -> list[str]:
	items: list[str] = []
	for line in text.splitlines():
		cleaned = line.strip()
		if cleaned.startswith("- "):
			items.append(cleaned[2:].strip())
		elif cleaned:
			items.append(cleaned)
	return items


def normalize_target_sections(raw_target_sections: str) -> list[str]:
	candidates = re.split(r"[,\n;|]+", raw_target_sections)
	normalized: list[str] = []
	for candidate in candidates:
		section = candidate.strip().lower().replace(" ", "_")
		if section in ALLOWED_SECTION_NAMES and section not in normalized:
			normalized.append(section)
		elif section in {"other", "others", "otherparameters", "other-parameters"} and "other_parameters" not in normalized:
			normalized.append("other_parameters")
	return normalized


def parse_planning_response(raw_response: str) -> dict[str, object]:
	text = strip_code_fences(raw_response)
	decision = extract_tag(text, "DECISION").upper()
	target_sections = normalize_target_sections(extract_optional_tag(text, "TARGET_SECTIONS") or "")
	company_name = extract_optional_tag(text, "COMPANY_NAME")
	job_role = extract_optional_tag(text, "JOB_ROLE")
	rationale = extract_tag(text, "RATIONALE")
	learnable_skills = parse_bulleted_section(extract_tag(text, "LEARNABLE_SKILLS"))

	if decision not in {"MODIFY", "SKIP"}:
		raise ValueError(f"Unexpected DECISION value: {decision}")

	return {
		"decision": decision,
		"target_sections": target_sections,
		"company_name": company_name,
		"job_role": job_role,
		"rationale": rationale,
		"learnable_skills": learnable_skills,
	}


def parse_section_edit_response(raw_response: str) -> dict[str, object]:
	text = strip_code_fences(raw_response)
	modified_section = extract_tag(text, "MODIFIED_SECTION")
	change_notes = extract_optional_tag(text, "CHANGE_NOTES") or "No change notes provided."
	return {
		"modified_section": modified_section,
		"change_notes": change_notes,
	}


def sanitize_for_path(name: str) -> str:
	cleaned = re.sub(r'[\\/:*?"<>|]+', " ", name)
	cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
	return cleaned or "Unknown"


def derive_company_name(job_description: str) -> str:
	lines = [line.strip() for line in job_description.splitlines() if line.strip()]
	if not lines:
		return "UnknownCompany"

	for line in lines:
		lower_line = line.lower()
		if lower_line.startswith("company"):
			parts = re.split(r"company\s*[:\-]", line, flags=re.IGNORECASE)
			if len(parts) > 1 and parts[1].strip():
				return sanitize_for_path(parts[1].strip())

	first_line = lines[0]
	if "job description" not in first_line.lower():
		return sanitize_for_path(first_line)

	return "UnknownCompany"


def derive_job_role(job_description: str) -> str:
	patterns = [
		r"(?:role|position|job title|title)\s*[:\-]\s*(.+)",
		r"hiring\s+for\s+(.+)",
		r"looking\s+for\s+(.+)",
	]

	for line in job_description.splitlines():
		text = line.strip()
		if not text:
			continue
		for pattern in patterns:
			match = re.search(pattern, text, flags=re.IGNORECASE)
			if match and match.group(1).strip():
				candidate = re.split(r"[.;|]", match.group(1).strip())[0].strip()
				return sanitize_for_path(candidate)

	jd_lower = job_description.lower()
	if "generative ai" in jd_lower or "llm" in jd_lower:
		return "Generative AI Engineer"
	if "data scientist" in jd_lower:
		return "Data Scientist"
	if "machine learning" in jd_lower or "ml" in jd_lower:
		return "Machine Learning Engineer"
	if "python" in jd_lower:
		return "Python Developer"

	return "TargetRole"


def format_skill_list(skills: list[str]) -> str:
	return "\n".join(f"- {skill}" for skill in skills)


def preview_text(text: str, limit: int) -> str:
	cleaned = text.strip()
	if len(cleaned) <= limit:
		return cleaned
	return cleaned[:limit].rstrip() + "\n[truncated]"


def replace_between_markers(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
	pattern = re.compile(
		rf"({re.escape(start_marker)})(.*?)(?={re.escape(end_marker)})",
		re.DOTALL,
	)
	match = pattern.search(text)
	if match:
		return pattern.sub(lambda found: found.group(1) + replacement, text, count=1)
	
	# Fallback loose search
	loose_start = re.escape(start_marker).replace(r'\ ', r'\s*').replace(r'\{', r'\s*\{')
	loose_end = re.escape(end_marker).replace(r'\ ', r'\s*').replace(r'\{', r'\s*\{')
	loose_pattern = re.compile(rf"({loose_start})(.*?)(?={loose_end})", re.DOTALL | re.IGNORECASE)
	match = loose_pattern.search(text)
	if not match:
		raise ValueError(f"Could not locate block between {start_marker!r} and {end_marker!r}.")
	return loose_pattern.sub(lambda found: found.group(1) + replacement, text, count=1)


def extract_between_markers(text: str, start_marker: str, end_marker: str) -> str:
	pattern = re.compile(
		rf"{re.escape(start_marker)}(.*?){re.escape(end_marker)}",
		re.DOTALL,
	)
	match = pattern.search(text)
	if not match:
		# Fallback to ignore spaces explicitly to deal with formatting differences that LLM might introduce
		loose_start = re.escape(start_marker).replace(r'\ ', r'\s*')
		loose_end = re.escape(end_marker).replace(r'\ ', r'\s*')
		# Also optionally handle \section{...} vs \section {...}
		loose_start = loose_start.replace(r'\{', r'\s*\{')
		loose_end = loose_end.replace(r'\{', r'\s*\{')
		loose_pattern = re.compile(rf"{loose_start}(.*?){loose_end}", re.DOTALL | re.IGNORECASE)
		
		match = loose_pattern.search(text)
		if not match:
			raise ValueError(f"Could not locate block between {start_marker!r} and {end_marker!r}.")
	return match.group(1)


def build_planning_prompt(resume_previews: dict[str, str], job_description: str) -> str:
	return (
		"Evaluate the resume against the job description and decide whether the resume should be tailored.\n\n"
		"Use the previews below to choose only the sections that actually need edits.\n"
		"If the resume does not have a dedicated skills section, do not select skills.\n"
		"If skill wording needs improvement, fold it into experience or summary instead.\n\n"
		"Resume previews:\n"
		f"Summary:\n{resume_previews['summary']}\n\n"
		f"Education:\n{resume_previews['education']}\n\n"
		f"Experience:\n{resume_previews['experience']}\n\n"
		f"Skills:\n{resume_previews['skills']}\n\n"
		f"Other parameters:\n{resume_previews['other_parameters']}\n\n"
		"Job description:\n"
		f"{job_description}\n"
	)


def build_section_edit_prompt(section_name: str, section_text: str, job_description: str) -> str:
	return (
		f"Edit only the {section_name} section.\n\n"
		"Rules:\n"
		"- Keep the section focused and conservative.\n"
		"- Do not change any other part of the resume.\n"
		"- Preserve LaTeX formatting and structure.\n"
		"- Make only truthful changes that align with the job description.\n\n"
		"Section text:\n"
		f"{section_text}\n\n"
		"Job description:\n"
		f"{job_description}\n"
	)


def build_change_report(
	company_name: str,
	job_role: str,
	plan: dict[str, object],
	requested_sections: list[str],
	applied_sections: dict[str, dict[str, object]],
	iteration_records: list[dict[str, object]],
) -> str:
	lines = [
		f"Company: {company_name}",
		f"Job role: {job_role}",
		f"Decision: {plan.get('decision', 'UNKNOWN')}",
		f"Alignment rationale: {plan.get('rationale', 'N/A')}",
		"",
		"Requested sections:",
	]
	if requested_sections:
		for section in requested_sections:
			lines.append(f"- {section}")
	else:
		lines.append("- None")

	lines.extend([
		"",
		"Applied changes:",
	])
	if applied_sections:
		for section_name, section_result in applied_sections.items():
			change_notes = str(section_result.get("change_notes", "No change notes provided.")).strip()
			lines.append(f"- {section_name}: {change_notes}")
	else:
		lines.append("- None")

	learnable_skills = plan.get("learnable_skills") or []
	lines.extend([
		"",
		"Suggested quick-learn skills:",
	])
	if learnable_skills:
		for skill in learnable_skills:
			lines.append(f"- {skill}")
	else:
		lines.append("- None")

	lines.extend([
		"",
		"Token usage by iteration:",
	])
	if iteration_records:
		for record in iteration_records:
			lines.append(
				f"- Iteration {record['iteration']} ({record['phase']}): input={record['input_tokens']}, output={record['output_tokens']}"
			)
	else:
		lines.append("- None")

	return "\n".join(lines).strip() + "\n"


def resolve_edit_target(section_name: str, resume: ResumeSections) -> str:
	if section_name == "skills" and not resume.has_explicit_skills_section:
		return "experience"
	return section_name


def tailor_resume_from_job_description(
	latex_path: str = DEFAULT_LATEX_PATH,
	jd_path: str = DEFAULT_JD_PATH,
	jd_text: str | None = None,
	output_dir: str = DEFAULT_OUTPUT_DIR,
	output_name: str | None = None,
	model: str = DEFAULT_MODEL,
	api_key: str | None = None,
) -> dict[str, object]:
	try:
		agent = ResumeTailoringAgent(model=model, api_key=api_key)
		resume = ResumeSections.load(latex_path, agent=agent)
		job_description = read_job_description(jd_path, jd_text)
		if not job_description.strip():
			raise ValueError("Job description is empty.")

		plan = agent.plan_sections(job_description, resume)

		company_name = sanitize_for_path(str(plan.get("company_name") or derive_company_name(job_description)))
		job_role = sanitize_for_path(str(plan.get("job_role") or derive_job_role(job_description)))

		if plan["decision"] == "SKIP":
			return {
				"decision": plan["decision"],
				"company_name": company_name,
				"job_role": job_role,
				"rationale": plan.get("rationale"),
				"target_sections": plan.get("target_sections", []),
				"learnable_skills": plan.get("learnable_skills", []),
				"iteration_records": agent.token_summary(),
			}

		requested_sections = list(plan.get("target_sections") or [])
		LOGGER.info(
			"Planning complete. Sections to edit: %s (%d total)",
			requested_sections, len(requested_sections),
		)
		applied_sections: dict[str, dict[str, object]] = {}
		section_updates: dict[str, str] = {}
		resolved_sections_in_order: list[str] = []

		for requested_section in requested_sections:
			resolved_section = resolve_edit_target(requested_section, resume)
			if resolved_section in resolved_sections_in_order:
				LOGGER.info("Skipping duplicate resolved section '%s' (from '%s').", resolved_section, requested_section)
				continue
			section_text = resume.get_section_text(resolved_section)
			if not section_text.strip():
				LOGGER.warning("Section '%s' is empty, skipping edit.", resolved_section)
				continue
			LOGGER.info("Editing section '%s' (%d chars)...", resolved_section, len(section_text))
			section_result = agent.edit_section(resolved_section, section_text, job_description)
			applied_sections[resolved_section] = section_result
			section_updates[resolved_section] = str(section_result["modified_section"])
			resolved_sections_in_order.append(resolved_section)

		if not section_updates:
			return {
				"decision": "SKIP",
				"company_name": company_name,
				"job_role": job_role,
				"rationale": plan.get("rationale"),
				"target_sections": requested_sections,
				"learnable_skills": plan.get("learnable_skills", []),
				"iteration_records": agent.token_summary(),
				"message": "No editable sections were produced by the agent.",
			}

		updated_latex = resume.apply_updates(section_updates)
		change_report = build_change_report(
			company_name=company_name,
			job_role=job_role,
			plan=plan,
			requested_sections=requested_sections,
			applied_sections=applied_sections,
			iteration_records=agent.token_summary(),
		)
		latex_output_path, changes_output_path = resume.save_artifacts(
			updated_latex=updated_latex,
			output_dir=output_dir,
			company_name=company_name,
			job_role=job_role,
			output_name=output_name,
			change_report_text=change_report,
		)

		agent.log_total_usage()

		return {
			"decision": plan["decision"],
			"company_name": company_name,
			"job_role": job_role,
			"rationale": plan.get("rationale"),
			"target_sections": requested_sections,
			"applied_sections": list(applied_sections.keys()),
			"learnable_skills": plan.get("learnable_skills", []),
			"iteration_records": agent.token_summary(),
			"output_path": latex_output_path,
			"changes_path": changes_output_path,
		}
	except Exception as e:
		LOGGER.error(f"Failed to tailor resume: {e}")
		raise


modify_latex_as_per_jd = tailor_resume_from_job_description


def main() -> None:
	parser = argparse.ArgumentParser(
		description=(
			"Conservatively tailor a LaTeX resume for a job description only when alignment "
			"with existing expertise is strong."
		)
	)
	parser.add_argument(
		"--latex-path",
		default=DEFAULT_LATEX_PATH,
		help=f"Path to the input resume .tex file (default: {DEFAULT_LATEX_PATH})",
	)
	parser.add_argument(
		"--jd-path",
		default=DEFAULT_JD_PATH,
		help=f"Path to a job description text file (default: {DEFAULT_JD_PATH})",
	)
	parser.add_argument("--jd-text", default=None, help="Inline job description text")
	parser.add_argument(
		"--output-dir",
		default=DEFAULT_OUTPUT_DIR,
		help=f"Directory for modified .tex output (default: {DEFAULT_OUTPUT_DIR})",
	)
	parser.add_argument("--output-name", default=None, help="Output file name without extension")
	parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model name (default: {DEFAULT_MODEL})")
	parser.add_argument("--api-key", dest="api_key", default=None, help="Google/Gemini API key")
	parser.add_argument("--log-level", default=DEFAULT_LOG_LEVEL, help=f"Logging level (default: {DEFAULT_LOG_LEVEL})")
	args = parser.parse_args()

	logging.basicConfig(
		level=getattr(logging, args.log_level.upper(), logging.INFO),
		format="%(levelname)s:%(name)s:%(message)s",
	)

	try:
		result = tailor_resume_from_job_description(
			latex_path=args.latex_path,
			jd_path=args.jd_path,
			jd_text=args.jd_text,
			output_dir=args.output_dir,
			output_name=args.output_name,
			model=args.model,
			api_key=args.api_key,
		)

		print(f"Decision: {result['decision']}")
		print(f"Company: {result['company_name']}")
		print(f"Role: {result['job_role']}")
		if result.get("rationale"):
			print(f"Rationale: {result['rationale']}")

		if result.get("iteration_records"):
			for record in result["iteration_records"]:
				print(
					f"Iteration {record['iteration']} ({record['phase']}) token usage - input: {record['input_tokens']}, output: {record['output_tokens']}"
				)

		if result.get("learnable_skills"):
			print("Suggested quick-learn skills (4-7 hours / adjacent):")
			for skill in result["learnable_skills"]:
				print(f"- {skill}")

		if result["decision"] == "MODIFY":
			print(f"Modified LaTeX saved to {result['output_path']}")
			print(f"Change report saved to {result['changes_path']}")
		else:
			print("Resume was not modified because JD alignment was insufficient.")

	except Exception as exc:
		LOGGER.error("JD tailoring failed: %s", exc)
		print(f"Error: {exc}")
		sys.exit(1)


if __name__ == "__main__":
	main()
