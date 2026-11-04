"""Gemini-assisted matching: extract job requirements and find resume evidence, with checks.

Gemini never produces the score. It returns short quotes, and the app keeps a quote only when:
- the quote appears word for word in the job description or in the resume, and
- the resume quote really mentions the skill it is attached to.
The section the quote is in decides the strength, using the same rules as the rule-based matcher.
Gemini can add evidence the rules missed (for example "built ML pipelines" for Machine Learning).
It cannot remove a match the rules already found, and results are cached so the same inputs give the same output.
"""

import hashlib
import json
import re

from . import config
from .jd_parser import QUALIFICATION_TERMS, SOFT_SKILLS
from .llm_rewrite import ask_gemini
from .resume_model import sections_text
from .skills import contains_term, find_skills, normalize_skill

EXTRACT_PROMPT = """You are reading a job description to find what the employer asks for.

Task: list the TECHNICAL skills, tools, languages and subjects the job asks for.
- "required" = clearly required (words such as required, must have, you will need, minimum).
- "preferred" = nice to have (words such as preferred, plus, bonus, good to have).
- Use the skill name as written in the job description (for example "Retrieval-Augmented Generation", "Docker").
- For each skill, copy the exact sentence or phrase from the job description that shows it, in "quote".
- Do NOT include soft skills (teamwork, communication, leadership, problem solving, time management).
- Do NOT invent anything that the text does not say.
- "qualifications": degree words the job asks for, such as "bachelor's degree", "master's degree", "PhD".

Job description:
---
{jd_text}
---

Reply with JSON only in this shape:
{{"required": [{{"skill": "...", "quote": "..."}}], "preferred": [{{"skill": "...", "quote": "..."}}], "qualifications": ["..."]}}"""

JUDGE_PROMPT = """You are checking whether a resume shows evidence for each skill a job asks for.

For each skill in the list below, decide whether the resume mentions it, including synonyms and clear
descriptions (for example "built retrieval pipelines over PDFs" shows "Retrieval-Augmented Generation").
- Only count evidence that is stated in the resume. Do not assume a skill from a job title or from a related skill.
- For each skill that the resume shows, copy the exact sentence from the resume in "evidence".
- If the resume does not show the skill, leave it out of the reply.
- Soft skills are not part of this check.

Skills to check: {skills}

Resume lines (each line is numbered and shows its section):
{resume_lines}

Reply with JSON only in this shape:
{{"found": [{{"skill": "...", "evidence": "exact sentence copied from one resume line"}}]}}"""

_cache: dict[str, dict] = {}


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _cache_key(*parts: str) -> str:
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _parse_json(reply: str | None) -> dict | None:
    if not reply:
        return None
    try:
        data = json.loads(reply)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _default_ask(prompt: str) -> str | None:
    return ask_gemini(prompt, config.LLM_MODEL, config.GEMINI_API_KEY)


def extract_job_requirements(jd_text: str, ask=None) -> dict | None:
    """Gemini's reading of the job description, with each skill checked against the text. None if unavailable."""
    key = _cache_key("extract", config.LLM_MODEL, jd_text)
    if key in _cache:
        return _cache[key]
    ask = ask or _default_ask
    data = _parse_json(ask(EXTRACT_PROMPT.format(jd_text=jd_text[:8000])))
    if data is None:
        return None
    jd_normal = _normal(jd_text)
    result = {"required": [], "preferred": [], "qualifications": []}
    for level in ("required", "preferred"):
        for item in data.get(level, []) or []:
            if not isinstance(item, dict):
                continue
            quote = _normal(str(item.get("quote", "")))
            canonical = normalize_skill(str(item.get("skill", "")))
            if canonical and canonical not in SOFT_SKILLS and quote and quote in jd_normal and canonical not in result[level]:
                result[level].append(canonical)
    for label in data.get("qualifications", []) or []:
        if label in QUALIFICATION_TERMS and label not in result["qualifications"] and \
                any(term in jd_normal for term in QUALIFICATION_TERMS[label]):
            result["qualifications"].append(label)
    result["preferred"] = [s for s in result["preferred"] if s not in result["required"]]
    _cache[key] = result
    return result


def judge_evidence(resume_data: dict, skills: list[str], ask=None) -> dict:
    """Verified evidence per skill: {skill: (section_key, evidence_text)}. Only checked quotes are returned."""
    if not skills:
        return {}
    blocks = [b for b in sections_text(resume_data) if b["text"].strip()]
    if not blocks:
        return {}
    resume_lines = "\n".join(f"{i + 1}. [{b['section']}] {b['text']}" for i, b in enumerate(blocks))
    key = _cache_key("judge", config.LLM_MODEL, ",".join(sorted(skills)), resume_lines)
    if key in _cache:
        return _cache[key]
    ask = ask or _default_ask
    data = _parse_json(ask(JUDGE_PROMPT.format(skills=", ".join(skills), resume_lines=resume_lines[:12000])))
    verified: dict[str, tuple[str, str]] = {}
    if data is None:
        return verified
    wanted = set(skills)
    for item in data.get("found", []) or []:
        if not isinstance(item, dict):
            continue
        skill = normalize_skill(str(item.get("skill", "")))
        evidence = _normal(str(item.get("evidence", "")))
        if skill not in wanted or not evidence or skill in verified:
            continue
        for block in blocks:
            if evidence in _normal(block["text"]) and skill in find_skills(block["text"]):
                verified[skill] = (block["section"], evidence)
                break
    _cache[key] = verified
    return verified


def requirements_with_gemini(rule_requirements: dict, jd_text: str, ask=None) -> tuple[dict, bool]:
    """Add Gemini's verified skills to the rule-based requirements. Returns (requirements, used_gemini)."""
    if not (config.LLM_MODEL and config.GEMINI_API_KEY):
        return rule_requirements, False
    extra = extract_job_requirements(jd_text, ask=ask)
    if extra is None:
        return rule_requirements, False
    merged = dict(rule_requirements)
    required = list(rule_requirements.get("required", []))
    preferred = list(rule_requirements.get("preferred", []))
    for skill in extra["required"]:
        if skill not in required:
            required.append(skill)
        if skill in preferred:
            preferred.remove(skill)
    for skill in extra["preferred"]:
        if skill not in required and skill not in preferred:
            preferred.append(skill)
    merged["required"] = sorted(required)
    merged["preferred"] = sorted(preferred)
    merged["qualifications"] = sorted(set(rule_requirements.get("qualifications", [])) | set(extra["qualifications"]))
    return merged, True


def evidence_with_gemini(resume_data: dict, requirements: dict, ask=None) -> tuple[dict, bool]:
    """Verified Gemini evidence for the required and preferred skills. Returns (evidence, used_gemini)."""
    if not (config.LLM_MODEL and config.GEMINI_API_KEY):
        return {}, False
    skills = sorted(set(requirements.get("required", [])) | set(requirements.get("preferred", [])))
    verified = judge_evidence(resume_data, skills, ask=ask)
    return verified, bool(verified)
