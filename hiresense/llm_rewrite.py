"""Optional Gemini rewrites for resume bullets. Needs GEMINI_API_KEY in .env; without it the app stays rule-based.

The model only rewords a bullet. A rewrite is kept only when it passes every check below, so it
cannot add a skill, a number, or a name that is not already in the bullet or the job description.
If there is no key, the network call fails, or the reply is unusable, the caller gets nothing and the rule-based suggestions remain.
Resume bullets are sent to Google when this step runs.
"""

import json
import re
import urllib.error
import urllib.request

from . import config
from .skills import find_skills

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

PROMPT = """Rewrite this resume bullet so it uses the wording of the job description where it truthfully fits.

Rules:
- Keep every fact, number, name and claim from the original. Do not add any.
- Do not add a skill or tool that the original does not name. Ignore job-description skills that the original does not mention, even if they sound related.
- Rewrite only the wording of the work actually described, for example:
  Original: Built a chatbot using RAG over PDFs. -> Rewritten: Built a chatbot using Retrieval-Augmented Generation (RAG) over PDFs.
- You may use a job-description term only when it describes work the original already shows (for example "RAG" and "Retrieval-Augmented Generation" are the same thing).
- Start with a strong action verb. Keep it under 30 words.
- Use the requirement lines only for technical wording. Ignore soft skills such as teamwork, communication or leadership.
- Fix grammar, tense and sentence structure. The result must be one complete sentence.

Job description skills: {jd_terms}
Job description requirement lines (technical only): {requirement_lines}
Original bullet: {bullet}

Reply with JSON only: {{"rewrite": "<the rewritten bullet>"}}"""

NUMBER = re.compile(r"\d+(?:\.\d+)?")
CAPITALISED = re.compile(r"(?<=[\s(,])[A-Z][A-Za-z0-9+#.-]{2,}")


def ask_gemini(prompt: str, model: str, api_key: str, timeout: float = 60.0) -> str | None:
    """Send one prompt to the Gemini API and return the text of the reply, or None on any failure."""
    url = f"{GEMINI_ENDPOINT}/{model}:generateContent"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }).encode()
    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode())
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None


def is_available() -> bool:
    """The Gemini step runs only when a key is configured. No network call is made to check."""
    return bool(config.GEMINI_API_KEY)


def passes_checks(original: str, rewrite: str, jd_text: str) -> bool:
    """Reject any rewrite that adds a skill, number, proper name or length the original does not support."""
    if not rewrite or rewrite.strip() == original.strip():
        return False
    words = rewrite.split()
    if len(words) < 3 or len(words) > max(30, len(original.split()) + 8):
        return False
    if not set(NUMBER.findall(rewrite)) <= set(NUMBER.findall(original)):
        return False
    if find_skills(rewrite) - find_skills(original):
        return False
    known = {w.lower() for w in re.findall(r"[A-Za-z0-9+#.-]+", original + " " + jd_text)}
    for token in CAPITALISED.findall(rewrite):
        if token.lower() not in known:
            return False
    return True


def rewrite_bullet(original: str, jd_terms: list[str], jd_text: str, requirement_lines: list[str] | None = None,
                   model: str = config.LLM_MODEL, ask=None) -> str | None:
    """Return a checked rewrite, or None when there is no safe improvement."""
    if not model or not original.strip():
        return None
    ask = ask or (lambda prompt, name: ask_gemini(prompt, name, config.GEMINI_API_KEY))
    prompt = PROMPT.format(jd_terms=", ".join(jd_terms) or "none", bullet=original,
                           requirement_lines=" | ".join(requirement_lines or []) or "none")
    reply = ask(prompt, model)
    if not reply:
        return None
    try:
        rewrite = str(json.loads(reply).get("rewrite", "")).strip()
    except (ValueError, AttributeError):
        return None
    return rewrite if passes_checks(original, rewrite, jd_text) else None


SKILL_PROMPT = """Read this job description and list the TECHNICAL skills, tools, languages, or subjects it asks for.
Ignore soft skills such as teamwork, communication or leadership. Use the exact wording from the job description.

Job description:
{jd_text}

Reply with JSON only: {{"skills": ["...", "..."]}}"""


def suggest_skills(jd_text: str, existing: set[str], model: str = config.LLM_MODEL, ask=None) -> list[str]:
    """Technical skills the job description asks for that the resume does not have. Only names found in the JD."""
    if not model or not jd_text.strip():
        return []
    ask = ask or (lambda prompt, name: ask_gemini(prompt, name, config.GEMINI_API_KEY))
    reply = ask(SKILL_PROMPT.format(jd_text=jd_text[:6000]), model)
    if not reply:
        return []
    try:
        names = json.loads(reply).get("skills", [])
    except (ValueError, AttributeError):
        return []
    lowered_jd = jd_text.lower()
    lowered_existing = {name.lower() for name in existing}
    result = []
    for name in names:
        name = str(name).strip()
        if not name or name.lower() in lowered_existing or name.lower() not in lowered_jd:
            continue
        if name not in result:
            result.append(name)
    return result[:15]
