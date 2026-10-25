"""Skill vocabulary, synonym normalization, and boundary-safe term matching.

Edit SKILL_ALIASES to add skills or synonyms. Keys are the canonical names shown in the UI.
"""

import re

SKILL_ALIASES: dict[str, list[str]] = {
    "Python": [],
    "Java": [],
    "JavaScript": ["js", "es6"],
    "TypeScript": [],
    "C++": ["cpp"],
    "C#": ["csharp", "c sharp"],
    "Go": ["golang"],
    "SQL": [],
    "MySQL": [],
    "PostgreSQL": ["postgres"],
    "MongoDB": ["mongo"],
    "Database Management System": ["dbms"],
    "Object-Oriented Programming": ["oop", "object oriented programming", "object oriented"],
    "Data Structures and Algorithms": ["dsa", "data structures"],
    "Machine Learning": ["ml"],
    "Deep Learning": ["dl"],
    "Natural Language Processing": ["nlp"],
    "Computer Vision": [],
    "Artificial Intelligence": ["ai"],
    "Generative AI": ["genai", "gen ai"],
    "TensorFlow": [],
    "PyTorch": [],
    "Scikit-learn": ["sklearn", "scikit learn"],
    "Pandas": [],
    "NumPy": ["numpy"],
    "React": ["reactjs", "react.js"],
    "Node.js": ["nodejs", "node js", "node.js"],
    "Express.js": ["expressjs", "express.js"],
    "Django": [],
    "Flask": [],
    "FastAPI": [],
    "Streamlit": [],
    "HTML": [],
    "CSS": [],
    "REST API": ["rest", "restful", "rest apis"],
    "Git": [],
    "GitHub": [],
    "Docker": [],
    "Kubernetes": [],
    "AWS": ["amazon web services"],
    "Azure": [],
    "Google Cloud": ["gcp"],
    "Linux": [],
    "Excel": ["microsoft excel"],
    "Power BI": ["powerbi"],
    "Tableau": [],
    "Data Analysis": ["data analytics", "data analysis"],
    "Data Visualization": ["data visualisation", "data visualization"],
    "Unit Testing": ["unit tests", "pytest", "junit"],
    "Agile": ["scrum"],
    "Problem Solving": [],
    "Communication": ["communication skills"],
    "Teamwork": ["team work", "collaboration"],
    "Leadership": [],
}

# Words that never count as "other relevant keywords".
STOPWORDS = set(
    """
    the and for with that this from will have has are you your our their they them who what when
    where which while about into over under such also must should would could able work working
    team role years year experience strong good excellent knowledge understanding ability skills
    skill candidate job position responsibilities responsibility requirements requirement preferred
    required including include includes using used use within across other more most any all each
    etc plus etc. new join looking seeking company apply application etc candidates looking
    """.split()
)


def _pattern_for(alias: str) -> re.Pattern:
    words = [re.escape(part) for part in alias.lower().split()]
    body = r"[\s\-]+".join(words)
    return re.compile(rf"(?<![a-z0-9+#]){body}(?![a-z0-9+#])")


_PATTERNS: dict[str, list[re.Pattern]] = {
    canonical: [_pattern_for(name) for name in [canonical, *aliases]]
    for canonical, aliases in SKILL_ALIASES.items()
}


def normalize_skill(name: str) -> str | None:
    """Map a typed skill (or synonym) to its canonical name, or None if unknown."""
    text = (name or "").strip().lower()
    if not text:
        return None
    for canonical, patterns in _PATTERNS.items():
        if any(p.fullmatch(text) for p in patterns):
            return canonical
    return None


def find_skills(text: str) -> set[str]:
    """Return canonical skills mentioned in text. Each skill counts once, however often it appears."""
    lowered = (text or "").lower()
    found = set()
    for canonical, patterns in _PATTERNS.items():
        if any(p.search(lowered) for p in patterns):
            found.add(canonical)
    return found


def contains_term(text: str, term: str) -> bool:
    """Whole-word, case-insensitive check for an arbitrary keyword."""
    return bool(_pattern_for(term).search((text or "").lower()))


def extract_keywords(text: str, exclude: set[str] | None = None, top_n: int = 12) -> list[str]:
    """Frequent non-skill words from a JD. Returned in order of frequency, then first appearance."""
    exclude_lower = {item.lower() for item in (exclude or set())}
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    tokens = re.findall(r"[a-z][a-z+#.\-]{3,}", (text or "").lower())
    for position, token in enumerate(tokens):
        token = token.strip(".-")
        if len(token) < 4 or token in STOPWORDS or token in exclude_lower:
            continue
        counts[token] = counts.get(token, 0) + 1
        first_seen.setdefault(token, position)
    ranked = sorted(counts, key=lambda word: (-counts[word], first_seen[word]))
    return ranked[:top_n]
