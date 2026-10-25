from hiresense.matching_engine import DEFAULT_WEIGHTS, analyze_match, compare_results
from hiresense.resume_model import empty_resume, add_entry, add_bullet, add_skill
from hiresense.resume_parser import parse_resume_text
from hiresense.skills import find_skills, normalize_skill


def test_synonyms_map_to_canonical_skills():
    assert "Database Management System" in find_skills("Strong DBMS fundamentals")
    assert "Object-Oriented Programming" in find_skills("Good OOP knowledge")
    assert "JavaScript" in find_skills("Built UI with JS")
    assert "Machine Learning" in find_skills("Experience with ML")
    assert "Natural Language Processing" in find_skills("NLP projects")
    assert normalize_skill("dbms") == "Database Management System"


def test_java_and_javascript_are_not_confused():
    found = find_skills("We use JavaScript daily")
    assert "JavaScript" in found and "Java" not in found
    assert "Java" in find_skills("Core Java developer")


def test_skill_in_project_counts_as_evidence():
    resume = empty_resume()
    entry = add_entry(resume, "projects", "Chat bot")
    add_bullet(resume, "projects", entry, "Implemented the backend using Python and FastAPI")
    result = analyze_match(resume, "Required: Python, Docker. Experience with Python services is key here.")
    assert result["matched_terms"]["Python"]["strength"] == "contextual"
    assert "Python" not in result["missing_required"]


def test_duplicate_mentions_do_not_inflate_score():
    base = empty_resume()
    add_skill(base, "Python")
    jd = "Required: Python, SQL. Strong SQL and Python skills needed for analytics work."
    once = analyze_match(base, jd)["score"]

    repeated = empty_resume()
    for _ in range(10):
        add_skill(repeated, "Python")
    assert analyze_match(repeated, jd)["score"] == once


def test_missing_requirements_are_reported_not_proven_absent(sample_jd, sample_text):
    result = analyze_match(parse_resume_text(sample_text), sample_jd)
    assert "Object-Oriented Programming" in result["missing_required"]
    notes = " ".join(result["notes"])
    assert "does not predict" in notes


def test_weak_evidence_gets_half_credit_and_is_flagged_uncertain():
    resume = empty_resume()
    resume["interests"].append({"id": "i1", "text": "Enjoys Docker in spare time"})
    result = analyze_match(resume, "Required: Docker. Looking for someone who knows Docker well for the role.")
    assert result["matched_terms"]["Docker"]["strength"] == "weak"
    assert "Docker" in result["uncertain_terms"]
    assert "Docker" not in result["missing_required"]
    required = next(c for c in result["categories"] if c["key"] == "required")
    assert required["ratio"] == 0.5


def test_score_stays_within_boundaries(sample_jd, sample_text):
    result = analyze_match(parse_resume_text(sample_text), sample_jd)
    assert 0 <= result["score"] <= 100
    empty = analyze_match(empty_resume(), sample_jd)
    assert 0 <= empty["score"] <= 100


def test_full_match_reaches_100_and_no_match_is_zero():
    resume = empty_resume()
    add_skill(resume, "Python")
    for index in range(3):  # three relevant entries earn full practical-evidence credit
        entry = add_entry(resume, "projects", f"Project {index}")
        add_bullet(resume, "projects", entry, "Built a service in Python")
    jd = "Required: Python."
    assert analyze_match(resume, jd)["score"] == 100.0
    assert analyze_match(empty_resume(), "Required: Python. Python is needed for this job.")["score"] == 0.0


def test_non_applicable_categories_are_removed_and_weights_renormalized():
    resume = empty_resume()
    add_skill(resume, "Python")
    result = analyze_match(resume, "Required: Python. Need Python for this role.")
    applicable = [c for c in result["categories"] if c["applicable"]]
    assert {c["key"] for c in applicable} == {"required", "experience", "other"}
    assert all(c["key"] not in {"preferred", "education"} for c in applicable)
    assert round(sum(c["effective_weight"] for c in applicable), 1) == 100.0


def test_jd_without_requirements_gives_explicit_insufficient_signal():
    result = analyze_match(empty_resume(), "a an the of to in on at by for")
    assert result["insufficient_signal"] is True
    assert result["score"] == 0.0
    assert any("no recognizable requirements" in n for n in result["notes"])


def test_matching_is_deterministic(sample_jd, sample_text):
    resume = parse_resume_text(sample_text)
    assert analyze_match(resume, sample_jd) == analyze_match(resume, sample_jd)


def test_default_weights_match_spec():
    assert DEFAULT_WEIGHTS == {"required": 45.0, "experience": 25.0, "preferred": 15.0, "education": 10.0, "other": 5.0}


def test_recalculation_reports_change_and_newly_matched(sample_jd, sample_text):
    resume = parse_resume_text(sample_text)
    before = analyze_match(resume, sample_jd)
    add_skill(resume, "Object-Oriented Programming")
    after = analyze_match(resume, sample_jd)
    comparison = compare_results(before, after)
    assert comparison["score_change"] == round(after["score"] - before["score"], 1)
    assert comparison["score_change"] > 0
    assert "Object-Oriented Programming" in comparison["newly_matched"]
