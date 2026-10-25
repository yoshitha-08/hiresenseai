# HireSense AI

A student resume builder. Log in, pick a saved resume or upload a new one (PDF or DOCX), add a job description, and see an explainable match score. Then edit your resume, apply suggestions, switch templates, and download a PDF or DOCX.

No paid service or API key is needed.

## Run it on your Mac

Open Terminal in the project folder and run these commands one at a time.

```bash
cd ~/Desktop/HireSenseAI
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the address Streamlit prints (usually http://localhost:8501). You will see the login page first.

To start it again later:

```bash
cd ~/Desktop/HireSenseAI && source .venv/bin/activate
streamlit run app.py
```

## Using the app

1. **Log in or create an account.** You can also continue as a guest, but guest work is not saved.
2. **Dashboard:** choose a saved resume, or upload a new one. Your recent matches are listed here.
3. **Job description:** upload it (PDF, DOCX, or TXT) or paste it.
4. **Processing:** four stages run in order, with a progress bar: reading the resume, reading the job description, scoring the match, and writing suggestions.
5. **Match review:** the score ring, category breakdown, matched and missing skills, and "How was this score calculated?".
6. **Editor:** edit every section, apply or dismiss suggestions, change the template, and download your resume.

## Run the tests

```bash
cd ~/Desktop/HireSenseAI && source .venv/bin/activate
python -m pytest -q -p no:cacheprovider
```

The tests use temporary databases and need no internet access. Run them one at a time. Running several test processes at once can stall on macOS file access to the Desktop folder.

## Settings (optional, in `.env`)

Copy `.env.example` to `.env` to change the database location or the upload limit. Leave it out to use the defaults.

## Project layout

- `app.py`: entry point, opens the login page.
- `views/`: the student screens (login, dashboard, job description, processing, editor), plus shared styling.
- `hiresense/`: core logic for parsing, matching, suggestions, the resume model, document generation, and the database.
- `tests/`: automated tests.
- `data/`: local SQLite database, created on first run and not committed.

## How the score works

Required skills 45%, experience and projects 25%, preferred skills 15%, education 10%, and other keywords 5%. Categories that do not apply to a job description are removed, and the rest are rescaled to 100. The score is a compatibility estimate. It does not predict interviews or hiring.

## Known limitations

- Scanned PDFs are rejected with an OCR message; OCR is not included.
- The skill list is fixed in `hiresense/skills.py`. Skills outside it are only found as plain keywords.
- The visual design follows the screenshots as closely as Streamlit allows, but it has not been compared pixel by pixel.
