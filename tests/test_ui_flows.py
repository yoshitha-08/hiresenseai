"""Drives the real Streamlit student pages with AppTest (no browser, no network)."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from hiresense import db
from hiresense.resume_parser import parse_resume_text
from hiresense.suggestion_engine import generate_suggestions

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app():
    return AppTest.from_file(APP, default_timeout=90)


def _errors(at):
    return [e.value for e in at.exception]


def _register(at, name="Ana Student", email="ana@example.com", password="password123"):
    next(b for b in at.button if b.label == "Sign up").click().run()
    next(t for t in at.text_input if t.label == "Full name").set_value(name)
    at.text_input(key="reg_email").set_value(email)
    at.text_input(key="reg_pw").set_value(password)
    at.text_input(key="reg_pw2").set_value(password)
    next(b for b in at.button if b.label == "Create account").click().run()


def test_app_opens_on_the_student_login_page(temp_db):
    at = _app().run()
    assert not _errors(at)
    labels = [b.label for b in at.button]
    assert "Log in" in labels and "Sign up" in labels and "Start free trial" in labels
    assert "Recruiter / Employer" not in labels and "Administrator sign-in" not in labels


def test_registration_leads_to_student_dashboard(temp_db):
    at = _app().run()
    _register(at)
    assert not _errors(at), _errors(at)
    assert at.session_state["student"]["name"] == "Ana Student"
    assert at.session_state["student_step"] == "dashboard"
    assert any(b.label == "Upload a new resume" for b in at.button)
    assert any(b.label == "Choose a saved resume" for b in at.button)


def test_login_with_existing_account(temp_db):
    db.create_user("login@example.com", "Login User", "password123")
    at = _app().run()
    at.text_input[0].set_value("login@example.com")
    at.text_input[1].set_value("password123")
    next(b for b in at.button if b.label == "Log in").click().run()
    assert not _errors(at)
    assert at.session_state["student"]["name"] == "Login User"


def test_wrong_password_is_refused(temp_db):
    db.create_user("wrong@example.com", "Someone", "password123")
    at = _app().run()
    at.text_input[0].set_value("wrong@example.com")
    at.text_input[1].set_value("not-the-password")
    next(b for b in at.button if b.label == "Log in").click().run()
    assert not _errors(at)
    assert at.session_state["student"] is None
    assert any("incorrect" in e.value for e in at.error)


def test_guest_reaches_dashboard_without_saved_resumes(temp_db):
    at = _app().run()
    next(b for b in at.button if b.label == "Start free trial").click().run()
    assert not _errors(at)
    assert at.session_state["student"]["guest"] is True
    assert at.session_state["student_step"] == "dashboard"


def test_dashboard_buttons_open_saved_and_upload_modes(temp_db):
    db.create_user("modes@example.com", "Modes", "password123")
    at = _app().run()
    at.text_input[0].set_value("modes@example.com")
    at.text_input[1].set_value("password123")
    next(b for b in at.button if b.label == "Log in").click().run()
    next(b for b in at.button if b.label == "Choose a saved resume").click().run()
    assert at.session_state["choose_mode"] == "saved" and at.session_state["student_step"] == "choose"
    assert not _errors(at)
    at.button(key="choose_back").click().run()
    assert at.session_state["student_step"] == "dashboard"
    next(b for b in at.button if b.label == "Upload a new resume").click().run()
    assert at.session_state["choose_mode"] == "upload" and not _errors(at)


def _workspace(at, sample_text, sample_jd, make_docx):
    resume = parse_resume_text(sample_text)
    at.session_state["resume_data"] = resume
    at.session_state["resume_source"] = {"kind": "upload", "resume_id": None, "filename": "cv.docx",
                                         "file_type": "docx", "bytes": make_docx(sample_text.splitlines())}
    at.session_state["jd"] = {"title": "ML Engineer", "company": "", "text": sample_jd}
    at.session_state["stage_status"] = ["done", "pending", "pending", "pending"]
    at.session_state["student_step"] = "processing"
    return resume


def test_processing_reaches_match_results_and_editor(temp_db, make_docx, sample_text, sample_jd):
    at = _app().run()
    next(b for b in at.button if b.label == "Start free trial").click().run()
    _workspace(at, sample_text, sample_jd, make_docx)
    at.run()
    assert not _errors(at), _errors(at)
    assert at.session_state["student_step"] == "workspace"
    assert 0 < at.session_state["match_current"]["score"] <= 100


def test_editing_summary_updates_resume_data(temp_db, make_docx, sample_text, sample_jd):
    at = _app().run()
    next(b for b in at.button if b.label == "Start free trial").click().run()
    _workspace(at, sample_text, sample_jd, make_docx)
    at.run()
    summary_box = next(t for t in at.text_area if t.label == "Summary")
    summary_box.input("Edited summary for the test").run()
    assert at.session_state["resume_data"]["summary"] == "Edited summary for the test"
    assert not _errors(at)


def test_applying_a_suggestion_changes_only_the_target_bullet(temp_db, make_docx, sample_text, sample_jd):
    at = _app().run()
    next(b for b in at.button if b.label == "Start free trial").click().run()
    resume = _workspace(at, sample_text, sample_jd, make_docx)
    at.run()
    at.session_state["suggestions"] = generate_suggestions(resume)
    at.session_state["suggestion_status"] = {}
    at.session_state["main_view"] = "Suggestions"
    at.run()
    weak = next(s for s in at.session_state["suggestions"] if s["kind"] == "weak_opener")
    before = [b["text"] for b in resume["experience"][0]["bullets"]]
    at.button(key=f"accept:{weak['id']}").click().run()
    assert not _errors(at)
    after = [b["text"] for b in at.session_state["resume_data"]["experience"][0]["bullets"]]
    assert after[0] != before[0] and after[1:] == before[1:]
    assert at.session_state["suggestion_status"][weak["id"]] == "accepted"


def test_student_sees_only_own_recent_matches(temp_db, make_docx, sample_text):
    owner = db.create_user("owner@example.com", "Owner", "password123")
    other = db.create_user("other@example.com", "Other", "password456")
    resume_id = db.save_new_resume(owner, "owner-cv.docx", "docx", make_docx(sample_text.splitlines()),
                                   parse_resume_text(sample_text))
    db.save_analysis(owner, resume_id, "Owner job", "job text " * 5, {"score": 70.0})
    at = _app().run()
    at.text_input[0].set_value("other@example.com")
    at.text_input[1].set_value("password456")
    next(b for b in at.button if b.label == "Log in").click().run()
    assert not _errors(at)
    assert db.list_resumes(other) == [] and db.list_user_analyses(other) == []
    assert not any("owner-cv.docx" in str(d.value) for d in at.dataframe)
