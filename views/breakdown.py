"""Match breakdown: score ring, matched and missing requirements, and the scoring method."""

import streamlit as st

from views.common import esc


def donut_html(score: float, projected: float | None) -> str:
    """Purple progress ring. Numbers come from the matching engine only."""
    radius, circumference = 70, 2 * 3.14159265 * 70
    offset = circumference * (1 - max(0.0, min(100.0, score)) / 100)
    projected_tag = ""
    if projected is not None and projected > score:
        projected_tag = f'<div class="hs-pill">Projected {projected:.0f}%</div>'
    return (
        '<div class="hs-donut">'
        '<svg width="170" height="170" viewBox="0 0 170 170">'
        '<circle cx="85" cy="85" r="%d" stroke="#ede9fe" stroke-width="16" fill="none"/>'
        '<circle cx="85" cy="85" r="%d" stroke="#6d28d9" stroke-width="16" fill="none" stroke-linecap="round"'
        ' stroke-dasharray="%.2f" stroke-dashoffset="%.2f" transform="rotate(-90 85 85)"/>'
        '</svg>'
        '<div class="hs-donut-label"><div class="hs-muted">Your match</div>'
        '<div class="hs-donut-value">%.0f%%</div>%s</div>'
        '</div>'
    ) % (radius, radius, circumference, offset, score, projected_tag)


def review_label(score: float) -> str:
    """Status word for the score. Bands match the shortlisting defaults: 75 and up, 60 to 74, below 60."""
    if score >= 75:
        return "Strong match"
    if score >= 60:
        return "Fair match"
    return "Needs work"


def _dot_colour(percent: float) -> str:
    if percent >= 75:
        return "#16a34a"
    if percent >= 60:
        return "#d97706"
    return "#dc2626"


def review_card_html(result: dict) -> str:
    """JD match review: score ring with a status word, then one row per applicable category."""
    score = result["score"]
    radius, circumference = 52, 2 * 3.14159265 * 52
    offset = circumference * (1 - max(0.0, min(100.0, score)) / 100)
    rows = []
    for category in result["categories"]:
        if not category["applicable"]:
            continue
        percent = round(category["ratio"] * 100)
        colour = _dot_colour(percent)
        rows.append(
            f'<div class="hs-review-row">'
            f'<span class="hs-review-dot" style="background:{colour}"></span>'
            f'<span class="hs-review-name">{esc(category["label"])}</span>'
            f'<span class="hs-review-score">{percent}<span class="hs-muted">/100</span></span>'
            f'</div>'
            f'<div class="hs-bar-track"><div class="hs-bar-fill" style="width:{percent}%;background:{colour}"></div></div>'
        )
    return (
        '<div class="hs-review">'
        '<div class="hs-review-ring">'
        '<svg width="130" height="130" viewBox="0 0 130 130">'
        '<circle cx="65" cy="65" r="%d" stroke="#e5e7eb" stroke-width="10" fill="none"/>'
        '<circle cx="65" cy="65" r="%d" stroke="#6d28d9" stroke-width="10" fill="none" stroke-linecap="round"'
        ' stroke-dasharray="%.2f" stroke-dashoffset="%.2f" transform="rotate(-90 65 65)"/>'
        '</svg>'
        '<div class="hs-review-ring-value">%.0f</div>'
        '</div>'
        '<div class="hs-review-label">%s</div>'
        '<div class="hs-muted">Compatibility estimate out of 100</div>'
        '<div class="hs-review-rows">%s</div>'
        '</div>'
    ) % (radius, radius, circumference, offset, score, esc(review_label(score)), "".join(rows))


def category_bars_html(categories: list[dict]) -> str:
    """One bar per applicable scoring category. Width is the evidence ratio from the matching engine."""
    rows = []
    for category in categories:
        if not category["applicable"]:
            continue
        percent = round(category["ratio"] * 100)
        rows.append(
            f'<div class="hs-bar-row"><div>{esc(category["label"])} <span class="hs-muted">{percent}/100</span></div>'
            f'<div class="hs-bar-track"><div class="hs-bar-fill" style="width:{percent}%"></div></div></div>'
        )
    return "".join(rows)


def render_match_breakdown() -> None:
    result = st.session_state.get("match_current")
    if not result:
        st.info("No analysis yet.")
        return
    if result["insufficient_signal"]:
        st.warning("The job description has no recognizable requirements, so no fair score can be calculated. "
                   "The score shown is 0 for that reason.")
    for note in result["notes"]:
        st.caption(note)
    if result["years_note"]:
        st.info(result["years_note"])

    st.markdown(review_card_html(result), unsafe_allow_html=True)

    matched_col, missing_col = st.columns(2)
    with matched_col:
        st.subheader("Matched skills")
        if result["matched_terms"]:
            for term, info in sorted(result["matched_terms"].items()):
                strength = {"explicit": "explicit", "contextual": "contextual evidence",
                            "weak": "weak evidence"}[info["strength"]]
                st.write(f"- **{esc(term)}** ({strength}; {esc(', '.join(info['sections']))})")
        else:
            st.write("No recognized skills were matched.")
    with missing_col:
        st.subheader("Missing requirements")
        st.write("**Required:** " + (esc(", ".join(result["missing_required"])) or "none"))
        st.write("**Preferred:** " + (esc(", ".join(result["missing_preferred"])) or "none"))
        st.caption("Missing means not found in this resume. It does not prove you lack the skill.")

    st.subheader("Relevant experience and projects")
    if result["relevant_entries"]:
        for entry in result["relevant_entries"]:
            st.write(f"- {esc(entry['title'])} ({entry['section']}) — mentions {esc(', '.join(entry['matched_terms']))}")
    else:
        st.write("No experience, internship, or project entry was found that mentions the job's skills.")

    edu_col, kw_col = st.columns(2)
    with edu_col:
        st.subheader("Education and qualifications")
        st.write("**Found:** " + (", ".join(result["education"]["matched"]) or "none"))
        st.write("**Not found:** " + (", ".join(result["education"]["missing"]) or "none"))
    with kw_col:
        st.subheader("Relevant keywords")
        st.write("**Found:** " + (", ".join(result["keywords"]["matched"]) or "none"))
        st.write("**Not found:** " + (", ".join(result["keywords"]["missing"]) or "none"))

    st.subheader("Uncertain or unsupported requirements")
    if result["uncertain_terms"]:
        st.write("Only weak evidence was found (for example in interests or links): "
                 + ", ".join(result["uncertain_terms"]))
    else:
        st.write("None.")

    with st.expander("How was this score calculated?"):
        st.write("Each category earns points from its evidence ratio. Categories that do not apply to this job "
                 "description are removed and the remaining weights are rescaled to 100.")
        st.table([
            {
                "Category": c["label"],
                "Base weight": f'{c["weight"]:g}%',
                "Applies": "yes" if c["applicable"] else "no (not in JD)",
                "Effective weight": f'{c["effective_weight"]:.1f}%' if c["applicable"] else "-",
                "Evidence ratio": f'{c["ratio"] * 100:.0f}%' if c["applicable"] else "-",
                "Points": f'{c["points"]:.1f}' if c["applicable"] else "-",
            }
            for c in result["categories"]
        ])
        st.caption("Partial evidence counts as weak (half credit). Repeated mentions of the same skill do not add "
                   "points.")
