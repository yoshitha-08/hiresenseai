"""Password safety, input validation, and student data ownership."""

import pytest

from hiresense import db
from hiresense.resume_model import empty_resume
from hiresense.security import hash_password, validate_email, validate_new_password, verify_password


def test_passwords_are_hashed_not_stored_plain(temp_db):
    password_hash = hash_password("correct horse battery")
    assert "correct horse" not in password_hash
    assert verify_password("correct horse battery", password_hash)
    assert not verify_password("wrong password!", password_hash)


def test_short_and_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        validate_new_password("short")
    with pytest.raises(ValueError):
        validate_email("not-an-email")
    assert validate_email("  Student@Example.COM ") == "student@example.com"


def test_authenticate_checks_password(temp_db):
    db.create_user("ana@example.com", "Ana", "password123")
    assert db.authenticate_user("ana@example.com", "password123") is not None
    assert db.authenticate_user("ana@example.com", "wrongpass1") is None
    assert db.authenticate_user("nobody@example.com", "password123") is None


def test_duplicate_account_is_refused(temp_db):
    db.create_user("dup@example.com", "One", "password123")
    with pytest.raises(ValueError, match="already exists"):
        db.create_user("dup@example.com", "Two", "password456")


def test_student_ownership_is_enforced(temp_db):
    owner = db.create_user("owner@example.com", "Owner", "password123")
    other = db.create_user("other@example.com", "Other", "password456")
    resume_id = db.save_new_resume(owner, "cv.docx", "docx", b"PK123", empty_resume())
    assert db.get_resume(other, resume_id) is None
    assert db.latest_version(other, resume_id) is None
    with pytest.raises(PermissionError):
        db.add_resume_version(other, resume_id, empty_resume(), "tamper")
    assert db.list_resumes(other) == []


def test_saved_resume_keeps_existing_versions_when_new_upload_added(temp_db):
    user = db.create_user("s@example.com", "S", "password123")
    first = db.save_new_resume(user, "one.pdf", "pdf", b"%PDF-1", empty_resume())
    db.save_new_resume(user, "two.pdf", "pdf", b"%PDF-2", empty_resume())
    assert db.latest_version(user, first)["version_no"] == 1
    assert len(db.list_resumes(user)) == 2


def test_new_version_is_numbered_and_listed(temp_db):
    user = db.create_user("v@example.com", "V", "password123")
    resume_id = db.save_new_resume(user, "cv.pdf", "pdf", b"%PDF-1", empty_resume())
    assert db.add_resume_version(user, resume_id, empty_resume(), "Saved") == 2
    assert [v["version_no"] for v in db.list_resume_versions(user, resume_id)] == [2, 1]


def test_analyses_are_listed_only_for_their_owner(temp_db):
    owner = db.create_user("m@example.com", "M", "password123")
    other = db.create_user("n@example.com", "N", "password456")
    resume_id = db.save_new_resume(owner, "cv.pdf", "pdf", b"%PDF-1", empty_resume())
    db.save_analysis(owner, resume_id, "Analyst", "job text " * 5, {"score": 61.5})
    mine = db.list_user_analyses(owner)
    assert len(mine) == 1 and mine[0]["score"] == 61.5 and mine[0]["filename"] == "cv.pdf"
    assert db.list_user_analyses(other) == []
    with pytest.raises(PermissionError):
        db.save_analysis(other, resume_id, "x", "y", {"score": 1})


def test_init_db_keeps_existing_rows(temp_db):
    user = db.create_user("keep@example.com", "Keep", "password123")
    db.init_db()
    assert db.authenticate_user("keep@example.com", "password123") is not None
    assert db.get_resume(user, 999) is None  # the second init did not change existing data
    assert user == 1
