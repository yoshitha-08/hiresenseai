"""Deterministic, explainable resume-to-JD matching.

Evidence strength per requirement (best found wins; each requirement counts once):
- explicit    : listed in the Skills section                    -> 1.0
- contextual  : found in experience, projects, education, etc.  -> 1.0
- weak        : found only in interests, links or unclassified  -> 0.5
- missing     : not found in the supplied resume                -> 0.0
A missing item means "not found in this resume", not proof the candidate lacks the skill.

Categories and default weights (renormalized when a category does not apply to the JD):
  required skills 45 | experience & practical evidence 25 | preferred skills 15 |
  education & qualifications 10 | other relevant keywords 5
"""

from copy import deepcopy

import re

from .jd_parser import QUALIFICATION_TERMS, extract_requirements
from .resume_model import SECTION_TITLES, sections_text
from .skills import contains_term, find_skills

DEFAULT_WEIGHTS = {
    "required": 45.0,
    "experience": 25.0,
    "preferred": 15.0,
    "education": 10.0,
    "other": 5.0,
}
CATEGORY_LABELS = {
    "required": "Required skills and evidence",
    "experience": "Relevant experience and projects",
    "preferred": "Preferred skills",
    "education": "Education and qualifications",
    "other": "Other relevant keywords",
}
STRENGTH_SCORE = {"explicit": 1.0, "contextual": 1.0, "weak": 0.5, "missing": 0.0}
STRENGTH_RANK = {"missing": 0, "weak": 1, "contextual": 2, "explicit": 3}
MAIN_SECTIONS = {"summary", "experience", "internships", "projects", "education", "certifications", "achievements"}
PRACTICAL_SECTIONS = {"experience", "internships", "projects"}
PRACTICAL_REFERENCE_COUNT = 3  # three relevant entries earn full credit for this category
EDUCATION_SECTIONS = {"education", "certifications", "summary"}


def _strength_for_section(section: str) -> str:
    if section == "skills":
        return "explicit"
    if section in MAIN_SECTIONS:
        return "contextual"
    return "weak"


def _term_in_block(term: str, text: str) -> bool:
    """True when a canonical skill (or any of its synonyms) appears in the text."""
    return term in find_skills(text)


def _jd_term_strength(term: str, blocks: list[dict]) -> tuple[str, list[str]]:
    best, where = "missing", []
    for block in blocks:
        if _term_in_block(term, block["text"]):
            strength = _strength_for_section(block["section"])
            label = SECTION_TITLES.get(block["section"], block["section"])
            if label not in where:
                where.append(label)
            if STRENGTH_RANK[strength] > STRENGTH_RANK[best]:
                best = strength
    return best, where


def analyze_match(resume_data: dict, jd_text: str, weights: dict | None = None) -> dict:
    """Score a resume against a JD. Pure function: identical inputs always give identical output."""
    weights = dict(DEFAULT_WEIGHTS if weights is None else weights)
    requirements = extract_requirements(jd_text)
    blocks = sections_text(resume_data)
    full_text = " \n ".join(block["text"] for block in blocks)

    term_results = {}
    for term in sorted(set(requirements["required"]) | set(requirements["preferred"])):
        strength, where = _jd_term_strength(term, blocks)
        term_results[term] = {"strength": strength, "sections": where}

    def category_ratio(terms):
        if not terms:
            return None, []
        values = [STRENGTH_SCORE[term_results[t]["strength"]] for t in terms]
        return sum(values) / len(terms), values

    required_ratio, _ = category_ratio(requirements["required"])
    preferred_ratio, _ = category_ratio(requirements["preferred"])

    # Experience and practical evidence: relevant entries (projects, internships, experience) that mention
    # at least one JD skill with non-weak evidence. Duplicate mentions inside one entry count once.
    jd_terms = set(requirements["required"]) | set(requirements["preferred"])
    relevant_entries = []
    practical_total = 0
    for section in PRACTICAL_SECTIONS:
        for entry in resume_data.get(section, []):
            practical_total += 1
            entry_text = " ".join([entry.get("title", ""), entry.get("organization", "")] +
                                  [b.get("text", "") for b in entry.get("bullets", [])])
            matched = {t for t in jd_terms if _term_in_block(t, entry_text)}
            if matched:
                relevant_entries.append({
                    "section": SECTION_TITLES[section],
                    "title": entry.get("title", "") or "(untitled entry)",
                    "matched_terms": sorted(matched),
                })
    experience_ratio = None
    if jd_terms:
        experience_ratio = min(1.0, len(relevant_entries) / PRACTICAL_REFERENCE_COUNT)

    # Education and qualifications: JD qualification labels found in education, certifications or summary.
    qual_text = " \n ".join(b["text"] for b in blocks if b["section"] in EDUCATION_SECTIONS)
    education_matched, education_missing = [], []
    for label in requirements["qualifications"]:
        terms = QUALIFICATION_TERMS[label]
        if any(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", qual_text.lower()) for term in terms):
            education_matched.append(label)
        else:
            education_missing.append(label)
    education_ratio = None
    if requirements["qualifications"]:
        education_ratio = len(education_matched) / len(requirements["qualifications"])

    # Other keywords: presence only (never counted per mention).
    keyword_matched = [k for k in requirements["keywords"] if contains_term(full_text, k)]
    keyword_missing = [k for k in requirements["keywords"] if k not in keyword_matched]
    other_ratio = None
    if requirements["keywords"]:
        other_ratio = len(keyword_matched) / len(requirements["keywords"])

    ratios = {
        "required": required_ratio,
        "experience": experience_ratio,
        "preferred": preferred_ratio,
        "education": education_ratio,
        "other": other_ratio,
    }
    applicable = {key: value for key, value in ratios.items() if value is not None}
    total_weight = sum(weights[key] for key in applicable)

    categories = []
    score = 0.0
    for key in ("required", "experience", "preferred", "education", "other"):
        ratio = ratios[key]
        applies = ratio is not None
        effective = (weights[key] / total_weight * 100.0) if applies and total_weight else 0.0
        points = effective * ratio if applies else 0.0
        score += points
        categories.append({
            "key": key,
            "label": CATEGORY_LABELS[key],
            "weight": weights[key],
            "applicable": applies,
            "ratio": round(ratio, 4) if applies else None,
            "effective_weight": round(effective, 2),
            "points": round(points, 2),
        })

    score = max(0.0, min(100.0, round(score, 1)))
    missing_required = [t for t in requirements["required"] if term_results[t]["strength"] == "missing"]
    missing_preferred = [t for t in requirements["preferred"] if term_results[t]["strength"] == "missing"]
    uncertain = [t for t, info in term_results.items() if info["strength"] == "weak"]

    matched_terms = {
        term: {"strength": info["strength"], "sections": info["sections"],
               "requirement": "required" if term in requirements["required"] else "preferred"}
        for term, info in term_results.items() if info["strength"] != "missing"
    }

    improvements = []
    required_effective = next(c["effective_weight"] for c in categories if c["key"] == "required")
    if missing_required and required_effective:
        per_item = required_effective / len(requirements["required"])
        for term in missing_required:
            improvements.append({
                "skill": term,
                "estimate_points": round(per_item, 1),
                "note": "Estimate only: if real evidence for this skill is added, the score could rise by about "
                        "this many points. Results are not guaranteed.",
            })

    years_note = None
    if requirements["years"]:
        years_note = (f"The JD asks for {max(requirements['years'])}+ years of experience. Durations are not "
                      "inferred from dates, so this is shown as a note and not scored.")

    notes = []
    if not jd_terms and not requirements["qualifications"] and not requirements["keywords"]:
        notes.append("The job description contains no recognizable requirements, so no fair score can be calculated.")
    notes.append("This is a compatibility estimate for this resume and job description. It does not predict "
                 "shortlisting, interviews, or employment.")

    return {
        "score": score,
        "insufficient_signal": not applicable,
        "weights": weights,
        "categories": categories,
        "matched_terms": matched_terms,
        "missing_required": missing_required,
        "missing_preferred": missing_preferred,
        "uncertain_terms": uncertain,
        "relevant_entries": relevant_entries,
        "practical_entry_count": practical_total,
        "education": {"matched": education_matched, "missing": education_missing},
        "keywords": {"matched": keyword_matched, "missing": keyword_missing},
        "years_note": years_note,
        "improvements": improvements,
        "requirements": requirements,
        "notes": notes,
    }


def compare_results(previous: dict, updated: dict) -> dict:
    """Recalculation comparison. The score change is simply updated minus previous."""
    prev_terms = previous.get("matched_terms", {})
    new_terms = updated.get("matched_terms", {})
    newly_matched = sorted(t for t in new_terms if t not in prev_terms)
    lost_evidence = sorted(t for t in prev_terms if t not in new_terms)
    still_missing = sorted(set(updated.get("missing_required", [])) | set(updated.get("missing_preferred", [])))
    change = round(updated["score"] - previous["score"], 1)
    return {
        "previous_score": previous["score"],
        "updated_score": updated["score"],
        "score_change": change,
        "newly_matched": newly_matched,
        "lost_evidence": lost_evidence,
        "still_missing": still_missing,
        "updated_categories": deepcopy(updated["categories"]),
    }
