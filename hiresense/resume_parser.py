"""Conservative resume parsing for PDF and DOCX files.

Rules:
- Dates, job titles, qualifications and achievements are never guessed. Text is copied as written.
- Anything that cannot be placed confidently is kept in the "unclassified" section.
- A scanned PDF with no text layer is reported as needing OCR, never as a successful parse.
"""

import io
import re

from . import config
from .resume_model import ENTRY_SECTIONS, empty_resume, new_id, normalize_resume

BULLET_RE = re.compile(r"^\s*[•●▪◦·\-*–]\s*")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s\-()]{7,}\d)")
LINK_LABEL_RE = re.compile(r"^(?:\S{1,2}\s+)?(linkedin|github|portfolio|website|gitlab|behance|kaggle|leetcode)\b.*$",
                           re.IGNORECASE)
URL_RE = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin\.com|github\.com)/\S+", re.IGNORECASE)
DATE_RE = re.compile(
    r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}"
    r"|\d{1,2}/\d{4}|\b(?:19|20)\d{2}\b)"
    r"(?:\s*(?:-|–|—|to)\s*(?:present|current|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}"
    r"|\d{1,2}/\d{4}|(?:19|20)\d{2}))?",
    re.IGNORECASE,
)

SECTION_ALIASES = {
    "summary": ["summary", "professional summary", "profile", "objective", "career objective", "about me"],
    "experience": ["experience", "work experience", "professional experience", "employment",
                   "employment history", "work history"],
    "internships": ["internship", "internships", "industrial training", "training"],
    "education": ["education", "academic background", "academics", "qualifications"],
    "skills": ["skills", "technical skills", "core competencies", "competencies", "technologies", "tools"],
    "projects": ["projects", "academic projects", "personal projects", "key projects"],
    "certifications": ["certifications", "certificates", "licenses", "licenses and certifications", "courses"],
    "achievements": ["achievements", "awards", "honors", "honours", "accomplishments", "awards and achievements"],
    "interests": ["interests", "hobbies", "hobbies and interests", "activities"],
    "links": ["links", "profiles", "online profiles", "professional links", "social links"],
}
HEADING_LOOKUP = {alias: section for section, aliases in SECTION_ALIASES.items() for alias in aliases}


class ResumeParseError(ValueError):
    """Raised with a user-facing message when a document cannot be read."""


def validate_upload(filename: str, data: bytes) -> str:
    """Return 'pdf' or 'docx', or raise ResumeParseError with a clear message."""
    name = (filename or "").lower()
    if not data:
        raise ResumeParseError("The file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise ResumeParseError(f"The file is larger than {config.MAX_UPLOAD_MB:g} MB.")
    if name.endswith(".pdf"):
        if not data.startswith(b"%PDF"):
            raise ResumeParseError("The file is named .pdf but is not a valid PDF.")
        return "pdf"
    if name.endswith(".docx"):
        if not data.startswith(b"PK"):
            raise ResumeParseError("The file is named .docx but is not a valid Word document.")
        return "docx"
    raise ResumeParseError("Unsupported file type. Upload a PDF or DOCX file.")


def extract_document_text(filename: str, data: bytes) -> str:
    """Extract plain text from a PDF or DOCX. Raises ResumeParseError on any problem."""
    file_type = validate_upload(filename, data)
    if file_type == "pdf":
        return _extract_pdf(data)
    return _extract_docx(data)


def _extract_pdf(data: bytes) -> str:
    import pymupdf

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ResumeParseError("The PDF could not be opened. It may be corrupted or password-protected.") from exc
    try:
        if document.needs_pass:
            raise ResumeParseError("The PDF is password-protected. Remove the password and try again.")
        pages = [page.get_text("text") for page in document]
    finally:
        document.close()
    text = "\n".join(pages).strip()
    if len(text) < 20:
        raise ResumeParseError(
            "This PDF has no extractable text. It may be a scanned image, and OCR is needed before it can be read."
        )
    return text


def _extract_docx(data: bytes) -> str:
    from docx import Document

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise ResumeParseError("The Word document could not be read. It may be corrupted.") from exc
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    text = "\n".join(line for line in lines if line.strip()).strip()
    if not text:
        raise ResumeParseError("The Word document contains no text.")
    return text


def _heading_section(line: str):
    """Return (section, is_unknown_heading) when a line is a section heading, else (None, False)."""
    stripped = line.strip().rstrip(":").strip()
    lowered = stripped.lower()
    if lowered in HEADING_LOOKUP and len(stripped) <= 45:
        return HEADING_LOOKUP[lowered], False
    # An all-caps or colon-ended short line that is not a known heading keeps its own bucket.
    letters = [ch for ch in stripped if ch.isalpha()]
    looks_like_heading = (
        0 < len(stripped) <= 45 and letters and stripped.isupper() and len(stripped.split()) <= 5
    ) or (line.strip().endswith(":") and len(stripped.split()) <= 5 and not BULLET_RE.match(line))
    if looks_like_heading:
        return "unclassified", True
    return None, False


def parse_resume_text(text: str) -> dict:
    """Turn plain resume text into the structured resume object. Never drops content silently."""
    data = empty_resume()
    notes = []
    lines = [line.rstrip() for line in (text or "").splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        raise ResumeParseError("No text was found in the resume.")

    buckets: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in lines:
        line = _clean_icon_line(line)
        if not any(ch.isalnum() for ch in line):
            continue  # icon-only lines from PDF icon fonts carry no content
        if LINK_LABEL_RE.match(line.strip()) and len(line.strip()) <= 60:
            buckets.setdefault("links", []).append(line.strip())
            continue
        section, unknown = _heading_section(line)
        if section:
            current = section
            if unknown:
                buckets.setdefault("unclassified", []).append(line.strip())
            else:
                buckets.setdefault(section, [])
            continue
        buckets.setdefault(current, []).append(line.strip())

    _parse_header(buckets.pop("header", []), data, notes)
    summary_lines = buckets.pop("summary", [])
    data["summary"] = " ".join(_strip_bullet(line) for line in summary_lines).strip()

    for section in ENTRY_SECTIONS:
        if section in buckets:
            data[section] = _parse_entries(buckets.pop(section))
    if "skills" in buckets:
        data["skills"] = _parse_skills(buckets.pop("skills"))
    if "links" in buckets:
        data["links"] = _parse_links(buckets.pop("links"))
    for section in ("achievements", "interests"):
        if section in buckets:
            data[section] = [{"id": new_id(), "text": _strip_bullet(line)} for line in buckets.pop(section)]

    leftovers = []
    for key, value in buckets.items():
        leftovers.extend(value)
    if leftovers:
        data["unclassified"].extend({"id": new_id(), "text": _strip_bullet(line)} for line in leftovers)
        notes.append(f"{len(leftovers)} line(s) could not be classified and were kept in Additional Content.")
    if not data["personal"]["name"]:
        notes.append("A name could not be identified confidently. Please add it in Personal Details.")
    data["parse_notes"] = notes
    return normalize_resume(data)


def _clean_icon_line(line: str) -> str:
    """Remove icon characters that PDFs put in front of contact and link labels, such as the ones before LinkedIn."""
    stripped = line.strip()
    match = re.match(r"^\S{1,2}\s+(linkedin|github|portfolio|website|email|phone)\b", stripped, re.IGNORECASE)
    if match:
        return stripped[len(stripped) - len(stripped.split(maxsplit=1)[1]):]
    return line


def _strip_bullet(line: str) -> str:
    return BULLET_RE.sub("", line).strip()


def _parse_header(lines, data, notes):
    personal = data["personal"]
    leftovers = []
    for line in lines:
        used = False
        email = EMAIL_RE.search(line)
        if email and not personal["email"]:
            personal["email"] = email.group(0)
            used = True
        phone = PHONE_RE.search(line)
        if phone and not personal["phone"] and not DATE_RE.search(line):
            personal["phone"] = phone.group(0).strip()
            used = True
        for url in URL_RE.findall(line):
            data["links"].append({"id": new_id(), "label": "", "url": url.strip(".,;")})
            used = True
        if used:
            # Remove the matched contact text; anything left over is kept.
            remainder = URL_RE.sub("", EMAIL_RE.sub("", PHONE_RE.sub("", line) if phone else line))
            remainder = re.sub(r"[|•·,]+", " ", remainder).strip()
            if remainder and not personal["name"] and _looks_like_name(remainder):
                personal["name"] = remainder
            elif remainder:
                leftovers.append(remainder)
            continue
        if not personal["name"] and _looks_like_name(line):
            personal["name"] = line.strip()
        else:
            leftovers.append(line)
    if leftovers:
        data["unclassified"].extend({"id": new_id(), "text": item} for item in leftovers)


def _looks_like_name(text: str) -> bool:
    words = text.split()
    return 1 <= len(words) <= 4 and not any(ch.isdigit() for ch in text) and "@" not in text


def _parse_entries(lines):
    entries = []
    current = None
    previous_was_bullet = False
    for line in lines:
        is_bullet = bool(BULLET_RE.match(line))
        text = _strip_bullet(line)
        if is_bullet:
            if current is None:
                current = _new_entry()
                entries.append(current)
            current["bullets"].append({"id": new_id(), "text": text})
            previous_was_bullet = True
            continue
        if previous_was_bullet and current is not None and text[:1].islower():
            # A wrapped bullet continuing on the next line.
            current["bullets"][-1]["text"] = f'{current["bullets"][-1]["text"]} {text}'
            continue
        if current is not None and not current["bullets"] and current["title"] and not current["organization"] \
                and not current.get("_meta_done"):
            # Second line of an entry header, usually organization and dates.
            _apply_subheader(current, text)
            current["_meta_done"] = True
            continue
        current = _new_entry()
        entries.append(current)
        _apply_title(current, text)
        previous_was_bullet = False
    for entry in entries:
        entry.pop("_meta_done", None)
        if not entry["title"] and entry["bullets"]:
            entry["title"] = entry["bullets"].pop(0)["text"]
    return entries


def _new_entry():
    return {"id": new_id(), "title": "", "organization": "", "dates": "", "bullets": []}


def _apply_title(entry, text):
    date_match = DATE_RE.search(text)
    if date_match:
        entry["dates"] = date_match.group(0).strip()
        text = (text[:date_match.start()] + text[date_match.end():]).strip(" |,-–—")
    entry["title"] = text


def _apply_subheader(entry, text):
    date_match = DATE_RE.search(text)
    if date_match:
        entry["dates"] = date_match.group(0).strip()
        text = (text[:date_match.start()] + text[date_match.end():]).strip(" |,-–—")
    entry["organization"] = text


def _parse_skills(lines):
    skills = []
    for line in lines:
        category = ""
        body = _strip_bullet(line)
        if ":" in body:
            label, rest = body.split(":", 1)
            if 0 < len(label) <= 40 and rest.strip():
                category, body = label.strip(), rest.strip()
        for part in re.split(r"[,;|]", body):
            name = part.strip()
            if name:
                skills.append({"id": new_id(), "name": name, "category": category})
    return skills


def _parse_links(lines):
    links = []
    for line in lines:
        text = _strip_bullet(line)
        found = URL_RE.findall(text)
        if found:
            for url in found:
                label = URL_RE.sub("", text).strip(" |,:-")
                links.append({"id": new_id(), "label": label, "url": url.strip(".,;")})
        else:
            links.append({"id": new_id(), "label": text, "url": ""})
    return links


def parse_upload(filename: str, data: bytes) -> dict:
    """Full pipeline for an uploaded resume: validate, extract text, parse, keep the original text."""
    file_type = validate_upload(filename, data)
    text = extract_document_text(filename, data)
    resume = parse_resume_text(text)
    resume["source_file_type"] = file_type
    return resume
