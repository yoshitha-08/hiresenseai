"""The structured resume object: the single source of truth for editor, preview, matching and downloads.

Every repeatable item has a stable random ID, so edits always target the right entry after reruns,
reorders, additions and deletions.
"""

import copy
import uuid

MAX_FIELD_LENGTH = 10000  # long bullets come from PDFs that lose line breaks

# Sections made of entries (title / organization / dates / bullets).
ENTRY_SECTIONS = ("experience", "internships", "education", "projects", "certifications")
ENTRY_FIELDS = ("title", "organization", "dates", "location", "link", "field_of_study", "grade")
ENTRY_DEFAULTS = {"location": "", "link": "", "field_of_study": "", "grade": ""}
# Sections made of simple items.
ITEM_SECTIONS = ("achievements", "interests", "unclassified")
SECTION_ORDER = (
    "summary", "experience", "internships", "education", "skills", "projects",
    "certifications", "achievements", "interests", "links", "unclassified",
)
PERSONAL_FIELDS = ("name", "role", "email", "phone", "location")
SECTION_TITLES = {
    "summary": "Professional Summary",
    "experience": "Work Experience",
    "internships": "Internships",
    "education": "Education",
    "skills": "Skills",
    "projects": "Projects",
    "certifications": "Certifications",
    "achievements": "Achievements",
    "interests": "Interests",
    "links": "Professional Links",
    "unclassified": "Additional Content",
}


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def empty_resume() -> dict:
    data = {
        "personal": {field: "" for field in PERSONAL_FIELDS},
        "summary": "",
        "skills": [],
        "links": [],
        "hidden_sections": [],
    }
    for section in ENTRY_SECTIONS:
        data[section] = []
    for section in ITEM_SECTIONS:
        data[section] = []
    return data


def _clean(value) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_FIELD_LENGTH:
        raise ValueError(f"Text is too long (maximum {MAX_FIELD_LENGTH} characters).")
    return text


def _find_index(items: list, item_id: str) -> int:
    for index, item in enumerate(items):
        if item.get("id") == item_id:
            return index
    raise KeyError(f"Item {item_id} was not found.")


def _require_section(section: str, allowed: tuple) -> None:
    if section not in allowed:
        raise ValueError(f"'{section}' does not support this operation.")


def copy_resume(data: dict) -> dict:
    return copy.deepcopy(data)


# ---------- personal details and summary ----------

def set_personal(data: dict, field: str, value: str) -> dict:
    if field not in PERSONAL_FIELDS:
        raise ValueError(f"Unknown personal field: {field}")
    data["personal"][field] = _clean(value)
    return data


def set_summary(data: dict, value: str) -> dict:
    data["summary"] = _clean(value)
    return data


def set_section_visible(data: dict, section: str, visible: bool) -> dict:
    """Hidden sections stay in the data but are left out of the preview, downloads and matching."""
    if section not in SECTION_ORDER:
        raise ValueError(f"Unknown section: {section}")
    hidden = [name for name in data.get("hidden_sections", []) if name != section]
    if not visible:
        hidden.append(section)
    data["hidden_sections"] = hidden
    return data


def normalize_resume(data: dict) -> dict:
    """Fill in fields added after a resume was saved, so older data keeps working."""
    data.setdefault("hidden_sections", [])
    data.setdefault("personal", {})
    for field in PERSONAL_FIELDS:
        data["personal"].setdefault(field, "")
    for section in ENTRY_SECTIONS:
        for entry in data.setdefault(section, []):
            for key, default in ENTRY_DEFAULTS.items():
                entry.setdefault(key, default)
    return data


# ---------- entry sections ----------

def add_entry(data: dict, section: str, title: str = "") -> str:
    _require_section(section, ENTRY_SECTIONS)
    entry_id = new_id()
    data[section].append(
        {"id": entry_id, "title": _clean(title), "organization": "", "dates": "", "bullets": [],
         **ENTRY_DEFAULTS}
    )
    return entry_id


def update_entry(data: dict, section: str, entry_id: str, field: str, value: str) -> dict:
    _require_section(section, ENTRY_SECTIONS)
    if field not in ENTRY_FIELDS:
        raise ValueError(f"Unknown field: {field}")
    entry = data[section][_find_index(data[section], entry_id)]
    entry[field] = _clean(value)
    return data


def delete_entry(data: dict, section: str, entry_id: str) -> dict:
    _require_section(section, ENTRY_SECTIONS)
    del data[section][_find_index(data[section], entry_id)]
    return data


def move_entry(data: dict, section: str, entry_id: str, direction: int) -> dict:
    _require_section(section, ENTRY_SECTIONS + ITEM_SECTIONS)
    _move(data[section], entry_id, direction)
    return data


def add_bullet(data: dict, section: str, entry_id: str, text: str = "") -> str:
    _require_section(section, ENTRY_SECTIONS)
    entry = data[section][_find_index(data[section], entry_id)]
    bullet_id = new_id()
    entry["bullets"].append({"id": bullet_id, "text": _clean(text)})
    return bullet_id


def update_bullet(data: dict, section: str, entry_id: str, bullet_id: str, text: str) -> dict:
    _require_section(section, ENTRY_SECTIONS)
    entry = data[section][_find_index(data[section], entry_id)]
    entry["bullets"][_find_index(entry["bullets"], bullet_id)]["text"] = _clean(text)
    return data


def delete_bullet(data: dict, section: str, entry_id: str, bullet_id: str) -> dict:
    _require_section(section, ENTRY_SECTIONS)
    entry = data[section][_find_index(data[section], entry_id)]
    del entry["bullets"][_find_index(entry["bullets"], bullet_id)]
    return data


def move_bullet(data: dict, section: str, entry_id: str, bullet_id: str, direction: int) -> dict:
    _require_section(section, ENTRY_SECTIONS)
    entry = data[section][_find_index(data[section], entry_id)]
    _move(entry["bullets"], bullet_id, direction)
    return data


# ---------- simple item sections ----------

def add_item(data: dict, section: str, text: str = "") -> str:
    _require_section(section, ITEM_SECTIONS)
    item_id = new_id()
    data[section].append({"id": item_id, "text": _clean(text)})
    return item_id


def update_item(data: dict, section: str, item_id: str, text: str) -> dict:
    _require_section(section, ITEM_SECTIONS)
    data[section][_find_index(data[section], item_id)]["text"] = _clean(text)
    return data


def delete_item(data: dict, section: str, item_id: str) -> dict:
    _require_section(section, ITEM_SECTIONS)
    del data[section][_find_index(data[section], item_id)]
    return data


def move_item(data: dict, section: str, item_id: str, direction: int) -> dict:
    _require_section(section, ITEM_SECTIONS)
    _move(data[section], item_id, direction)
    return data


# ---------- skills and links (structured items) ----------

def add_skill(data: dict, name: str, category: str = "") -> str:
    skill_id = new_id()
    data["skills"].append({"id": skill_id, "name": _clean(name), "category": _clean(category)})
    return skill_id


def update_skill(data: dict, skill_id: str, field: str, value: str) -> dict:
    if field not in ("name", "category"):
        raise ValueError(f"Unknown skill field: {field}")
    data["skills"][_find_index(data["skills"], skill_id)][field] = _clean(value)
    return data


def delete_skill(data: dict, skill_id: str) -> dict:
    del data["skills"][_find_index(data["skills"], skill_id)]
    return data


def move_skill(data: dict, skill_id: str, direction: int) -> dict:
    _move(data["skills"], skill_id, direction)
    return data


def add_link(data: dict, label: str = "", url: str = "") -> str:
    link_id = new_id()
    data["links"].append({"id": link_id, "label": _clean(label), "url": _clean(url)})
    return link_id


def update_link(data: dict, link_id: str, field: str, value: str) -> dict:
    if field not in ("label", "url"):
        raise ValueError(f"Unknown link field: {field}")
    data["links"][_find_index(data["links"], link_id)][field] = _clean(value)
    return data


def delete_link(data: dict, link_id: str) -> dict:
    del data["links"][_find_index(data["links"], link_id)]
    return data


def move_link(data: dict, link_id: str, direction: int) -> dict:
    _move(data["links"], link_id, direction)
    return data


# ---------- helpers ----------

def _move(items: list, item_id: str, direction: int) -> None:
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 or 1")
    index = _find_index(items, item_id)
    target = index + direction
    if 0 <= target < len(items):
        items[index], items[target] = items[target], items[index]


def sections_text(data: dict) -> list[dict]:
    """Flatten the resume into labelled text blocks for matching and suggestions.

    Each block: {"section", "entry_id", "item_id", "text"}.
    """
    blocks = []
    hidden = set(data.get("hidden_sections", []))
    if data.get("summary") and "summary" not in hidden:
        blocks.append({"section": "summary", "entry_id": None, "item_id": None, "text": data["summary"]})
    for section in ENTRY_SECTIONS:
        if section in hidden:
            continue
        for entry in data.get(section, []):
            header = " ".join(part for part in (entry.get("title", ""), entry.get("organization", "")) if part)
            if header:
                blocks.append({"section": section, "entry_id": entry["id"], "item_id": None, "text": header})
            for bullet in entry.get("bullets", []):
                if bullet.get("text"):
                    blocks.append({"section": section, "entry_id": entry["id"], "item_id": bullet["id"],
                                   "text": bullet["text"]})
    for skill in data.get("skills", []) if "skills" not in hidden else []:
        text = " ".join(part for part in (skill.get("category", ""), skill.get("name", "")) if part)
        if text:
            blocks.append({"section": "skills", "entry_id": None, "item_id": skill["id"], "text": text})
    for section in ITEM_SECTIONS:
        if section in hidden:
            continue
        for item in data.get(section, []):
            if item.get("text"):
                blocks.append({"section": section, "entry_id": None, "item_id": item["id"], "text": item["text"]})
    for link in data.get("links", []) if "links" not in hidden else []:
        text = f'{link.get("label", "")} {link.get("url", "")}'.strip()
        if text:
            blocks.append({"section": "links", "entry_id": None, "item_id": link["id"], "text": text})
    return blocks
