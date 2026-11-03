import json

from hiresense.llm_rewrite import passes_checks, rewrite_bullet

ORIGINAL = "Developed a document-aware chatbot using Groq Llama-3.3-70B and RAG to answer questions from 3 PDF files."


def test_accepts_wording_change_with_same_facts():
    rewrite = "Built a document-aware chatbot using Groq Llama-3.3-70B and Retrieval-Augmented Generation (RAG) to answer questions from 3 PDF files."
    assert passes_checks(ORIGINAL, rewrite, "RAG Retrieval-Augmented Generation")


def test_rejects_skill_not_in_original():
    assert not passes_checks(ORIGINAL, "Built a chatbot using Groq and Docker to answer questions from 3 PDF files.", "Docker")


def test_rejects_new_number():
    assert not passes_checks(ORIGINAL, "Built a document-aware chatbot using Groq and RAG to answer questions from 50 PDF files.", "")


def test_rejects_new_proper_name():
    assert not passes_checks(ORIGINAL, "Built a document-aware chatbot for Google using Groq and RAG across 3 PDF files.", "")


def test_rejects_unchanged_or_too_short():
    assert not passes_checks(ORIGINAL, ORIGINAL, "")
    assert not passes_checks(ORIGINAL, "Built chatbot.", "")


def test_rewrite_bullet_uses_model_json_and_checks_it():
    reply = json.dumps({"rewrite": "Built a document-aware chatbot using Groq and Retrieval-Augmented Generation (RAG) to answer questions from 3 PDF files."})
    result = rewrite_bullet(ORIGINAL, ["RAG"], "We need Retrieval-Augmented Generation (RAG) experience", model="fake", ask=lambda *a: reply)
    assert result and "Retrieval-Augmented Generation" in result


def test_rewrite_bullet_returns_none_on_bad_or_missing_reply():
    assert rewrite_bullet(ORIGINAL, [], "", model="fake", ask=lambda *a: None) is None
    assert rewrite_bullet(ORIGINAL, [], "", model="fake", ask=lambda *a: "not json") is None
    assert rewrite_bullet(ORIGINAL, [], "", model="", ask=lambda *a: "{}") is None
