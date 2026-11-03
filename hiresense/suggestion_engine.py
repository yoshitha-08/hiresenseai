"""Rule-based, offline resume suggestions.

Suggestions are proposals only. Nothing changes the resume until the user accepts (with optional edits).
The engine never adds skills, employers, dates, numbers, responsibilities or achievements.
"""

import hashlib
import re

from . import config
from .llm_rewrite import is_available, rewrite_bullet
from .resume_model import ENTRY_SECTIONS, SECTION_TITLES, sections_text
from .jd_parser import SOFT_SKILLS
from .skills import find_skills

def _suggestion_id(kind: str, target: dict, original: str, proposed: str = "") -> str:
    raw = f"{kind}|{target.get('section')}|{target.get('entry_id')}|{target.get('item_id')}|{target.get('field')}|{original}|{proposed}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _make(kind, target, original, proposed, issue, explanation, editable=True):
    return {
        "id": _suggestion_id(kind, target, original, proposed),
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
    """Suggestions only for technical job skills missing from the resume, plus optional Gemini rewrites.

    Rule-based style checks were removed on purpose. Soft skills are never suggested.
    """
    if not requirements:
        return []
    suggestions = []
    resume_skills = find_skills(" ".join(b["text"] for b in sections_text(resume_data)))
    wanted = [(term, "required") for term in requirements.get("required", [])]
    wanted += [(term, "preferred") for term in requirements.get("preferred", []) if term not in requirements.get("required", [])]
    for term, level in wanted:
        if term in resume_skills or term in SOFT_SKILLS:
            continue
        suggestions.append(_make(
            "keyword_gap", {"section": "skills", "entry_id": None, "item_id": None, "field": "name"},
            "", term,
            issue=f"{level.capitalize()} skill '{term}' is in the job description but not in your resume",
            explanation=f"Add {term} to your Skills section only if you know it.",
        ))
    return suggestions


LLM_BULLET_LIMIT = 12


def _llm_bullet_suggestions(resume_data: dict, requirements: dict) -> list[dict]:
    """Local-model rewrites for experience and project bullets. Only checked rewrites become suggestions."""
    jd_terms = sorted(set(requirements.get("required", [])) | set(requirements.get("preferred", [])))
    jd_text = requirements.get("text", "")
    suggestions = []
    bullets = [(section, entry["id"], bullet["id"], bullet["text"])
               for section in ("experience", "projects")
               for entry in resume_data.get(section, [])
               for bullet in entry.get("bullets", [])
               if len(bullet["text"].split()) >= 4]
    for section, entry_id, bullet_id, text in bullets[:LLM_BULLET_LIMIT]:
        evidenced = sorted(find_skills(text) & set(jd_terms))
        rewrite = rewrite_bullet(text, evidenced, jd_text, requirements.get("requirement_lines", []))
        if not rewrite:
            continue
        target = {"section": section, "entry_id": entry_id, "item_id": bullet_id, "field": "text"}
        suggestions.append(_make(
            "llm_rewrite", target, text, rewrite,
            issue="Stronger wording for this job",
            explanation="Reworded by a local model using only facts already in this bullet. Check that it "
                        "matches what you did before you apply it.",
        ))
    return suggestions


def apply_suggestion(resume_data: dict, suggestion: dict, final_text: str) -> bool:
    """Apply an accepted suggestion with the user's final text. Returns True when the resume changed."""
    from .resume_model import add_skill, skill_category_for, update_bullet, update_item, update_link, set_summary

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
        if target.get("item_id") is None:
            add_skill(resume_data, text, skill_category_for(resume_data, text))
        else:
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
