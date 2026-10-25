"""Password hashing and input validation helpers."""

import hashlib
import re

import bcrypt

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72  # bcrypt limit


def validate_email(email: str) -> str:
    """Return the normalized email or raise ValueError."""
    cleaned = (email or "").strip().lower()
    if not cleaned or len(cleaned) > 254 or not EMAIL_RE.match(cleaned):
        raise ValueError("Enter a valid email address.")
    return cleaned


def validate_new_password(password: str) -> None:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long (maximum 72 bytes).")


def hash_password(password: str) -> str:
    validate_new_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def hash_token(token: str) -> str:
    """One-way hash for short-lived codes so they are never stored in plain text."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clean_text(value: str, max_length: int = 2000) -> str:
    """Trim a user-supplied string and enforce a length limit."""
    text = (value or "").strip()
    if len(text) > max_length:
        raise ValueError(f"Text is too long (maximum {max_length} characters).")
    return text
