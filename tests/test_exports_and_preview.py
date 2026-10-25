import io

import pymupdf
import pytest
from docx import Document

from hiresense.generators import TEMPLATES, build_docx, build_pdf, document_blocks, render_html
from hiresense.resume_model import add_bullet, add_entry, add_skill, empty_resume, set_personal, set_summary
from hiresense.resume_parser import parse_resume_text


def _resume():
    resume = parse_resume_text(
        "Priya Sharma\npriya@example.com\nSUMMARY\nBuilds data tools & pipelines\n"
        "EXPERIENCE\nAnalyst Intern — Acme\nJun 2024 – Aug 2024\n• Built dashboards <b>bold</b> with Python\n"
        "SKILLS\nPython, SQL\nLEADERSHIP ACTIVITIES\nCaptain of the chess club"
    )
    return resume


def _all_text(resume):
    blocks = document_blocks(resume)
    parts = [blocks["name"], blocks["contact"]]
    for title, lines in blocks["sections"]:
        parts.append(title)
        parts.extend(" ".join(str(x) for x in line[1:]) for line in lines)
    return " ".join(parts)


def _pdf_text(data):
    document = pymupdf.open(stream=data, filetype="pdf")
    text = " ".join(page.get_text() for page in document)
    document.close()
    return text


def test_pdf_is_valid_and_contains_latest_content():
    resume = _resume()
    pdf = build_pdf(resume, "Modern")
    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf).replace("\n", " ")
    assert "Built dashboards" in text and "Captain of the chess club" in text


def test_docx_is_valid_and_contains_latest_content():
    resume = _resume()
    docx_bytes = build_docx(resume, "ATS-Friendly")
    document = Document(io.BytesIO(docx_bytes))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "Priya Sharma" in text and "Captain of the chess club" in text


@pytest.mark.parametrize("template", TEMPLATES)
def test_templates_change_presentation_not_content(template):
    resume = _resume()
    expected = _all_text(resume)
    pdf_text = _pdf_text(build_pdf(resume, template)).replace("\n", " ")
    for word in ["Built dashboards", "Captain of the chess club", "Python, SQL", "Acme"]:
        assert word in pdf_text
        assert word in expected


def test_switching_templates_keeps_data_unchanged():
    resume = _resume()
    snapshot = repr(resume)
    for template in TEMPLATES:
        render_html(resume, template)
        build_docx(resume, template)
    assert repr(resume) == snapshot


def test_html_preview_escapes_user_text_and_never_contains_scripts():
    resume = empty_resume()
    set_personal(resume, "name", "<script>alert(1)</script>")
    add_skill(resume, "<img src=x onerror=alert(2)>")
    set_summary(resume, "Uses <b>bold</b> & ampersands")
    html = render_html(resume, "Classic")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html


def test_live_preview_reflects_latest_edit():
    resume = _resume()
    entry = add_entry(resume, "projects", "Late addition")
    add_bullet(resume, "projects", entry, "Added after the first render")
    assert "Added after the first render" in render_html(resume, "Modern")


def test_pdf_paginates_long_resume_without_losing_text():
    resume = empty_resume()
    entry = add_entry(resume, "experience", "Long role")
    for index in range(120):
        add_bullet(resume, "experience", entry, f"Bullet number {index} describes an achievement in detail")
    pdf = build_pdf(resume, "Classic")
    document = pymupdf.open(stream=pdf, filetype="pdf")
    assert document.page_count > 1
    text = " ".join(page.get_text() for page in document)
    document.close()
    assert "Bullet number 0 " in text and "Bullet number 119 " in text
