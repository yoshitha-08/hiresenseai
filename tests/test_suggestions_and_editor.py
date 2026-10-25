import pytest

from hiresense import resume_model as rm
from hiresense.resume_parser import parse_resume_text
from hiresense.suggestion_engine import apply_suggestion, generate_suggestions


def _resume_with_weak_bullet():
    resume = rm.empty_resume()
    entry = rm.add_entry(resume, "experience", "Analyst")
    rm.add_bullet(resume, "experience", entry, "Responsible for weekly reports")
    rm.add_bullet(resume, "experience", entry, "Worked on the billing system and its database migrations with the team")
    return resume, entry


def test_weak_opener_gets_proposal_and_original_is_unchanged():
    resume, _ = _resume_with_weak_bullet()
    suggestions = generate_suggestions(resume)
    weak = next(s for s in suggestions if s["kind"] == "weak_opener")
    assert weak["original"] == "Responsible for weekly reports"
    assert weak["proposed"].startswith("Led")
    assert resume["experience"][0]["bullets"][0]["text"] == "Responsible for weekly reports"


def test_accepting_with_edit_changes_only_target_bullet():
    resume, _ = _resume_with_weak_bullet()
    suggestions = generate_suggestions(resume)
    weak = next(s for s in suggestions if s["kind"] == "weak_opener")
    changed = apply_suggestion(resume, weak, "Coordinated weekly reports")
    assert changed
    bullets = resume["experience"][0]["bullets"]
    assert bullets[0]["text"] == "Coordinated weekly reports"
    assert bullets[1]["text"].startswith("Worked on the billing system")


def test_empty_accepted_text_is_rejected():
    resume, _ = _resume_with_weak_bullet()
    suggestion = next(s for s in generate_suggestions(resume) if s["kind"] == "weak_opener")
    with pytest.raises(ValueError):
        apply_suggestion(resume, suggestion, "   ")


def test_suggestions_never_add_skills_or_metrics():
    resume = rm.empty_resume()
    entry = rm.add_entry(resume, "projects", "Tool")
    rm.add_bullet(resume, "projects", entry, "Built a tool for the team")
    before_skills = list(resume["skills"])
    requirements = {"required": ["Kubernetes"], "preferred": [], "qualifications": [], "years": [], "keywords": []}
    suggestions = generate_suggestions(resume, requirements)
    gap = next(s for s in suggestions if s["kind"] == "keyword_gap")
    assert gap["editable"] is False
    assert gap["target"]["section"] is None
    assert resume["skills"] == before_skills
    metric = next(s for s in suggestions if s["kind"] == "add_detail_question")
    assert metric["original"] == metric["proposed"]


def test_unsupported_skill_is_flagged_but_not_removed():
    resume = rm.empty_resume()
    rm.add_skill(resume, "Kubernetes")
    suggestions = generate_suggestions(resume)
    assert any(s["kind"] == "unsupported_skill" for s in suggestions)
    assert [s["name"] for s in resume["skills"]] == ["Kubernetes"]


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
