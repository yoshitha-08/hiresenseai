"""Job description intake: validation and requirement extraction."""

import re

from .resume_parser import extract_document_text
from .skills import extract_keywords, find_skills

PREFERRED_HINTS = ("preferred", "nice to have", "good to have", "bonus", "desirable", "plus", "optional")
REQUIRED_HINTS = ("required", "must have", "must-have", "requirements", "essential", "qualifications", "minimum")

QUALIFICATION_TERMS = {
    "bachelor's degree": ["bachelor", "b.tech", "btech", "b.e.", "b.sc", "bsc", "bca"],
    "master's degree": ["master", "m.tech", "mtech", "m.sc", "msc", "mca"],
    "PhD": ["phd", "doctorate"],
    "diploma": ["diploma"],
    "computer science degree": ["computer science", "computer engineering", "information technology"],
    "any engineering degree": ["engineering degree", "engineering"],
}


class JDError(ValueError):
    """User-facing problem with a job description."""


def read_jd_text(pasted: str, upload_name: str | None = None, upload_bytes: bytes | None = None) -> str:
    """Use the uploaded file when given, otherwise the pasted text. Validates that text is usable."""
    if upload_bytes:
        if (upload_name or "").lower().endswith(".txt"):
            try:
                text = upload_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise JDError("The text file must be UTF-8 encoded.") from exc
        else:
            try:
                text = extract_document_text(upload_name or "", upload_bytes)
            except ValueError as exc:
                raise JDError(f"The job description file could not be read: {exc}") from exc
    else:
        text = (pasted or "").strip()
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text.split()) < 15:
        raise JDError("The job description needs at least 15 words of usable text.")
    return text


def extract_requirements(jd_text: str) -> dict:
    """Deterministic requirement extraction.

    required / preferred: canonical skills, by the JD section they appear in (required wins if both).
    qualifications: qualification labels found in the JD.
    years: explicit experience years stated in the JD (not scored, shown as a note).
    keywords: frequent non-skill words in the JD.
    """
    required, preferred = set(), set()
    mode = "required"
    for line in jd_text.splitlines():
        lowered = line.strip().lower()
        if not lowered:
            continue
        if any(hint in lowered for hint in PREFERRED_HINTS) and len(lowered) <= 80:
            mode = "preferred"
        elif any(hint in lowered for hint in REQUIRED_HINTS) and len(lowered) <= 80:
            mode = "required"
        found = find_skills(line)
        if mode == "preferred":
            preferred |= found
        else:
            required |= found
    preferred -= required

    lowered_jd = jd_text.lower()
    qualifications = [
        label for label, terms in QUALIFICATION_TERMS.items()
        if any(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", lowered_jd) for term in terms)
    ]
    years = sorted({int(match) for match in re.findall(r"(\d{1,2})\+?\s*(?:years|yrs)", lowered_jd)})
    keywords = extract_keywords(jd_text, exclude=required | preferred)
    return {
        "required": sorted(required),
        "preferred": sorted(preferred),
        "qualifications": qualifications,
        "years": years,
        "keywords": keywords,
    }
