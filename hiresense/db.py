"""SQLite persistence for student accounts, resumes, versions and match analyses.

All queries are parameterized and every student-owned lookup includes the owner's user ID.
Initialization only creates missing tables; it never deletes data.
"""

import datetime as dt
import json
import sqlite3
from contextlib import contextmanager

from . import config
from .security import hash_password, verify_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    original_bytes BLOB NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resume_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER NOT NULL REFERENCES resumes(id),
    version_no INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (resume_id, version_no)
);

CREATE TABLE IF NOT EXISTS match_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    resume_id INTEGER NOT NULL REFERENCES resumes(id),
    jd_title TEXT NOT NULL DEFAULT '',
    jd_text TEXT NOT NULL,
    score REAL NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _drop_legacy_role_column(conn)


def _drop_legacy_role_column(conn) -> None:
    """Older versions stored a 'role' column that new sign-ups do not fill in. Rebuild the table without it,
    keeping every existing account."""
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "role" not in columns:
        return
    conn.executescript("""
        CREATE TABLE users_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO users_new (id, email, full_name, password_hash, created_at)
            SELECT id, email, full_name, password_hash, created_at FROM users;
        DROP TABLE users;
        ALTER TABLE users_new RENAME TO users;
    """)


# ---------- accounts ----------

def create_user(email: str, full_name: str, password: str) -> int:
    password_hash = hash_password(password)
    if get_user_by_email(email):
        raise ValueError("An account with this email already exists.")
    try:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, full_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (email, full_name, password_hash, utcnow()),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError("The account could not be created. Please try again.") from exc


def get_user_by_email(email: str):
    with connect() as conn:
        row = conn.execute("SELECT id, email, full_name FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def authenticate_user(email: str, password: str):
    """Return the user row when the email and password match, else None."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        return None
    user = dict(row)
    return user if verify_password(password, user["password_hash"]) else None


# ---------- resumes and versions ----------

def save_new_resume(user_id, filename, file_type, original_bytes, resume_data, note="Initial upload") -> int:
    """Store a new resume. Existing saved resumes are never replaced."""
    now = utcnow()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO resumes (user_id, filename, file_type, original_bytes, uploaded_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, filename, file_type, sqlite3.Binary(original_bytes), now),
        )
        resume_id = cur.lastrowid
        conn.execute(
            "INSERT INTO resume_versions (resume_id, version_no, data_json, note, created_at) VALUES (?, 1, ?, ?, ?)",
            (resume_id, json.dumps(resume_data), note, now),
        )
    return resume_id


def list_resumes(user_id: int):
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, filename, file_type, uploaded_at FROM resumes WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_resume(user_id: int, resume_id: int):
    """Ownership is enforced in the query: other students' resumes are never returned."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, filename, file_type, uploaded_at, original_bytes FROM resumes WHERE id = ? AND user_id = ?",
            (resume_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def latest_version(user_id: int, resume_id: int):
    if not get_resume(user_id, resume_id):
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM resume_versions WHERE resume_id = ? ORDER BY version_no DESC LIMIT 1", (resume_id,)
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["data"] = json.loads(item.pop("data_json"))
    return item


def first_version(user_id: int, resume_id: int):
    """The resume as it was first parsed from the uploaded file. Edits are compared against it."""
    if not get_resume(user_id, resume_id):
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT data_json FROM resume_versions WHERE resume_id = ? ORDER BY version_no ASC LIMIT 1", (resume_id,)
        ).fetchone()
    return json.loads(row["data_json"]) if row else None


def add_resume_version(user_id: int, resume_id: int, resume_data: dict, note: str) -> int:
    if not get_resume(user_id, resume_id):
        raise PermissionError("This resume does not belong to your account.")
    with connect() as conn:
        next_no = conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) + 1 FROM resume_versions WHERE resume_id = ?", (resume_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO resume_versions (resume_id, version_no, data_json, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (resume_id, next_no, json.dumps(resume_data), note, utcnow()),
        )
    return next_no


def list_resume_versions(user_id: int, resume_id: int):
    if not get_resume(user_id, resume_id):
        return []
    with connect() as conn:
        rows = conn.execute(
            "SELECT version_no, note, created_at FROM resume_versions WHERE resume_id = ? ORDER BY version_no DESC",
            (resume_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- match analyses ----------

def save_analysis(user_id, resume_id, jd_title, jd_text, result: dict) -> int:
    if not get_resume(user_id, resume_id):
        raise PermissionError("This resume does not belong to your account.")
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO match_analyses (user_id, resume_id, jd_title, jd_text, score, result_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, resume_id, jd_title, jd_text, float(result["score"]), json.dumps(result), utcnow()),
        )
    return cur.lastrowid


def list_user_analyses(user_id: int, limit: int = 20):
    """The student's recent matches, newest first, with the resume filename."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT m.id, m.jd_title, m.score, m.created_at, r.filename"
            " FROM match_analyses m JOIN resumes r ON r.id = m.resume_id"
            " WHERE m.user_id = ? ORDER BY m.id DESC LIMIT ?",
            (user_id, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]
