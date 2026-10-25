"""Shared styling, sidebar and small rendering helpers."""

import html

import streamlit as st

PURPLE = "#6d28d9"

APP_CSS = """
<style>
:root { --hs-purple: #6d28d9; --hs-text: #1f2937; --hs-muted: #9ca3af; }
.stApp { background: #ffffff; color: #1f2937; }
[data-testid="stSidebar"] { background: #f3f4f6; }
.hs-brand { font-size: 30px; font-weight: 800; color: #6d28d9; letter-spacing: -0.5px; }
.hs-tagline { color: #4b5563; font-size: 16px; margin-bottom: 18px; }
.hs-card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 18px 20px; background: #ffffff; }
.hs-muted { color: #6b7280; }
.hs-score { font-size: 56px; font-weight: 800; color: #6d28d9; line-height: 1; }
.hs-stage { display: flex; align-items: center; gap: 12px; padding: 8px 0; font-size: 16px; }
.hs-dot { width: 14px; height: 14px; border-radius: 50%; background: #d1d5db; display: inline-block; }
.hs-dot.running { border: 2px solid #6d28d9; background: #ffffff; box-sizing: border-box; }
.hs-dot.done { background: #6d28d9; }
.hs-check { color: #6d28d9; font-weight: 700; width: 14px; text-align: center; }
.hs-pending { color: #9ca3af; }
.hs-running { color: #1f2937; font-weight: 700; }
.hs-failed { color: #b91c1c; font-weight: 600; }
.hs-dialog-title { font-size: 24px; font-weight: 700; color: #1f2937; margin-bottom: 4px; }
.hs-or { text-align: center; color: #6b7280; font-size: 12px; letter-spacing: 0.08em; margin: 14px 0 6px; }
.hs-illustration { text-align: center; margin: 16px 0 8px 0; }
.hs-processing-title { text-align: center; color: #4b5563; margin-bottom: 12px; }
.hs-doc-icon { text-align: center; font-size: 72px; color: #6d28d9; margin: 8px 0; }
.stButton > button[kind="primary"] { background: #6d28d9; border-color: #6d28d9; color: #ffffff; border-radius: 8px; }
.stButton > button { border-radius: 8px; }
.stDownloadButton > button { border-radius: 8px; }
.hs-crumbs { color: #6b7280; font-size: 14px; margin-bottom: 4px; }
.hs-donut { position: relative; width: 170px; height: 170px; margin: 8px auto 4px auto; }
.hs-donut svg { position: absolute; top: 0; left: 0; }
.hs-donut-label { position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; text-align: center; }
.hs-donut-value { font-size: 36px; font-weight: 800; color: #1f2937; line-height: 1.1; }
.hs-pill { background: #ede9fe; color: #5b21b6; border-radius: 999px; padding: 2px 10px;
  font-size: 13px; margin-top: 4px; }
.hs-card-purple { border: 1px solid #c4b5fd; border-radius: 12px; padding: 14px 16px; background: #faf5ff;
  color: #1f2937; margin-bottom: 12px; }
.hs-frame { border: 1px solid #e5e7eb; border-radius: 14px; overflow: hidden; background: #ffffff;
  box-shadow: 0 12px 30px -14px rgba(0, 0, 0, 0.18); }
.hs-frame-bar { display: flex; align-items: center; gap: 6px; padding: 8px 12px; background: #f9fafb;
  border-bottom: 1px solid #f0f1f3; }
.hs-frame-dot { width: 9px; height: 9px; border-radius: 50%; background: #e5e7eb; display: inline-block; }
.hs-chip { margin-left: auto; font-size: 12px; color: #374151; background: #ffffff; border: 1px solid #e5e7eb;
  border-radius: 999px; padding: 2px 10px; }
.hs-tag { display: inline-block; font-size: 11px; color: #b45309; background: #fef3c7; border-radius: 6px;
  padding: 1px 7px; margin-right: 4px; }
.hs-review { border: 1px solid #e5e7eb; border-radius: 14px; padding: 18px; background: #ffffff; margin-bottom: 14px; }
.hs-review-ring { position: relative; width: 130px; height: 130px; margin: 0 auto; }
.hs-review-ring svg { position: absolute; top: 0; left: 0; }
.hs-review-ring-value { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 34px; font-weight: 800; color: #1f2937; }
.hs-review-label { text-align: center; font-weight: 700; color: #1f2937; margin-top: 8px; }
.hs-review-rows { margin-top: 14px; }
.hs-review-row { display: flex; align-items: center; gap: 8px; font-size: 14px; color: #1f2937; margin-top: 10px; }
.hs-review-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.hs-review-name { flex: 1; }
.hs-review-score { font-weight: 700; }
.hs-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 6px; }
.hs-pill-strong { background: #6d28d9; color: #ffffff; border-radius: 999px; padding: 4px 12px; font-weight: 700; white-space: nowrap; }
.hs-group { font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #6d28d9; margin: 14px 0 6px; }
.hs-group-count { background: #ede9fe; color: #5b21b6; border-radius: 999px; padding: 1px 8px; margin-left: 4px; }
.hs-bar-row { margin: 8px 0; font-size: 14px; color: #1f2937; }
.hs-bar-track { height: 8px; background: #ede9fe; border-radius: 999px; overflow: hidden; margin-top: 4px; }
.hs-bar-fill { height: 100%; background: #6d28d9; border-radius: 999px; }
.hs-a4 { background: #ffffff; width: 100%; aspect-ratio: 210 / 297; overflow: hidden; box-sizing: border-box;
  box-shadow: 0 1px 8px rgba(0, 0, 0, 0.12); border-radius: 4px; }
.hs-a4 > div { width: 100%; }
.st-key-preview_page img { max-height: 84vh; width: auto !important; margin: 0 auto; display: block; }
.hs-paper { background: #ffffff; box-shadow: 0 1px 8px rgba(0, 0, 0, 0.12); border-radius: 4px;
  max-height: 760px; overflow-y: auto; }
</style>
"""


def inject_css() -> None:
    st.markdown(APP_CSS, unsafe_allow_html=True)


def brand_block() -> None:
    st.markdown('<div class="hs-brand">HireSense AI</div>', unsafe_allow_html=True)


def esc(value) -> str:
    return html.escape(str(value or ""))


def show_error(message: str) -> None:
    st.error(message)


def sidebar(role_label: str | None, display_name: str | None, logout_key: str, on_logout,
            footer: bool = True) -> None:
    """Brand and identity at the top. Dashboard and Log out sit at the bottom unless the page adds its own footer."""
    with st.sidebar:
        brand_block()
        st.caption("Intelligent resume builder and screening")
        if role_label:
            st.markdown(f"**{esc(display_name) or 'Signed in'}**")
            st.caption(f"Role: {role_label}")
        if footer:
            with st.container(key="sidebar_bottom"):
                footer_buttons(logout_key, on_logout, bool(role_label))


def footer_buttons(logout_key: str, on_logout, signed_in: bool) -> None:
    """Line, Dashboard and Log out, and the local-build note. Call inside a sidebar container."""
    st.divider()
    if signed_in:
        st.button("Dashboard", key="dashboard_btn", use_container_width=True, on_click=_go_dashboard)
        st.button("Log out", key=logout_key, on_click=on_logout, use_container_width=True)
    st.caption("Local development build. No account or API key is required for the resume builder.")


def _go_dashboard() -> None:
    st.session_state["student_step"] = "dashboard"


STAGE_LABELS = [
    ("Reading your resume", 15,
     "Pulling out your experience, your skills, and the evidence behind them."),
    ("Reading the job description", 30,
     "Identifying the skills, experience, and qualifications the role asks for."),
    ("Scoring your match", 65,
     "Checking every claim against your resume and calculating the weighted score."),
    ("Writing your fixes", 100,
     "Preparing evidence-based improvements for your resume."),
]


def stage_list_html(states: list[str]) -> str:
    """states: 'pending' | 'running' | 'done' | 'failed' for each of the four stages."""
    rows = []
    for (label, _, _), state in zip(STAGE_LABELS, states):
        if state == "done":
            indicator = '<span class="hs-check">&#10003;</span>'
            text_class = "hs-running"
        elif state == "running":
            indicator = '<span class="hs-dot running"></span>'
            text_class = "hs-running"
        elif state == "failed":
            indicator = '<span class="hs-failed">!</span>'
            text_class = "hs-failed"
        else:
            indicator = '<span class="hs-dot"></span>'
            text_class = "hs-pending"
        rows.append(f'<div class="hs-stage">{indicator}<span class="{text_class}">{esc(label)}</span></div>')
    return "".join(rows)
