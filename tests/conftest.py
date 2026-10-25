"""Shared fixtures. Every test uses a temporary database, never the real one."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hiresense import config, db  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.sqlite3"
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init_db()
    return path


SAMPLE_RESUME_TEXT = """Priya Sharma
priya.sharma@example.com | +91 98765 43210
Summary
Final-year CSE student who enjoys building data tools.
EXPERIENCE
Software Intern — Acme Labs
Jun 2024 – Aug 2024
• Responsible for internal dashboards using Python and Pandas
• Helped the QA team automate regression tests with pytest
PROJECTS
Resume Screener
• Built an NLP pipeline for resume ranking with scikit-learn and Flask
EDUCATION
B.Tech in Computer Science, XYZ University 2021 – 2025
SKILLS
Languages: Python, Java, JavaScript
Databases: DBMS, SQL
CERTIFICATIONS
Machine Learning by Coursera 2023
LEADERSHIP ACTIVITIES
Captain of the chess club
"""

SAMPLE_JD = """Machine Learning Engineer
Required: Python, Machine Learning, SQL, Database Management System, Object-Oriented Programming.
Preferred: Docker, JavaScript, Flask.
Bachelor's degree in Computer Science is required. Experience building NLP models and data pipelines."""


@pytest.fixture()
def sample_text():
    return SAMPLE_RESUME_TEXT


@pytest.fixture()
def sample_jd():
    return SAMPLE_JD


@pytest.fixture()
def make_pdf():
    def _make(lines):
        import pymupdf

        document = pymupdf.open()
        page = document.new_page()
        for index, line in enumerate(lines):
            page.insert_text((72, 80 + index * 16), line, fontsize=11)
        data = document.tobytes()
        document.close()
        return data

    return _make


@pytest.fixture()
def make_docx():
    def _make(lines):
        import io
        from docx import Document

        document = Document()
        for line in lines:
            document.add_paragraph(line)
        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    return _make
