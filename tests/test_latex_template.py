import re

import pytest

from hiresense.latex_build import build_latex, compile_latex, escape
from hiresense.resume_model import empty_resume, add_skill


def test_escape_keeps_special_characters_printable():
    assert escape("C++ & R_D 50%") == r"C++ \& R\_D 50\%"


def test_template_contains_every_parsed_section_item():
    resume = empty_resume()
    resume["personal"]["name"] = "Test Person"
    resume["education"].append({"id": "e1", "title": "Bachelor of Technology", "organization": "Test Institute",
                                "dates": "2023 - 2027", "location": "", "link": "", "field_of_study": "Electrical",
                                "grade": "CGPA: 7.9", "bullets": []})
    add_skill(resume, "Python", "Programming")
    resume["achievements"].append({"id": "a1", "text": "Finalist at HackNITJ"})
    source = build_latex(resume)
    assert "Test Institute" in source and "Python" in source and "Finalist at HackNITJ" in source
    assert "\\begin{document}" in source and source.rstrip().endswith("\\end{document}")


def test_template_compiles_when_tectonic_is_installed():
    try:
        import shutil
        if not shutil.which("tectonic"):
            pytest.skip("tectonic is not installed")
    except Exception:
        pytest.skip("tectonic check failed")
    resume = empty_resume()
    resume["personal"]["name"] = "Test Person"
    pdf = compile_latex(build_latex(resume))
    assert pdf.startswith(b"%PDF")
