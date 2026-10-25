"""Renders every editor section of the three-panel layout through AppTest."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from hiresense.jd_parser import extract_requirements
from hiresense.matching_engine import analyze_match
from hiresense.resume_parser import parse_resume_text
from hiresense.suggestion_engine import generate_suggestions

from views.editor import NAV_KEYS

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _workspace(temp_db, sample_text, sample_jd, make_docx):
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.button(key="guest_start").click().run()
    resume = parse_resume_text(sample_text)
    at.session_state["resume_data"] = resume
    at.session_state["resume_source"] = {"kind": "upload", "resume_id": None, "filename": "cv.docx",
                                         "file_type": "docx", "bytes": make_docx(sample_text.splitlines())}
    at.session_state["jd"] = {"title": "Business Analyst", "company": "", "text": sample_jd}
    at.session_state["jd_requirements"] = extract_requirements(sample_jd)
    at.session_state["match_current"] = analyze_match(resume, sample_jd)
    at.session_state["suggestions"] = generate_suggestions(resume, at.session_state["jd_requirements"])
    at.session_state["stage_status"] = ["done"] * 4
    at.session_state["student_step"] = "workspace"
    return at


def test_every_navigation_section_renders(temp_db, sample_text, sample_jd, make_docx):
    at = _workspace(temp_db, sample_text, sample_jd, make_docx)
    at.run()
    assert not [e.value for e in at.exception]
    for key in NAV_KEYS:
        at.session_state["nav_section"] = key
        at.run()
        errors = [e.value for e in at.exception]
        assert not errors, (key, errors)


def test_donut_and_preview_are_present(temp_db, sample_text, sample_jd, make_docx):
    at = _workspace(temp_db, sample_text, sample_jd, make_docx).run()
    assert not [e.value for e in at.exception]
    html = " ".join(m.value for m in at.markdown)
    assert "hs-donut" in html and "Your match" in html


def test_section_visibility_hides_content_from_preview(temp_db, sample_text, sample_jd, make_docx):
    at = _workspace(temp_db, sample_text, sample_jd, make_docx)
    at.session_state["nav_section"] = "projects"
    at.run()
    assert not [e.value for e in at.exception]
    checkbox = next(c for c in at.checkbox if c.key == "vis:projects")
    checkbox.set_value(False).run()
    assert not [e.value for e in at.exception]
    assert "projects" in at.session_state["resume_data"]["hidden_sections"]
    from hiresense.generators import document_blocks
    titles = [title for title, _ in document_blocks(at.session_state["resume_data"])["sections"]]
    assert "Projects" not in titles


def test_match_review_card_renders_with_score_label(temp_db, sample_text, sample_jd, make_docx):
    from views.breakdown import review_label

    at = _workspace(temp_db, sample_text, sample_jd, make_docx)
    at.session_state["show_breakdown"] = True
    at.run()
    assert not [e.value for e in at.exception]
    html = " ".join(m.value for m in at.markdown)
    assert "hs-review" in html
    assert review_label(75) == "Strong match" and review_label(60) == "Fair match" and review_label(59.9) == "Needs work"
