import pytest

from hiresense import resume_model as rm
from hiresense.jd_parser import extract_requirements
from hiresense.resume_parser import parse_resume_text
from hiresense.suggestion_engine import apply_suggestion, generate_suggestions


def _gap_requirements(*terms):
    return {"required": list(terms), "preferred": [], "qualifications": [], "years": [], "keywords": [], "text": ""}


def test_no_rule_based_suggestions_without_a_job_description():
    resume = rm.empty_resume()
    entry = rm.add_entry(resume, "experience", "Analyst")
    rm.add_bullet(resume, "experience", entry, "Responsible for weekly reports")
    assert generate_suggestions(resume) == []
    assert generate_suggestions(resume, _gap_requirements()) == []


def test_missing_technical_skill_is_suggested_and_applied_to_skills_only():
    resume = rm.empty_resume()
    entry = rm.add_entry(resume, "projects", "Tool")
    rm.add_bullet(resume, "projects", entry, "Built a tool for the team")
    before_bullets = list(resume["projects"][0]["bullets"])
    gap = next(s for s in generate_suggestions(resume, _gap_requirements("Kubernetes")) if s["kind"] == "keyword_gap")
    assert gap["editable"] is True
    assert gap["target"]["section"] == "skills"
    assert gap["proposed"] == "Kubernetes"
    assert gap["explanation"] == "Add Kubernetes to your Skills section only if you know it."
    assert apply_suggestion(resume, gap, "Kubernetes")
    assert [skill["name"] for skill in resume["skills"]] == ["Kubernetes"]
    assert resume["projects"][0]["bullets"] == before_bullets


def test_skill_already_in_resume_is_not_suggested():
    resume = rm.empty_resume()
    rm.add_skill(resume, "Kubernetes")
    assert generate_suggestions(resume, _gap_requirements("Kubernetes")) == []


def test_soft_skills_are_never_suggested():
    requirements = extract_requirements("Required: Python, communication skills, teamwork and leadership with SQL.")
    gaps = [s["proposed"] for s in generate_suggestions(rm.empty_resume(), requirements)]
    assert "Python" in gaps and "SQL" in gaps
    assert not {"Communication", "Teamwork", "Leadership"} & set(gaps)


def test_empty_accepted_skill_text_is_rejected():
    resume = rm.empty_resume()
    gap = next(s for s in generate_suggestions(resume, _gap_requirements("Docker")) if s["kind"] == "keyword_gap")
    with pytest.raises(ValueError):
        apply_suggestion(resume, gap, "   ")


def test_editor_add_edit_delete_reorder_entries_with_stable_ids():
    resume = rm.empty_resume()
    first = rm.add_entry(resume, "experience", "First role")
    second = rm.add_entry(resume, "experience", "Second role")
    rm.update_entry(resume, "experience", second, "organization", "Acme")
    rm.move_entry(resume, "experience", second, -1)
    assert [e["id"] for e in resume["experience"]] == [second, first]
    assert resume["experience"][0]["organization"] == "Acme"
    rm.update_entry(resume, "experience", first, "title", "Renamed")
    assert resume["experience"][1]["title"] == "Renamed"
    rm.delete_entry(resume, "experience", second)
    assert [e["id"] for e in resume["experience"]] == [first]


def test_bullet_operations_only_touch_the_intended_entry():
    resume = rm.empty_resume()
    rm.add_entry(resume, "projects", "A")
    b = rm.add_entry(resume, "projects", "B")
    b1 = rm.add_bullet(resume, "projects", b, "one")
    b2 = rm.add_bullet(resume, "projects", b, "two")
    rm.move_bullet(resume, "projects", b, b2, -1)
    rm.update_bullet(resume, "projects", b, b1, "one edited")
    rm.delete_bullet(resume, "projects", b, b1)
    assert [x["text"] for x in resume["projects"][1]["bullets"]] == ["two"]
    assert resume["projects"][0]["bullets"] == []


def test_unknown_ids_and_sections_raise_clear_errors():
    resume = rm.empty_resume()
    with pytest.raises(KeyError):
        rm.delete_entry(resume, "experience", "missing")
    with pytest.raises(ValueError):
        rm.add_entry(resume, "personal", "x")


def test_over_length_input_is_rejected_without_losing_old_value():
    resume = rm.empty_resume()
    rm.set_summary(resume, "Good summary")
    with pytest.raises(ValueError):
        rm.set_summary(resume, "x" * (rm.MAX_FIELD_LENGTH + 1))
    assert resume["summary"] == "Good summary"


def test_sections_text_covers_every_section_for_matching(sample_text):
    resume = parse_resume_text(sample_text)
    sections = {block["section"] for block in rm.sections_text(resume)}
    assert {"summary", "experience", "projects", "education", "skills", "certifications", "unclassified"} <= sections
