"""Rule-based, offline resume suggestions.

Suggestions are proposals only. Nothing changes the resume until the user accepts (with optional edits).
The engine never adds skills, employers, dates, numbers, responsibilities or achievements.
"""

import hashlib
import re

from .resume_model import ENTRY_SECTIONS, SECTION_TITLES, sections_text
from .skills import find_skills

WEAK_OPENERS = [
    ("responsible for", "Led", "'Responsible for' describes duties rather than actions."),
    ("worked on", "Developed", "'Worked on' is vague about what you did."),
    ("helped", "Contributed to", "'Helped' understates your role and is vague."),
    ("helping", "Contributed to", "'Helping' is vague about the action you took."),
    ("involved in", "Contributed to", "'Involved in' is vague about your role."),
    ("assisted", "Supported", "'Assisted' is vague; name the specific action."),
    ("participated in", "Contributed to", "'Participated in' describes presence rather than contribution."),
    ("tasked with", "Delivered", "'Tasked with' describes an assignment rather than a result."),
]
LONG_WORDS = 32
SHORT_WORDS = 4
REPEAT_THRESHOLD = 3


def _suggestion_id(kind: str, target: dict, original: str) -> str:
    raw = f"{kind}|{target.get('section')}|{target.get('entry_id')}|{target.get('item_id')}|{target.get('field')}|{original}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _make(kind, target, original, proposed, issue, explanation, editable=True):
    return {
        "id": _suggestion_id(kind, target, original),
        "kind": kind,
        "target": target,
        "original": original,
        "proposed": proposed,
        "issue": issue,
        "explanation": explanation,
        "editable": editable,
        "section_title": SECTION_TITLES.get(target.get("section"), target.get("section", "")),
    }


def generate_suggestions(resume_data: dict, requirements: dict | None = None) -> list[dict]:
    """Return a list of suggestion dicts. `requirements` is the JD requirement dict (optional)."""
    suggestions = []

    # Bullets: weak openers, long sentences, short or vague lines, formatting consistency.
    all_bullets = []
    for section in ENTRY_SECTIONS:
        for entry in resume_data.get(section, []):
            for bullet in entry.get("bullets", []):
                all_bullets.append((section, entry["id"], bullet["id"], bullet["text"]))
    punctuation_styles = {text.rstrip()[-1:] for _, _, _, text in all_bullets if text.strip()}

    for section, entry_id, bullet_id, text in all_bullets:
        target = {"section": section, "entry_id": entry_id, "item_id": bullet_id, "field": "text"}
        lowered = text.lower()
        word_count = len(text.split())

        for opener, replacement, why in WEAK_OPENERS:
            if lowered.startswith(opener):
                rest = text[len(opener):].lstrip(" :,-")
                proposed = f"{replacement} {rest}".strip()
                suggestions.append(_make(
                    "weak_opener", target, text, proposed,
                    issue="Vague opening phrase",
                    explanation=f"{why} Check that the new verb matches what you actually did before accepting.",
                ))
                break

        if word_count >= LONG_WORDS:
            suggestions.append(_make(
                "long_sentence", target, text, text,
                issue=f"Long sentence ({word_count} words)",
                explanation="Long bullets are harder to scan. Split or tighten it while keeping every fact.",
            ))
        elif word_count <= SHORT_WORDS:
            suggestions.append(_make(
                "unclear_short", target, text, text,
                issue="Very short bullet",
                explanation="A short bullet may not show the action or outcome. If you can, add the missing detail "
                            "yourself. Nothing is added automatically.",
            ))

        if text.endswith(".") and len(punctuation_styles) > 1:
            suggestions.append(_make(
                "formatting", target, text, text.rstrip(". "),
                issue="Inconsistent punctuation across bullets",
                explanation="Some bullets end with a full stop and others do not. Keep one style throughout.",
            ))

        if not re.search(r"\d", text):
            suggestions.append(_make(
                "add_detail_question", target, text, text,
                issue="No number or measurable detail",
                explanation="If a count, percentage or scale is true, add it yourself. HireSense AI will not invent a "
                            "metric. Leave the text unchanged if none applies.",
            ))

    # Repetitive openings across bullets.
    openers: dict[str, int] = {}
    for _, _, _, text in all_bullets:
        first = text.split()[0].lower() if text.split() else ""
        if first:
            openers[first] = openers.get(first, 0) + 1
    repeated = {word for word, count in openers.items() if count >= REPEAT_THRESHOLD}
    for section, entry_id, bullet_id, text in all_bullets:
        first = text.split()[0].lower() if text.split() else ""
        if first in repeated:
            target = {"section": section, "entry_id": entry_id, "item_id": bullet_id, "field": "text"}
            suggestions.append(_make(
                "repetitive_wording", target, text, text,
                issue=f"Many bullets start with '{first}'",
                explanation="Varying the opening verbs makes achievements easier to read. Edit this bullet if you "
                            "want a different opening.",
            ))

    # Summary clarity.
    summary = resume_data.get("summary", "")
    if summary and len(summary.split()) > 60:
        target = {"section": "summary", "entry_id": None, "item_id": None, "field": "summary"}
        suggestions.append(_make(
            "long_sentence", target, summary, summary,
            issue="Long professional summary",
            explanation="A shorter summary is easier to read. Trim it without removing facts.",
        ))

    # Missing or incomplete sections.
    if not resume_data.get("skills"):
        suggestions.append(_make(
            "missing_section", {"section": "skills", "entry_id": None, "item_id": None, "field": ""}, "", "",
            issue="No Skills section found",
            explanation="Add a Skills section with skills you can support with examples. Nothing is added automatically.",
            editable=False,
        ))

    # Skills listed without any supporting description elsewhere (listed but unsupported).
    described_text = " ".join(
        block["text"] for block in sections_text(resume_data) if block["section"] != "skills"
    )
    described_skills = find_skills(described_text)
    for skill in resume_data.get("skills", []):
        for canonical in find_skills(skill.get("name", "")):
            if canonical not in described_skills:
                target = {"section": "skills", "entry_id": None, "item_id": skill["id"], "field": "name"}
                suggestions.append(_make(
                    "unsupported_skill", target, skill["name"], skill["name"],
                    issue=f"'{canonical}' is listed but not described in any experience or project",
                    explanation="Reviewers often look for a project or work example behind each skill. If you have "
                                "one, add it yourself. Otherwise you may keep the skill as it is.",
                ))

    # Keyword gaps from the JD. Information only: never inserted into the resume.
    if requirements:
        resume_skills = find_skills(" ".join(b["text"] for b in sections_text(resume_data)))
        for term in requirements.get("required", []):
            if term not in resume_skills:
                suggestions.append(_make(
                    "keyword_gap", {"section": None, "entry_id": None, "item_id": None, "field": ""},
                    term, term,
                    issue=f"Required skill '{term}' is not found in the resume",
                    explanation=f"If you have real experience with {term}, describe it in a project or experience "
                                "entry yourself. HireSense AI does not add skills you have not provided.",
                    editable=False,
                ))

    return suggestions


def apply_suggestion(resume_data: dict, suggestion: dict, final_text: str) -> bool:
    """Apply an accepted suggestion with the user's final text. Returns True when the resume changed."""
    from .resume_model import update_bullet, update_item, update_link, set_summary

    target = suggestion.get("target") or {}
    if not target.get("section") or not target.get("field"):
        return False
    text = (final_text or "").strip()
    if not text:
        raise ValueError("The accepted text cannot be empty. Dismiss the suggestion instead.")
    section = target["section"]
    if section == "summary":
        set_summary(resume_data, text)
    elif section in ENTRY_SECTIONS:
        update_bullet(resume_data, section, target["entry_id"], target["item_id"], text)
    elif section == "skills":
        for skill in resume_data["skills"]:
            if skill["id"] == target["item_id"]:
                skill["name"] = text
    elif section == "links":
        update_link(resume_data, target["item_id"], "url", text)
    else:
        update_item(resume_data, section, target["item_id"], text)
    return original_differs(suggestion, text)


def original_differs(suggestion: dict, text: str) -> bool:
    return text != suggestion.get("original", "")
