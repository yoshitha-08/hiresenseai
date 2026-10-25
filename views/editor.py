"""Three-panel resume editor: match ring and section navigation (left), editor and suggestions (middle),
and live preview with template and downloads (right).

Single source of truth: st.session_state["resume_data"]. Widgets write into it on every run, and the
preview is rendered from it on every run.
"""

import hashlib
import html
import copy
import json
import traceback

import streamlit as st

from hiresense import db
from hiresense import resume_model as rm
from hiresense.document_edit import apply_to_file, docx_preview_lines, docx_to_pdf, render_pdf_pages
from hiresense.matching_engine import analyze_match, compare_results
from hiresense.suggestion_engine import apply_suggestion, generate_suggestions

from views.breakdown import donut_html, render_match_breakdown
from views.common import esc, footer_buttons

MAX_LEN = rm.MAX_FIELD_LENGTH
MIN_PAGE_SCALE = 0.4

# Left-panel navigation: (key, label). "personal" holds Profile, Summary and Links.
SECTION_NAV = [
    ("personal", "Personal Details"),
    ("experience", "Experience"),
    ("education", "Education"),
    ("skills", "Skills"),
    ("projects", "Projects"),
    ("certifications", "Certifications"),
    ("interests", "Interests"),
    ("achievements", "Achievements"),
    ("unclassified", "Additional Content"),
]
NAV_KEYS = [key for key, _ in SECTION_NAV]
NAV_LABEL = dict(SECTION_NAV)
# Which navigation item a suggestion's resume section belongs to.
SUGGESTION_NAV = {"summary": "personal", "links": "personal", None: "skills"}

# Fields shown for each entry section: (field, label).
ENTRY_FIELDS = {
    "experience": [("organization", "Company name"), ("title", "Role"), ("location", "Location")],
    "internships": [("organization", "Company name"), ("title", "Role"), ("location", "Location")],
    "education": [("organization", "School"), ("title", "Degree"), ("field_of_study", "Field of study")],
    "projects": [("title", "Project name"), ("organization", "Organization"), ("location", "Location")],
    "certifications": [("title", "Certification name"), ("organization", "Issuer")],
}
ENTRY_HAS_BULLETS = {"experience", "internships", "projects"}
ENTRY_HAS_GRADE = {"education"}
LINK_LABELS = ["GitHub", "LinkedIn", "Portfolio", "Other"]
SECTION_NAME_FOR_ADD = {"experience": "Add another job", "internships": "Add another internship",
                        "education": "Add another school", "projects": "Add another project",
                        "certifications": "Add another certification"}


def reset_editor_state() -> None:
    st.session_state["editor_rev"] = 0
    st.session_state["suggestion_status"] = {}
    st.session_state["nav_section"] = "personal"
    st.session_state["saved_snapshot"] = None
    st.session_state.pop("save_notice", None)


def _rev() -> int:
    return st.session_state.get("editor_rev", 0)


def _bump_rev() -> None:
    st.session_state["editor_rev"] = _rev() + 1


def _data() -> dict:
    return st.session_state["resume_data"]


def _sync(container: dict, field: str, new_value: str, label: str) -> None:
    """Copy a widget value into the resume. Over-length input is reported and not applied."""
    if new_value == container.get(field, ""):
        return
    if len(new_value) > MAX_LEN:
        st.error(f"{label} is longer than {MAX_LEN} characters. Your previous text was kept.")
        return
    container[field] = new_value


def _text(label: str, container: dict, field: str, key: str, multiline: bool = False, height: int = 90,
          placeholder: str | None = None) -> None:
    current = container.get(field, "")
    if multiline:
        value = st.text_area(label, value=current, key=key, height=height, placeholder=placeholder)
    else:
        value = st.text_input(label, value=current, key=key, placeholder=placeholder)
    _sync(container, field, value, label)


def _split_dates(dates: str) -> tuple[str, str]:
    """Split 'Jun 2024 – Aug 2024' into start and end. Text that does not split stays as the start."""
    for separator in (" – ", " - ", " — ", " to "):
        if separator in dates:
            start, end = dates.split(separator, 1)
            return start.strip(), end.strip()
    return dates.strip(), ""


def _join_dates(start: str, end: str) -> str:
    start, end = start.strip(), end.strip()
    if start and end:
        return f"{start} – {end}"
    return start or end


# ---------- actions ----------

def _current_score(data: dict) -> float:
    return analyze_match(data, st.session_state["jd"]["text"])["score"]


def _refresh_match() -> None:
    """Score the resume again whenever it changes. Runs automatically; there is no button."""
    data = _data()
    key = hashlib.sha1(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
    if st.session_state.get("match_hash") == key:
        return
    previous = st.session_state.get("match_current")
    updated = analyze_match(data, st.session_state["jd"]["text"])
    if previous is not None:
        st.session_state["match_comparison"] = compare_results(previous, updated)
    st.session_state["match_current"] = updated
    st.session_state["match_hash"] = key


def _save_version() -> None:
    student = st.session_state["student"]
    source = st.session_state["resume_source"]
    version_no = db.add_resume_version(student["user_id"], source["resume_id"], _data(), "Saved from editor")
    st.session_state["saved_snapshot"] = _snapshot()
    st.session_state["save_notice"] = f"Saved as version {version_no}."


def _snapshot() -> str:
    return json.dumps(_data(), sort_keys=True)


def _go(nav_key: str) -> None:
    st.session_state["nav_section"] = nav_key


def _run(operation, *args) -> None:
    """Run a model operation from a button callback, then refresh the widget keys."""
    try:
        operation(_data(), *args)
    except (ValueError, KeyError) as exc:
        st.session_state["editor_error"] = str(exc)
    _bump_rev()


def _add_entry(section: str) -> None:
    rm.add_entry(_data(), section, "")
    _bump_rev()


def _add_text_from(section: str, input_key: str, kind: str) -> None:
    text = st.session_state.get(input_key, "").strip()
    if not text:
        return
    try:
        if kind == "skill":
            rm.add_skill(_data(), text)
        elif kind == "link":
            rm.add_link(_data(), "GitHub", text)
        else:
            rm.add_item(_data(), section, text)
    except ValueError as exc:
        st.session_state["editor_error"] = str(exc)
    _bump_rev()


def _suggestion_pending() -> list[dict]:
    status = st.session_state["suggestion_status"]
    return [s for s in st.session_state["suggestions"] if status.get(s["id"], "pending") == "pending"]


def _pending_by_nav() -> dict:
    counts: dict[str, int] = {}
    for suggestion in _suggestion_pending():
        section = suggestion["target"].get("section")
        nav = SUGGESTION_NAV.get(section, section)
        if nav not in NAV_LABEL:
            nav = "skills"
        counts[nav] = counts.get(nav, 0) + 1
    return counts


# ---------- layout ----------

def render_editor(student: dict, on_logout) -> None:
    if st.session_state.get("saved_snapshot") is None:
        st.session_state["saved_snapshot"] = _snapshot()
    if st.session_state.get("editor_error"):
        st.error(st.session_state.pop("editor_error"))
    _refresh_match()

    with st.sidebar:
        _render_sidebar_navigation()
        with st.container(key="sidebar_bottom"):
            _render_match_ring()
            footer_buttons("logout_student_btn", on_logout, signed_in=True)

    data = _data()
    tabs_col, actions_col = st.columns([3, 2], vertical_alignment="center")
    with tabs_col:
        view = st.segmented_control(
            "View", ["Editor", "Suggestions"], default="Editor", key="main_view", label_visibility="collapsed",
        ) or "Editor"
    with actions_col:
        _download_menu(data)

    if view == "Suggestions":
        suggestions_col, preview_col = st.columns([0.55, 0.45], gap="large")
        with suggestions_col:
            st.caption(f"{len(_suggestion_pending())} suggestion(s) to review")
            _render_suggestions()
        with preview_col:
            _render_preview(data)
        return
    form_col, preview_col = st.columns([0.42, 0.58], gap="large")
    with form_col:
        _render_editor_body(student)
    with preview_col:
        _render_preview(data)


def _render_sidebar_navigation() -> None:
    pending = _pending_by_nav()
    st.radio(
        "Section",
        NAV_KEYS,
        format_func=lambda key: f"{NAV_LABEL[key]}  ({pending[key]} fix{'es' if pending[key] != 1 else ''})"
        if pending.get(key) else NAV_LABEL[key],
        key="nav_section",
        label_visibility="collapsed",
    )


def _render_match_ring() -> None:
    result = st.session_state.get("match_current") or {"score": 0.0, "improvements": []}
    projected = min(100.0, result["score"] + sum(i["estimate_points"] for i in result["improvements"]))
    st.markdown(donut_html(result["score"], projected), unsafe_allow_html=True)
    st.caption("Projected value is an estimate from the missing required skills. It is not a guarantee.")
    comparison = st.session_state.get("match_comparison")
    if comparison:
        st.metric("Score change", f'{comparison["updated_score"]:.1f}', delta=f'{comparison["score_change"]:+.1f}')
        st.caption("Updates automatically with each edit and accepted suggestion.")


def _render_editor_body(student: dict) -> None:
    nav = st.session_state.get("nav_section", "personal")
    data = _data()
    rev = _rev()
    st.subheader(NAV_LABEL[nav])

    if nav != "personal":
        hidden = nav in data.get("hidden_sections", [])
        visible = st.checkbox("Show this section in the resume", value=not hidden, key=f"vis:{nav}")
        if visible == hidden:
            rm.set_section_visible(data, nav, visible)
            st.rerun()

    if nav == "personal":
        _render_personal(data, rev)
    elif nav in ENTRY_FIELDS or nav in ("experience", "projects", "certifications", "internships", "education"):
        _render_entries(nav, rev)
    elif nav == "skills":
        _render_skills(rev)
    else:
        _render_items(nav, rev)

    _render_footer(student, nav)


def _render_footer(student: dict, nav: str) -> None:
    st.divider()
    changed = _snapshot() != st.session_state.get("saved_snapshot")
    left, middle, right = st.columns([1.5, 0.9, 2])
    with left:
        if student["guest"]:
            st.caption("Guest mode: download your resume to keep changes.")
        elif st.session_state["resume_source"].get("resume_id"):
            st.caption("Unsaved changes" if changed else "No unsaved changes")
        else:
            st.caption("Not saved to your account.")
    with middle:
        if not student["guest"] and st.session_state["resume_source"].get("resume_id"):
            st.button("Save", key="save_version", on_click=_save_version)
    with right:
        order = [key for key in NAV_KEYS]
        index = order.index(nav)
        if index + 1 < len(order):
            following = order[index + 1]
            st.button(f"Next: {NAV_LABEL[following]}", key=f"next:{nav}", type="primary",
                      on_click=_go, args=(following,), use_container_width=True)
    if st.session_state.get("save_notice"):
        st.success(st.session_state.pop("save_notice"))


# ---------- personal details, summary and links ----------

def _render_personal(data: dict, rev: int) -> None:
    cols = st.columns(2)
    with cols[0]:
        _text("Name", data["personal"], "name", key=f"personal:name:{rev}")
    with cols[1]:
        _text("Role", data["personal"], "role", key=f"personal:role:{rev}", placeholder="e.g. Senior analyst")
    cols = st.columns(2)
    with cols[0]:
        _text("Email", data["personal"], "email", key=f"personal:email:{rev}", placeholder="Enter your email")
    with cols[1]:
        _text("Phone", data["personal"], "phone", key=f"personal:phone:{rev}", placeholder="Enter your phone number")
    _text("Location", data["personal"], "location", key=f"personal:location:{rev}", placeholder="e.g. Bangalore")
    _text("Summary", data, "summary", key=f"summary:{rev}", multiline=True, height=120)

    st.markdown("**Links**")
    for link in data["links"]:
        lid = link["id"]
        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 2.4, 0.5])
            options = LINK_LABELS if link.get("label") in LINK_LABELS or not link.get("label") \
                else LINK_LABELS + [link["label"]]
            with c1:
                label = st.selectbox("Type", options, index=options.index(link.get("label") or "GitHub"),
                                     key=f"link:{lid}:label:{rev}", label_visibility="collapsed")
            with c2:
                url = st.text_input("URL", value=link.get("url", ""), key=f"link:{lid}:url:{rev}",
                                    placeholder="Paste link", label_visibility="collapsed")
            with c3:
                st.button("✕", key=f"linkx:{lid}", help="Remove link",
                          on_click=_run, args=(rm.delete_link, lid))
            link["label"] = label
            _sync(link, "url", url, "Link")
    st.button("Add another link", key=f"addlink:{rev}", on_click=_run, args=(rm.add_link, "GitHub", ""))


# ---------- entry sections ----------

def _render_entries(section: str, rev: int) -> None:
    data = _data()
    header_left, header_right = st.columns([3, 1.4])
    with header_left:
        st.caption(f"{len(data[section])} item(s)")
    with header_right:
        st.button(SECTION_NAME_FOR_ADD.get(section, "Add another"), key=f"addentry:{section}:{rev}",
                  on_click=_add_entry, args=(section,), use_container_width=True)

    for index, entry in enumerate(data[section]):
        eid = entry["id"]
        title_shown = entry.get("organization") or entry.get("title") or "(untitled entry)"
        with st.container(border=True):
            top_a, top_b, top_c, top_d = st.columns([5, 1, 1, 1.4])
            with top_a:
                st.markdown(f"**{esc(title_shown)}**")
            with top_b:
                st.button("↑", key=f"eu:{section}:{eid}", help="Move up", disabled=index == 0,
                          on_click=_run, args=(rm.move_entry, section, eid, -1))
            with top_c:
                st.button("↓", key=f"ed:{section}:{eid}", help="Move down", disabled=index == len(data[section]) - 1,
                          on_click=_run, args=(rm.move_entry, section, eid, 1))
            with top_d:
                with st.popover("Delete"):
                    st.warning("This removes the entry and its bullet points.")
                    st.button("Confirm delete", key=f"ex:{section}:{eid}", type="primary",
                              on_click=_run, args=(rm.delete_entry, section, eid))

            for field, label in ENTRY_FIELDS.get(section, []):
                _text(label, entry, field, key=f"{section}:{eid}:{field}:{rev}")
            _render_duration(section, entry, rev)
            if section in ENTRY_HAS_GRADE:
                _text("Grade", entry, "grade", key=f"{section}:{eid}:grade:{rev}")
            if section in ENTRY_HAS_BULLETS:
                st.caption("Description")
                for bullet in entry["bullets"]:
                    bid = bullet["id"]
                    _render_fix_tags(bid)
                    value = st.text_area("Description point", value=bullet["text"],
                                         key=f"{section}:{eid}:{bid}:{rev}", height=70,
                                         label_visibility="collapsed")
                    _sync(bullet, "text", value, "Description point")
                    st.button("Remove point", key=f"bx:{section}:{bid}",
                              on_click=_run, args=(rm.delete_bullet, section, eid, bid))
                st.button("Add description point", key=f"ab:{section}:{eid}",
                          on_click=_run, args=(rm.add_bullet, section, eid, ""))
            _text("Link", entry, "link", key=f"{section}:{eid}:link:{rev}", placeholder="Enter URL")
    if not data[section]:
        st.info("Nothing here yet. Use the button above to add an entry.")


def _render_fix_tags(item_id: str) -> None:
    """Small tags showing which pending fixes touch this bullet."""
    labels = sorted({
        s["issue"].split(" (")[0] for s in _suggestion_pending()
        if s["target"].get("item_id") == item_id
    })
    if labels:
        st.markdown("".join(f'<span class="hs-tag">{esc(label)}</span>' for label in labels), unsafe_allow_html=True)


def _render_duration(section: str, entry: dict, rev: int) -> None:
    eid = entry["id"]
    if section == "certifications":
        _text("Date", entry, "dates", key=f"{section}:{eid}:dates:{rev}")
        return
    start, end = _split_dates(entry.get("dates", ""))
    current_role = end.lower() in ("present", "ongoing", "current")
    toggle_key = f"{section}:{eid}:current:{rev}"
    c1, c2 = st.columns(2)
    with c1:
        new_start = st.text_input("Start", value=start, key=f"{section}:{eid}:start:{rev}", placeholder="e.g. Jun 2024")
    with c2:
        new_end = st.text_input("End", value="Ongoing" if current_role else end,
                                key=f"{section}:{eid}:end:{rev}", disabled=current_role,
                                placeholder="e.g. Aug 2024")
    now_current = st.toggle("Current role" if section != "education" else "Still studying",
                            value=current_role, key=toggle_key)
    entry["dates"] = _join_dates(new_start, "Present" if now_current else new_end)


# ---------- skills and simple lists ----------

def _render_skills(rev: int) -> None:
    """Name and Level table. Level is stored in the skill's group field and shown in the preview."""
    data = _data()
    head_name, head_level, _ = st.columns([3, 2, 0.6])
    head_name.markdown("**Name**")
    head_level.markdown("**Level**")
    for skill in data["skills"]:
        sid = skill["id"]
        c1, c2, c3 = st.columns([3, 2, 0.6], vertical_alignment="center")
        with c1:
            _text("Skill name", skill, "name", key=f"skill:{sid}:name:{rev}")
        with c2:
            _text("Skill level", skill, "category", key=f"skill:{sid}:level:{rev}", placeholder="Optional")
        with c3:
            st.button("", key=f"sx:{sid}", icon=":material/delete:", help="Remove skill",
                      on_click=_run, args=(rm.delete_skill, sid))
    st.text_input("New skill", key=f"newskill:{rev}", placeholder="e.g. Python")
    st.button("Add another", key=f"addskill:{rev}", icon=":material/add:",
              on_click=_add_text_from, args=("skills", f"newskill:{rev}", "skill"))


def _render_items(section: str, rev: int) -> None:
    data = _data()
    for item in data[section]:
        iid = item["id"]
        with st.container(border=True):
            value = st.text_area("Item", value=item["text"], key=f"item:{section}:{iid}:{rev}", height=70,
                                 label_visibility="collapsed")
            _sync(item, "text", value, rm.SECTION_TITLES[section])
            c1, c2, c3 = st.columns([1, 1, 1])
            c1.button("↑", key=f"iu:{section}:{iid}", on_click=_run, args=(rm.move_item, section, iid, -1))
            c2.button("↓", key=f"id:{section}:{iid}", on_click=_run, args=(rm.move_item, section, iid, 1))
            c3.button("Remove", key=f"ix:{section}:{iid}", on_click=_run, args=(rm.delete_item, section, iid))
    st.text_input("New item", key=f"newitem:{section}:{rev}")
    st.button("Add item", key=f"additem:{section}:{rev}",
              on_click=_add_text_from, args=(section, f"newitem:{section}:{rev}", "item"))


# ---------- preview and downloads ----------

def _edited_document(data: dict):
    """The user's own file with the edits applied. Cached until the resume changes."""
    source = st.session_state.get("resume_source")
    original = st.session_state.get("original_resume")
    if not source or original is None:
        return None
    key = hashlib.sha1(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()
    cached = st.session_state.get("_doc_cache")
    if cached and cached[0] == key:
        return cached[1]
    try:
        result = apply_to_file(source["filename"], source["bytes"], original, data)
    except Exception as exc:
        traceback.print_exc()
        st.error(f"Your file could not be edited ({type(exc).__name__}: {exc}). Your changes are kept in the editor.")
        return None
    st.session_state["_doc_cache"] = (key, result)
    return result


def _render_preview(data: dict) -> None:
    """The uploaded file with your edits applied, so the preview is what gets downloaded."""
    source = st.session_state.get("resume_source")
    result = _edited_document(data)
    if not source or result is None:
        st.info("Upload a resume to see it here.")
        return
    new_bytes, failed, unsupported = result
    if source["filename"].lower().endswith(".pdf"):
        pages = render_pdf_pages(new_bytes)
        with st.container(key="preview_page", height=820 if len(pages) > 1 else None):
            for png in pages:
                st.image(png, use_container_width=True)
    else:
        try:
            pages = render_pdf_pages(docx_to_pdf(new_bytes))
        except Exception as exc:
            traceback.print_exc()
            st.warning(f"Word page preview is unavailable ({type(exc).__name__}). Showing the text instead.")
            lines = docx_preview_lines(new_bytes)
            body = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
            st.html(f'<div class="hs-a4" style="font-size:11px;padding:24px;overflow:auto">{body}</div>')
        else:
            with st.container(key="preview_page", height=820 if len(pages) > 1 else None):
                for png in pages:
                    st.image(png, use_container_width=True)
    _show_edit_notes(failed, unsupported)


def _show_edit_notes(failed: list[str], unsupported: list[str]) -> None:
    if failed:
        st.warning("Could not place these changes in your file (they are not lost; they stay in the editor): "
                   + "; ".join(item[:60] for item in failed))
    if unsupported:
        st.info("These new items need a place in your file before they can be added: "
                + "; ".join(unsupported[:5]))


def _download_menu(data: dict) -> None:
    """One download button in the format the user uploaded: PDF stays PDF, Word stays Word."""
    source = st.session_state.get("resume_source")
    result = _edited_document(data)
    if not source or result is None:
        return
    extension = source["filename"].rsplit(".", 1)[-1].lower()
    stem = source["filename"].rsplit(".", 1)[0]
    mime = ("application/pdf" if extension == "pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    st.download_button(f"Download {extension.upper()}", data=result[0], file_name=f"{stem}.{extension}",
                       mime=mime, key="dl_edited", use_container_width=True)


# ---------- suggestions ----------

def _render_suggestions() -> None:
    result = st.session_state.get("match_current") or {"score": 0.0, "improvements": []}
    score = result["score"]
    projected = min(100.0, score + sum(i["estimate_points"] for i in result["improvements"]))
    gap = max(0.0, projected - score)
    st.markdown(
        f'<div class="hs-card-purple"><div class="hs-row"><b>You are about {gap:.0f} points away from a stronger '
        f'JD match</b><span class="hs-pill-strong">{projected:.0f}% potential</span></div>'
        f'<div class="hs-muted">{score:.0f}% current &rarr; {projected:.0f}% potential. Estimates only; '
        f'nothing is guaranteed.</div></div>',
        unsafe_allow_html=True,
    )
    if st.toggle("See the breakdown", key="show_breakdown"):
        render_match_breakdown()
    if st.button("Refresh suggestions", key="refresh_sugg"):
        st.session_state["suggestions"] = generate_suggestions(_data(), st.session_state.get("jd_requirements"))
        st.rerun()

    pending = _suggestion_pending()
    if not pending:
        st.success("No pending suggestions. Use Refresh suggestions after you make changes.")
        return
    st.markdown(f'<div class="hs-group">Free to apply <span class="hs-group-count">{len(pending)}</span></div>',
                unsafe_allow_html=True)
    st.caption("Suggestions are proposals. Nothing changes until you apply it, and you can edit the text first. "
               "HireSense AI never invents skills, employers, dates, metrics or achievements.")
    for suggestion in pending:
        _render_one_suggestion(suggestion)


def _render_one_suggestion(suggestion: dict) -> None:
    sid = suggestion["id"]
    with st.container(border=True):
        st.markdown(f"<span class='hs-muted'>{esc(suggestion['section_title'])}</span> &middot; "
                    f"<b>{esc(suggestion['issue'])}</b>", unsafe_allow_html=True)
        st.caption(f"Why it may help: {suggestion['explanation']}")
        if suggestion["target"].get("section") is None or not suggestion["editable"]:
            st.markdown("<span class='hs-tag'>Needs your input</span>", unsafe_allow_html=True)
            st.caption("Nothing will be added to your resume automatically.")
            if st.button("Dismiss", key=f"dismiss:{sid}"):
                st.session_state["suggestion_status"][sid] = "dismissed"
                st.rerun()
            return
        st.caption(f"Original: {suggestion['original'] or '(no text)'}")
        edited = st.text_area("Proposed text (edit before applying)", value=suggestion["proposed"],
                              key=f"sugg_text:{sid}", height=90, label_visibility="collapsed")
        a1, a2 = st.columns(2)
        if a1.button("Apply", key=f"accept:{sid}", type="primary", use_container_width=True):
            trial = copy.deepcopy(_data())
            try:
                changed = apply_suggestion(trial, suggestion, edited)
            except ValueError as exc:
                st.error(str(exc))
            else:
                before = _current_score(_data())
                after = _current_score(trial)
                if after < before:
                    st.error(f"Not applied: this wording would lower your match from {before:.1f} to {after:.1f}. "
                             "Keep the skill or evidence in the sentence and try again.")
                else:
                    apply_suggestion(_data(), suggestion, edited)
                    st.session_state["suggestion_status"][sid] = "accepted"
                    if changed:
                        _bump_rev()
                    st.rerun()
        if a2.button("Dismiss", key=f"dismiss:{sid}", use_container_width=True):
            st.session_state["suggestion_status"][sid] = "dismissed"
            st.rerun()
