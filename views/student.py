"""Student / Job Seeker workspace: accounts, resume choice, JD input, processing, dashboard."""

import copy

import streamlit as st

from hiresense import db
from hiresense.config import MAX_UPLOAD_MB
from hiresense.generators import render_html
from hiresense.jd_parser import JDError, extract_requirements, read_jd_text
from hiresense.matching_engine import analyze_match
from hiresense.resume_parser import ResumeParseError, parse_upload
from hiresense.security import clean_text, validate_email, validate_new_password
from hiresense.suggestion_engine import generate_suggestions

from views.common import STAGE_LABELS, esc, stage_list_html
from views.editor import render_editor, reset_editor_state


STUDENT_DEFAULTS = {
    "student": None,          # {"user_id": int|None, "name": str, "guest": bool}
    "student_step": "dashboard",  # dashboard | choose | jd | processing | workspace
    "choose_mode": "upload",      # saved | upload
    "resume_source": None,     # {"kind": "saved"|"upload", "resume_id", "filename", "file_type", "bytes"}
    "resume_data": None,
    "original_resume": None,   # the parse of the uploaded file; edits are applied to the file relative to this
    "jd": None,                # {"title", "company", "text"}
    "jd_requirements": None,
    "match_current": None,
    "match_comparison": None,
    "suggestions": [],
    "suggestion_status": {},
    "stage_status": ["pending"] * 4,
    "stage_error": "",
    "upload_notice": None,
}


def init_student_state() -> None:
    for key, value in STUDENT_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def logout_student() -> None:
    for key in STUDENT_DEFAULTS:
        st.session_state.pop(key, None)
    reset_editor_state()


def go_dashboard() -> None:
    st.session_state["student_step"] = "dashboard"


# ---------- entry: login, registration, guest ----------

def render_student_entry() -> None:
    """Log-in page first. Sign-up and the free trial are one click away."""
    _, center, _ = st.columns([1, 1.3, 1])
    with center:
        if st.session_state.get("auth_view") == "signup":
            _render_signup()
        else:
            _render_login()


def _render_login() -> None:
    st.title("Log in to HireSense AI")
    st.caption("Tailor your resume to a job description and see an explainable match score.")
    with st.form("student_login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")
    if submitted:
        try:
            user = db.authenticate_user(validate_email(email), password)
        except ValueError as exc:
            st.error(str(exc))
        else:
            if user:
                _set_student(user["id"], user["full_name"] or user["email"], guest=False)
                st.rerun()
            else:
                st.error("Email or password is incorrect.")

    st.markdown("<div style='text-align:center'>New here?</div>", unsafe_allow_html=True)
    _, middle, _ = st.columns([1, 2, 1])
    with middle:
        if st.button("Sign up", key="go_signup", use_container_width=True):
            st.session_state["auth_view"] = "signup"
            st.rerun()
    st.markdown("<div style='text-align:center'>Just looking?</div>", unsafe_allow_html=True)
    _, middle, _ = st.columns([1, 2, 1])
    with middle:
        if st.button("Start free trial", key="guest_start", use_container_width=True):
            _set_student(None, "Guest", guest=True)
            st.rerun()


def _render_signup() -> None:
    st.title("Create your account")
    st.caption("Save your resumes and match history. It takes less than a minute.")
    with st.form("student_register"):
        name = st.text_input("Full name")
        email_new = st.text_input("Email", key="reg_email")
        password_new = st.text_input("Password (at least 8 characters)", type="password", key="reg_pw")
        confirm = st.text_input("Confirm password", type="password", key="reg_pw2")
        submitted = st.form_submit_button("Create account", type="primary")
    if submitted:
        try:
            if password_new != confirm:
                raise ValueError("The passwords do not match.")
            clean_name = clean_text(name, 120)
            if not clean_name:
                raise ValueError("Enter your full name.")
            validate_new_password(password_new)
            user_id = db.create_user(validate_email(email_new), clean_name, password_new)
        except ValueError as exc:
            st.error(str(exc))
        else:
            _set_student(user_id, clean_name, guest=False)
            st.rerun()

    _, middle, _ = st.columns([1, 2, 1])
    with middle:
        if st.button("Back to log in", key="back_to_login", use_container_width=True):
            st.session_state["auth_view"] = "login"
            st.rerun()
        if st.button("Start free trial instead", key="guest_start_signup", use_container_width=True):
            _set_student(None, "Guest", guest=True)
            st.rerun()


def _set_student(user_id, name, guest: bool) -> None:
    st.session_state["student"] = {"user_id": user_id, "name": name, "guest": guest}
    st.session_state["student_step"] = "dashboard"
    st.session_state["auth_view"] = "login"


# ---------- workspace ----------

def render_student_workspace() -> None:
    student = st.session_state["student"]
    step = st.session_state["student_step"]
    if step == "dashboard":
        _render_dashboard(student)
    elif step == "choose":
        _render_choose_step(student)
    elif step == "jd":
        _render_jd_step()
    elif step == "processing":
        _render_processing()
    else:
        _render_workspace(student)


def _render_dashboard(student: dict) -> None:
    st.title(f"Welcome back, {student['name']}" if not student["guest"] else "Welcome to HireSense AI")
    st.write("Start by choosing a resume, then add the job description you want to target.")
    saved_col, new_col = st.columns(2, gap="large")
    with saved_col:
        st.markdown("<div class='hs-card'><h3>Use a saved resume</h3><p class='hs-muted'>Pick a resume you "
                    "already saved, with its latest edits.</p></div>", unsafe_allow_html=True)
        if student["guest"]:
            st.caption("Saved resumes are available after you create an account.")
        elif st.button("Choose a saved resume", type="primary", use_container_width=True, key="dash_saved"):
            st.session_state["choose_mode"] = "saved"
            st.session_state["student_step"] = "choose"
            st.rerun()
    with new_col:
        st.markdown("<div class='hs-card'><h3>Upload a new resume</h3><p class='hs-muted'>Upload a PDF or DOCX "
                    "file. Your original file is kept unchanged.</p></div>", unsafe_allow_html=True)
        if st.button("Upload a new resume", type="primary", use_container_width=True, key="dash_new"):
            st.session_state["choose_mode"] = "upload"
            st.session_state["student_step"] = "choose"
            st.rerun()

    if not student["guest"]:
        st.subheader("Recent matches")
        matches = db.list_user_analyses(student["user_id"])
        if matches:
            st.dataframe(
                [{"Job": m["jd_title"] or "Untitled job", "Resume": m["filename"],
                  "Match": f'{m["score"]:.1f}/100', "Date": m["created_at"][:16].replace("T", " ")} for m in matches],
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption("No matches yet. Your analyses will appear here.")


def _render_choose_step(student: dict) -> None:
    if st.button("← Back to dashboard", key="choose_back"):
        go_dashboard()
        st.rerun()
    st.title("Tailor your resume")
    st.caption("Step 1 of 3: choose the resume you want to tailor.")
    if student["guest"]:
        st.info("Guest mode: nothing is saved to an account. Download your files before you leave.")
        _render_upload_resume(student)
        return
    if st.session_state.get("choose_mode") == "saved":
        _render_saved_resumes(student)
    else:
        _render_upload_resume(student)


def _render_saved_resumes(student: dict) -> None:
    resumes = db.list_resumes(student["user_id"])
    if not resumes:
        st.info("You have no saved resumes yet. Upload a new one in the next tab.")
        return
    labels = {r["id"]: f'{r["filename"]} (uploaded {r["uploaded_at"][:10]})' for r in resumes}
    choice = st.selectbox("Saved resume", options=list(labels.keys()), format_func=lambda rid: labels[rid],
                          key="saved_choice")
    chosen = db.get_resume(student["user_id"], choice)
    version = db.latest_version(student["user_id"], choice)
    if chosen and version:
        st.write(f"**File:** {esc(chosen['filename'])}  \n**Uploaded:** {esc(chosen['uploaded_at'][:19])}  \n"
                 f"**Latest version:** {version['version_no']}")
        with st.expander("Preview saved resume", expanded=False):
            st.html(render_html(version["data"], "ATS-Friendly"))
        if st.button("Use this resume", type="primary", key="use_saved"):
            st.session_state["resume_data"] = version["data"]
            st.session_state["original_resume"] = db.first_version(student["user_id"], chosen["id"]) or version["data"]
            st.session_state["resume_source"] = {
                "kind": "saved", "resume_id": chosen["id"], "filename": chosen["filename"],
                "file_type": chosen["file_type"], "bytes": bytes(chosen["original_bytes"]),
            }
            reset_editor_state()
            st.session_state["student_step"] = "jd"
            st.rerun()


def _render_upload_resume(student: dict) -> None:
    st.write(f"Accepted formats: PDF or DOCX, up to {MAX_UPLOAD_MB:g} MB. Your original file is kept unchanged.")
    upload = st.file_uploader("Upload your resume", type=["pdf", "docx"], key="resume_upload")
    save_to_account = False
    if student["user_id"]:
        save_to_account = st.checkbox("Also save this as a new resume in my account", value=True, key="save_new")
    if upload and st.button("Read this resume", type="primary", key="read_upload"):
        content = upload.getvalue()
        try:
            data = parse_upload(upload.name, content)
        except ResumeParseError as exc:
            st.error(str(exc))
            st.session_state["resume_data"] = None
            return
        except Exception:
            st.error("The resume could not be read because of an unexpected error. Try another file.")
            return
        file_type = "pdf" if upload.name.lower().endswith(".pdf") else "docx"
        resume_id = None
        if save_to_account:
            resume_id = db.save_new_resume(student["user_id"], upload.name, file_type, content, _strip_meta(data))
        st.session_state["resume_data"] = _strip_meta(data)
        st.session_state["original_resume"] = copy.deepcopy(st.session_state["resume_data"])
        st.session_state["resume_source"] = {
            "kind": "upload", "resume_id": resume_id, "filename": upload.name,
            "file_type": file_type, "bytes": content,
        }
        st.session_state["upload_notice"] = data.get("parse_notes", [])
        reset_editor_state()
        st.session_state["student_step"] = "jd"
        st.rerun()


def _strip_meta(data: dict) -> dict:
    cleaned = dict(data)
    cleaned.pop("parse_notes", None)
    cleaned.pop("source_file_type", None)
    return cleaned


def _render_jd_step() -> None:
    st.markdown("<div class='hs-dialog-title'>Tailor to a job description</div>", unsafe_allow_html=True)
    st.caption("Add the job description. We will check your resume against it and suggest improvements you can "
               "review in the editor.")
    if st.session_state.get("upload_notice"):
        for note in st.session_state["upload_notice"]:
            st.info(note)
    with st.form("jd_form"):
        st.markdown("**Job description**")
        jd_file = st.file_uploader("Upload job description", type=["pdf", "docx", "txt"],
                                   help="PDF, DOCX, or TXT · up to " + f"{MAX_UPLOAD_MB:g}" + " MB", key="jd_upload")
        st.markdown("<div class='hs-or'>OR PASTE THE JD</div>", unsafe_allow_html=True)
        pasted = st.text_area("Paste the job description", height=200, label_visibility="collapsed",
                              placeholder="Paste the full job description here...")
        title = st.text_input("Job title (optional)", value=(st.session_state.get("jd") or {}).get("title", ""))
        company = st.text_input("Company name (optional)", value=(st.session_state.get("jd") or {}).get("company", ""))
        cancel_col, submit_col = st.columns([1, 1])
        with cancel_col:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)
        with submit_col:
            submitted = st.form_submit_button("Tailor my resume", type="primary", use_container_width=True)
    if cancelled:
        st.session_state["student_step"] = "choose"
        st.rerun()
    if submitted:
        try:
            text = read_jd_text(pasted, jd_file.name if jd_file else None, jd_file.getvalue() if jd_file else None)
        except JDError as exc:
            st.error(str(exc))
            return
        st.session_state["jd"] = {"title": clean_text(title, 120), "company": clean_text(company, 120), "text": text}
        st.session_state["jd_requirements"] = None
        st.session_state["stage_status"] = (
            ["done", "pending", "pending", "pending"] if st.session_state["resume_data"] else ["pending"] * 4
        )
        st.session_state["stage_error"] = ""
        st.session_state["student_step"] = "processing"
        st.rerun()


# ---------- processing ----------

def _stage_read_resume() -> None:
    if st.session_state["resume_data"] is not None:
        return
    source = st.session_state["resume_source"]
    if not source:
        raise RuntimeError("No resume is selected.")
    data = parse_upload(source["filename"], source["bytes"])
    st.session_state["resume_data"] = _strip_meta(data)
    st.session_state["original_resume"] = copy.deepcopy(st.session_state["resume_data"])
    st.session_state["upload_notice"] = data.get("parse_notes", [])


def _stage_read_jd() -> None:
    st.session_state["jd_requirements"] = extract_requirements(st.session_state["jd"]["text"])


def _stage_score() -> None:
    jd = st.session_state["jd"]
    result = analyze_match(st.session_state["resume_data"], jd["text"])
    st.session_state["match_current"] = result
    st.session_state["match_comparison"] = None
    source = st.session_state["resume_source"]
    student = st.session_state["student"]
    if student and student["user_id"] and source and source.get("resume_id"):
        db.save_analysis(student["user_id"], source["resume_id"], jd["title"], jd["text"], result)


def _stage_suggest() -> None:
    requirements = st.session_state["jd_requirements"]
    suggestions = generate_suggestions(st.session_state["resume_data"], requirements)
    st.session_state["suggestions"] = suggestions


STAGE_FUNCS = [_stage_read_resume, _stage_read_jd, _stage_score, _stage_suggest]


RESUME_ILLUSTRATION = """
<div class="hs-illustration">
  <svg width="260" height="200" viewBox="0 0 260 200" aria-hidden="true">
    <rect x="70" y="30" width="180" height="120" rx="12" fill="#f5f3ff" stroke="#ddd6fe"/>
    <rect x="30" y="50" width="150" height="130" rx="12" fill="#ffffff" stroke="#e5e7eb"/>
    <circle cx="62" cy="78" r="13" fill="#ede9fe"/>
    <rect x="86" y="72" width="70" height="6" rx="3" fill="#e5e7eb"/>
    <rect x="86" y="84" width="46" height="5" rx="2.5" fill="#f3f4f6"/>
    <rect x="46" y="108" width="110" height="5" rx="2.5" fill="#f3f4f6"/>
    <rect x="46" y="120" width="82" height="6" rx="3" fill="#c4b5fd"/>
    <rect x="46" y="136" width="100" height="5" rx="2.5" fill="#f3f4f6"/>
    <rect x="46" y="148" width="64" height="6" rx="3" fill="#6d28d9"/>
  </svg>
</div>
"""


def _render_processing() -> None:
    st.markdown(RESUME_ILLUSTRATION, unsafe_allow_html=True)
    st.markdown("<div class='hs-processing-title'>Tailoring your resume to this job description</div>",
                unsafe_allow_html=True)
    stages_box = st.empty()
    bar_box = st.empty()
    message_box = st.empty()
    retry_box = st.empty()

    statuses = st.session_state["stage_status"]
    for index, func in enumerate(STAGE_FUNCS):
        if statuses[index] == "done":
            continue
        if statuses[index] == "failed":
            break
        statuses[index] = "running"
        _draw(stages_box, bar_box, message_box, statuses, index, running=True)
        try:
            func()
        except Exception as exc:  # the stage is marked failed; the resume and JD are preserved
            statuses[index] = "failed"
            st.session_state["stage_error"] = _friendly_error(exc)
            _draw(stages_box, bar_box, message_box, statuses, index, running=False)
            with retry_box.container():
                st.error(st.session_state["stage_error"])
            if st.button("Retry this step", type="primary", key=f"retry_{index}"):
                statuses[index] = "pending"
                st.session_state["stage_error"] = ""
                st.rerun()
            if st.button("Back to job description", key="processing_back"):
                st.session_state["student_step"] = "jd"
                st.rerun()
            return
        statuses[index] = "done"
        _draw(stages_box, bar_box, message_box, statuses, index, running=False)

    st.session_state["student_step"] = "workspace"
    st.rerun()


def _draw(stages_box, bar_box, message_box, statuses, index, running: bool) -> None:
    """Progress moves only when a real stage completes. The bar never advances on a timer."""
    label, percent, message = STAGE_LABELS[index]
    stages_box.markdown(stage_list_html(statuses), unsafe_allow_html=True)
    completed = [p for (_, p, _), s in zip(STAGE_LABELS, statuses) if s == "done"]
    value = completed[-1] if completed else 0
    bar_box.progress(value / 100, text=f"{value}%")
    message_box.caption(message if running else f"{percent}% — {label} complete.")


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, ResumeParseError):
        return str(exc)
    return "This step failed. Your resume and job description are kept. Try again."


# ---------- workspace dashboard ----------

def _render_workspace(student: dict) -> None:
    jd = st.session_state["jd"]
    head_left, head_right = st.columns([3, 2])
    with head_left:
        st.markdown(f"<div class='hs-crumbs'>Dashboard &nbsp;»&nbsp; JD Tailor &nbsp;»&nbsp; "
                    f"{esc(st.session_state['resume_source']['filename'])}</div>", unsafe_allow_html=True)
        st.caption(f"Target: {jd.get('title') or 'Job'}{' at ' + jd['company'] if jd.get('company') else ''}")
    with head_right:
        b1, b2 = st.columns(2)
        if b1.button("Change job", key="change_jd", use_container_width=True):
            st.session_state["student_step"] = "jd"
            st.rerun()
        if b2.button("Change resume", key="change_resume", use_container_width=True):
            for key in ("resume_data", "original_resume", "resume_source", "match_current", "match_comparison", "suggestions"):
                st.session_state[key] = STUDENT_DEFAULTS[key]
            st.session_state["student_step"] = "choose"
            reset_editor_state()
            st.rerun()
    render_editor(student, logout_student)
