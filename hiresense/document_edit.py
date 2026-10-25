"""Edit the user's own PDF or DOCX in place.

The original file stays the resume. Only the lines the user changed are replaced, a skill is appended to the
line it belongs to, and a removed skill is taken out of its line. Everything else in the file is left alone.

Changes are found by comparing the original parse with the edited resume. Items that have no place in the
original layout (new entries, new bullets) are reported instead of being guessed into the page.
"""

import io
import os
import re
import shutil
import subprocess
import tempfile

import pymupdf
from docx import Document

from .resume_model import ENTRY_SECTIONS, ITEM_SECTIONS, PERSONAL_FIELDS
from .resume_parser import extract_document_text

PAGE_PIXELS_PER_INCH = 110
MIN_FONT_SIZE = 6.0


def compute_edits(original: dict, edited: dict) -> tuple[list[dict], list[str]]:
    """Return (operations, unsupported). Operations are {"op": "replace", "old", "new"} on whole lines or items."""
    ops: list[dict] = []
    unsupported: list[str] = []

    for field in PERSONAL_FIELDS:
        _diff_text(ops, original["personal"].get(field, ""), edited["personal"].get(field, ""))
    _diff_text(ops, original.get("summary", ""), edited.get("summary", ""))

    for section in ENTRY_SECTIONS:
        original_entries = {entry["id"]: entry for entry in original.get(section, [])}
        for entry in edited.get(section, []):
            source = original_entries.get(entry["id"])
            if source is None:
                unsupported.append(f"New entry in {section}: {entry.get('title') or 'untitled'}")
                continue
            for field in ("title", "organization", "dates"):
                _diff_text(ops, source.get(field, ""), entry.get(field, ""))
            original_bullets = {bullet["id"]: bullet["text"] for bullet in source.get("bullets", [])}
            edited_ids = set()
            for bullet in entry.get("bullets", []):
                edited_ids.add(bullet["id"])
                if bullet["id"] in original_bullets:
                    _diff_text(ops, original_bullets[bullet["id"]], bullet["text"])
                else:
                    unsupported.append(f"New bullet in {section}: {bullet['text'][:60]}")
            for bullet_id, text in original_bullets.items():
                if bullet_id not in edited_ids:
                    ops.append({"op": "replace", "old": text, "new": ""})

    for section in ITEM_SECTIONS:
        original_items = {item["id"]: item["text"] for item in original.get(section, [])}
        edited_ids = set()
        for item in edited.get(section, []):
            edited_ids.add(item["id"])
            if item["id"] in original_items:
                _diff_text(ops, original_items[item["id"]], item["text"])
            else:
                unsupported.append(f"New item in {section}: {item['text'][:60]}")
        for item_id, text in original_items.items():
            if item_id not in edited_ids:
                ops.append({"op": "replace", "old": text, "new": ""})

    _skill_edits(ops, unsupported, original, edited)
    return ops, unsupported


def _diff_text(ops: list[dict], old: str, new: str) -> None:
    old, new = (old or "").strip(), (new or "").strip()
    if old == new or not old:
        return
    ops.append({"op": "replace", "old": old, "new": new})


def _skill_edits(ops, unsupported, original, edited) -> None:
    original_skills = {skill["id"]: skill for skill in original.get("skills", [])}
    edited_ids = set()
    new_skills = []
    for skill in edited.get("skills", []):
        edited_ids.add(skill["id"])
        source = original_skills.get(skill["id"])
        if source is None:
            new_skills.append(skill)
            continue
        if source["name"] != skill["name"]:
            ops.append({"op": "token", "old": source["name"], "new": skill["name"]})
    for skill_id, source in original_skills.items():
        if skill_id not in edited_ids:
            ops.append({"op": "token", "old": source["name"], "new": ""})

    # A new skill is written after the last skill that is still on the resume, in the same group when possible.
    surviving = [original_skills[skill_id] for skill_id in original_skills if skill_id in edited_ids]
    for skill in new_skills:
        if not skill["name"]:
            continue
        same_group = [item for item in surviving if item.get("category", "") == skill.get("category", "")]
        candidates = same_group or surviving
        if not candidates:
            unsupported.append(f"New skill: {skill['name']}")
            continue
        ops.append({"op": "append", "anchor": candidates[-1]["name"], "new": skill["name"]})


def _line_containing(lines: list[str], token: str) -> str | None:
    pattern = re.compile(rf"(?<![A-Za-z0-9+#]){re.escape(token)}(?![A-Za-z0-9+#])")
    for line in lines:
        if pattern.search(line):
            return line
    return None


def resolve_operations(original_text: str, ops: list[dict]) -> list[dict]:
    """Turn skill changes into whole-line replacements. Several changes to one line are combined."""
    lines = original_text.splitlines()
    working: dict[str, str] = {}
    resolved = []

    def line_for(token: str):
        line = _line_containing(lines, token)
        return line

    for op in ops:
        if op["op"] == "replace":
            resolved.append(op)
            continue
        if op["op"] == "token":
            line = line_for(op["old"])
            if line is None:
                resolved.append({"op": "replace", "old": op["old"], "new": op["new"], "missing": True})
                continue
            current = working.get(line, line)
            if op["new"]:
                updated = current.replace(op["old"], op["new"], 1)
            else:
                updated = _remove_token(current, op["old"])
            working[line] = updated
        elif op["op"] == "append":
            line = line_for(op["anchor"])
            if line is None:
                resolved.append({"op": "replace", "old": op["anchor"], "new": op["anchor"], "missing": True})
                continue
            current = working.get(line, line)
            working[line] = current.replace(op["anchor"], f"{op['anchor']}, {op['new']}", 1)

    for old, new in working.items():
        if old != new:
            resolved.append({"op": "replace", "old": old, "new": new})
    return resolved


def _remove_token(line: str, token: str) -> str:
    pattern = rf"(?<![A-Za-z0-9+#]){re.escape(token)}(?![A-Za-z0-9+#])"
    if re.search(rf",\s*{pattern}", line):
        return re.sub(rf",\s*{pattern}", "", line, count=1)
    return re.sub(rf"{pattern}\s*,\s*", "", line, count=1).strip()


def apply_to_file(filename: str, file_bytes: bytes, original: dict, edited: dict) -> tuple[bytes, list[str], list[str]]:
    """Apply the edits to the original file. Returns (new_bytes, failed, unsupported)."""
    ops, unsupported = compute_edits(original, edited)
    original_text = extract_document_text(filename, file_bytes)
    resolved = resolve_operations(original_text, ops)
    if filename.lower().endswith(".pdf"):
        return _apply_pdf(file_bytes, resolved, unsupported)
    return _apply_docx(file_bytes, resolved, unsupported)


# ---------- PDF ----------

def _find_words(page: pymupdf.Page, tokens: list[str]):
    words = page.get_text("words")
    texts = [word[4] for word in words]
    size = len(tokens)
    for start in range(len(texts) - size + 1):
        if texts[start:start + size] == tokens:
            return words[start:start + size]
    return None


def _font_for(page: pymupdf.Page, box: pymupdf.Rect) -> tuple[str, float]:
    """Pick a base font that matches the original text (serif or sans, bold or regular) and its size."""
    best = None
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                span_box = pymupdf.Rect(span["bbox"])
                if span_box.intersects(box):
                    best = span
                    break
            if best:
                break
        if best:
            break
    if not best:
        return "helv", 10.0
    flags = best["flags"]
    serif = bool(flags & 4) or "Times" in best["font"] or "Serif" in best["font"]
    bold = bool(flags & 16) or "Bold" in best["font"]
    if serif:
        return ("tibo" if bold else "tiro"), best["size"]
    return ("hebo" if bold else "helv"), best["size"]


def _widen_if_line_is_free(page: pymupdf.Page, box: pymupdf.Rect) -> pymupdf.Rect:
    """Let a longer replacement use the rest of its line, as long as nothing else sits on that line.

    This keeps the original font size instead of shrinking the new text to fit the old words.
    """
    right_margin = page.rect.x1 - 40
    for word in page.get_text("words"):
        word_box = pymupdf.Rect(word[:4])
        same_line = abs(word_box.y0 - box.y0) < 2 and abs(word_box.y1 - box.y1) < 2
        if same_line and word_box.x0 > box.x1 - 1:
            return box  # something else follows on this line (for example a date), so keep the box as it is
    return pymupdf.Rect(box.x0, box.y0, max(box.x1, right_margin), box.y1)


def _replace_on_page(page: pymupdf.Page, old: str, new: str) -> bool:
    tokens = old.split()
    if not tokens:
        return False
    chunk = _find_words(page, tokens)
    if not chunk:
        return False
    rects = [pymupdf.Rect(word[:4]) for word in chunk]
    box = pymupdf.Rect(rects[0])
    for rect in rects[1:]:
        box |= rect
    fontname, fontsize = _font_for(page, box)
    box = _widen_if_line_is_free(page, box)

    for rect in rects:
        page.add_redact_annot(rect, fill=(1, 1, 1))
    page.apply_redactions()

    text = new.strip()
    if not text:
        return True
    size = fontsize
    while size >= MIN_FONT_SIZE:
        result = page.insert_textbox(box, text, fontname=fontname, fontsize=size, color=(0, 0, 0), align=0)
        if result >= 0:
            return True
        size -= 0.25
    # Could not fit at the smallest size: put the text back so nothing is lost.
    page.insert_textbox(box, old, fontname=fontname, fontsize=MIN_FONT_SIZE, color=(0, 0, 0), align=0)
    return False


def _apply_pdf(file_bytes: bytes, ops: list[dict], unsupported: list[str]) -> tuple[bytes, list[str], list[str]]:
    document = pymupdf.open(stream=file_bytes, filetype="pdf")
    failed = []
    try:
        for op in ops:
            if op["op"] != "replace" or op.get("missing"):
                failed.append(op.get("old", "")[:80])
                continue
            done = False
            for page in document:
                if _replace_on_page(page, op["old"], op["new"]):
                    done = True
                    break
            if not done:
                failed.append(op["old"][:80])
        return document.tobytes(garbage=3, deflate=True), failed, unsupported
    finally:
        document.close()


def render_pdf_pages(file_bytes: bytes) -> list[bytes]:
    """PNG image of each page, for the preview."""
    document = pymupdf.open(stream=file_bytes, filetype="pdf")
    try:
        pages = []
        for page in document:
            pixmap = page.get_pixmap(dpi=PAGE_PIXELS_PER_INCH)
            pages.append(pixmap.tobytes("png"))
        return pages
    finally:
        document.close()


# ---------- DOCX ----------

def _apply_docx(file_bytes: bytes, ops: list[dict], unsupported: list[str]) -> tuple[bytes, list[str], list[str]]:
    document = Document(io.BytesIO(file_bytes))
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    failed = []
    for op in ops:
        if op["op"] != "replace" or op.get("missing"):
            failed.append(op.get("old", "")[:80])
            continue
        target = None
        for paragraph in paragraphs:
            if _normalize(paragraph.text) == _normalize(op["old"]):
                target = paragraph
                break
        if target is None:
            failed.append(op["old"][:80])
            continue
        _set_paragraph_text(target, op["new"])
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue(), failed, unsupported


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _set_paragraph_text(paragraph, text: str) -> None:
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for run in runs[1:]:
        run.text = ""


def docx_preview_lines(file_bytes: bytes) -> list[str]:
    """Paragraph text of a Word file, for an approximate preview (no Word or LibreOffice needed)."""
    document = Document(io.BytesIO(file_bytes))
    return [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]


# ---------- Word page preview through LibreOffice ----------

LIBREOFFICE_CANDIDATES = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
    "libreoffice",
)


def find_libreoffice() -> str | None:
    for candidate in LIBREOFFICE_CANDIDATES:
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def docx_to_pdf(docx_bytes: bytes) -> bytes:
    """Convert a Word file to PDF with LibreOffice so the preview shows real Word pages."""
    binary = find_libreoffice()
    if not binary:
        raise RuntimeError("LibreOffice is not installed")
    with tempfile.TemporaryDirectory() as folder:
        source = os.path.join(folder, "resume.docx")
        with open(source, "wb") as handle:
            handle.write(docx_bytes)
        profile = f"-env:UserInstallation=file://{folder}/profile"
        subprocess.run(
            [binary, profile, "--headless", "--convert-to", "pdf", "--outdir", folder, source],
            check=True, capture_output=True, timeout=180,
        )
        output = os.path.join(folder, "resume.pdf")
        if not os.path.exists(output):
            raise RuntimeError("LibreOffice did not produce a PDF")
        with open(output, "rb") as handle:
            return handle.read()
