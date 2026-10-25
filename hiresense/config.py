"""Configuration read from environment variables (a local .env file is supported).

No secret is needed for the student resume builder.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DB_PATH = Path(os.getenv("HIRESENSE_DB_PATH", str(ROOT_DIR / "data" / "hiresense.sqlite3")))
MAX_UPLOAD_MB = float(os.getenv("HIRESENSE_MAX_UPLOAD_MB", "5"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)
