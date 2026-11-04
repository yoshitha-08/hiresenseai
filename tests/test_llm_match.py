import json

from hiresense import config
from hiresense import llm_match as M
from hiresense import resume_model as rm
from hiresense.jd_parser import extract_requirements
from hiresense.matching_engine import analyze_match

JD = ("We need Retrieval-Augmented Generation (RAG) experience and Docker. "
      "Good communication skills are a plus. Bachelor's degree preferred.")


def _resume():
    resume = rm.empty_resume()
    entry = rm.add_entry(resume, "projects", "Chatbot")
    rm.add_bullet(resume, "projects", entry, "Built a document chatbot using RAG over PDF files.")
    return resume


def _fake(reply):
    return lambda prompt, *args: json.dumps(reply)


def test_extraction_keeps_only_quotes_found_in_the_job_description(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    M._cache.clear()
    reply = {"required": [{"skill": "RAG", "quote": "Retrieval-Augmented Generation (RAG) experience"},
                          {"skill": "Kubernetes", "quote": "Kubernetes is required"}],
             "preferred": [{"skill": "Teamwork", "quote": "Good communication skills"}],
             "qualifications": ["bachelor's degree"]}
    result = M.extract_job_requirements(JD, ask=_fake(reply))
    assert result["required"] == ["Retrieval-Augmented Generation"]
    assert result["preferred"] == []
    assert result["qualifications"] == ["bachelor's degree"]


def test_judge_accepts_only_verbatim_evidence_that_mentions_the_skill(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    M._cache.clear()
    good = {"found": [{"skill": "Retrieval-Augmented Generation", "evidence": "Built a document chatbot using RAG over PDF files."}]}
    verified = M.judge_evidence(_resume(), ["Retrieval-Augmented Generation"], ask=_fake(good))
    assert "Retrieval-Augmented Generation" in verified and verified["Retrieval-Augmented Generation"][0] == "projects"
    M._cache.clear()
    invented = {"found": [{"skill": "Docker", "evidence": "Deployed everything with Docker."}]}
    assert M.judge_evidence(_resume(), ["Docker"], ask=_fake(invented)) == {}


def test_without_a_key_the_rules_are_used_unchanged(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    rules = extract_requirements(JD)
    requirements, used = M.requirements_with_gemini(rules, JD)
    evidence, used_evidence = M.evidence_with_gemini(_resume(), rules)
    assert requirements == rules and not used and evidence == {} and not used_evidence


def test_verified_evidence_raises_a_skill_only_when_the_rules_missed_it():
    rules = extract_requirements(JD)
    resume = _resume()
    base = analyze_match(resume, JD, requirements=rules)
    assert base["engine"] == "rules"
    boosted = analyze_match(resume, JD, requirements=rules, evidence={"Docker": ("projects", "x")})
    assert boosted["engine"] == "rules + Gemini evidence"
    assert boosted["matched_terms"]["Docker"]["strength"] == "contextual"
    assert boosted["score"] >= base["score"]
