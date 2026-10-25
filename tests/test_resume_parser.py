import pytest

from hiresense.resume_parser import ResumeParseError, extract_document_text, parse_resume_text, parse_upload


def test_docx_text_and_sections_are_extracted(make_docx, sample_text):
    data = make_docx(sample_text.splitlines())
    resume = parse_upload("resume.docx", data)
    assert resume["personal"]["name"] == "Priya Sharma"
    assert resume["personal"]["email"] == "priya.sharma@example.com"
    assert resume["experience"][0]["title"].startswith("Software Intern")
    assert resume["experience"][0]["dates"] == "Jun 2024 – Aug 2024"
    assert len(resume["experience"][0]["bullets"]) == 2
    assert resume["projects"][0]["title"] == "Resume Screener"
    assert resume["education"][0]["dates"] == "2021 – 2025"


def test_pdf_text_is_extracted_and_sections_parsed(make_pdf, sample_text):
    data = make_pdf(sample_text.splitlines())
    resume = parse_upload("resume.pdf", data)
    assert resume["personal"]["email"] == "priya.sharma@example.com"
    skill_names = [s["name"] for s in resume["skills"]]
    assert {"Python", "Java", "JavaScript", "DBMS", "SQL"} <= set(skill_names)
    assert resume["skills"][0]["category"] == "Languages"


def test_unrecognized_uppercase_heading_is_preserved_not_dropped(sample_text):
    resume = parse_resume_text(sample_text)
    texts = [item["text"] for item in resume["unclassified"]]
    assert any("LEADERSHIP ACTIVITIES" in text for text in texts)
    assert "Captain of the chess club" in texts


def test_missing_name_is_not_guessed():
    resume = parse_resume_text("EXPERIENCE\nSoftware Engineer 2023\n• Built tools")
    assert resume["personal"]["name"] == ""
    assert any("name" in note.lower() for note in resume["parse_notes"])


def test_dates_are_not_invented():
    resume = parse_resume_text("EXPERIENCE\nData Analyst Intern\n• Cleaned datasets")
    assert resume["experience"][0]["dates"] == ""


def test_wrapped_bullet_lines_are_joined():
    text = "EXPERIENCE\nData Analyst\n• Built dashboards that track\nweekly sales for the team"
    resume = parse_resume_text(text)
    assert resume["experience"][0]["bullets"][0]["text"] == "Built dashboards that track weekly sales for the team"


def test_scanned_pdf_without_text_asks_for_ocr(make_pdf):
    import pymupdf

    document = pymupdf.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    with pytest.raises(ResumeParseError, match="OCR"):
        parse_upload("scan.pdf", data)


def test_empty_file_is_rejected():
    with pytest.raises(ResumeParseError, match="empty"):
        parse_upload("resume.pdf", b"")


def test_unsupported_extension_is_rejected():
    with pytest.raises(ResumeParseError, match="Unsupported"):
        parse_upload("resume.txt", b"hello world")


def test_fake_pdf_is_rejected():
    with pytest.raises(ResumeParseError, match="not a valid PDF"):
        parse_upload("resume.pdf", b"this is not a pdf at all")


def test_oversized_file_is_rejected(monkeypatch):
    from hiresense import config

    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ResumeParseError, match="larger"):
        parse_upload("resume.docx", b"PK" + b"x" * 50)


def test_corrupt_docx_is_rejected():
    with pytest.raises(ResumeParseError, match="could not be read"):
        extract_document_text("resume.docx", b"PK\x03\x04 corrupted")
