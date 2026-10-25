"""HireSense AI: student resume builder. Run with: streamlit run app.py"""

import streamlit as st

from hiresense import db
from views.common import inject_css, sidebar
from views.student import (
    init_student_state,
    logout_student,
    render_student_entry,
    render_student_workspace,
)

st.set_page_config(page_title="HireSense AI", page_icon="📄", layout="wide", initial_sidebar_state="expanded")


@st.cache_resource(show_spinner=False)
def _initialize_database() -> bool:
    db.init_db()  # creates missing tables only; never deletes data
    return True


def main() -> None:
    _initialize_database()
    inject_css()
    init_student_state()
    student = st.session_state.get("student")

    if not student:
        sidebar(None, None, "unused_logout", lambda: None)
        render_student_entry()
        return

    label = "Student (guest)" if student.get("guest") else "Student"
    sidebar(label, student["name"], "logout_student_btn", logout_student, footer=False)
    render_student_workspace()


main()
