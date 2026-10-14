"""
app.py - Streamlit frontend. This file handles ONLY the user interface.

STRICT RULES FOR THIS FILE:
  - No direct Gemini API calls.
  - No SQL queries.
  - No business logic.
  - It calls services/analyzer.py and storage/sqlite_store.py and renders results.

WHY KEEP UI SEPARATE?
If you ever replace Streamlit with a React frontend or a CLI tool, the entire
analysis engine (Phase 2) and storage layer (Phase 3) can be reused without
changing a single line. The UI is a thin skin over the real logic.
"""

import streamlit as st
from datetime import datetime

import config
from config import validate_config
from models.schemas import AnalysisRecord, AnalysisResult
from services.analyzer import analyze, AnalysisError
from services.pdf_reader import extract_text_from_pdf, PDFReadError
from storage.sqlite_store import SQLiteStorage

# ---------------------------------------------------------------------------
# Page Configuration (must be the very first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Resume & Job Match Analyzer",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Shared Storage Instance
# ---------------------------------------------------------------------------
# st.cache_resource tells Streamlit to create this object ONCE and reuse it
# across all reruns and all users. Without it, a new SQLiteStorage (and a
# new DB connection) would be created on every single button click.
@st.cache_resource
def get_storage() -> SQLiteStorage:
    """Returns a shared, cached instance of the SQLite storage backend."""
    return SQLiteStorage()


# ---------------------------------------------------------------------------
# Helper: Score Color
# ---------------------------------------------------------------------------
def score_color(score: int) -> str:
    """
    Returns a color string based on the score value.
    Green = strong match, Orange = partial match, Red = weak match.
    This makes the score instantly readable without reading numbers.
    """
    if score >= 75:
        return "green"
    elif score >= 50:
        return "orange"
    else:
        return "red"


def score_label(score: int) -> str:
    """Returns a human-readable label for the overall match score."""
    if score >= 75:
        return "Strong Match 🟢"
    elif score >= 50:
        return "Partial Match 🟡"
    else:
        return "Weak Match 🔴"


# ---------------------------------------------------------------------------
# Helper: Render a Full Analysis Result
# ---------------------------------------------------------------------------
def render_analysis(result: AnalysisResult, job_title: str = "") -> None:
    """
    Renders the complete analysis output in a structured, readable layout.
    Called both from the Analyze page and the History detail view.

    Args:
        result: The validated AnalysisResult Pydantic object.
        job_title: Optional job title string for display purposes.
    """
    # --- Top Summary Bar ---
    color = score_color(result.overall_score)
    label = score_label(result.overall_score)

    st.markdown(f"### {label}")
    st.markdown(
        f"<h1 style='color:{color}; font-size: 4rem; margin: 0;'>"
        f"{result.overall_score}<span style='font-size:1.5rem; color:gray;'>/100</span>"
        f"</h1>",
        unsafe_allow_html=True
    )
    st.caption(f"_{result.one_line_summary}_")
    st.divider()

    # --- Category Score Breakdown ---
    st.subheader("📊 Score Breakdown")
    col1, col2, col3, col4 = st.columns(4)

    def score_metric(col, label, score, max_score):
        """Renders a single category metric with a mini progress bar."""
        pct = score / max_score
        col.metric(label=label, value=f"{score:.0f} / {max_score}")
        col.progress(pct)

    score_metric(col1, "🛠 Skills Match",       result.category_scores.skills_match,         40)
    score_metric(col2, "💼 Experience",          result.category_scores.experience_relevance,  25)
    score_metric(col3, "🔍 ATS Keywords",        result.category_scores.keywords_ats,          20)
    score_metric(col4, "🎓 Education & Projects", result.category_scores.education_and_projects, 15)

    st.divider()

    # --- Two-Column: Matched / Missing Skills ---
    col_matched, col_missing = st.columns(2)

    with col_matched:
        st.subheader("✅ Matched Skills")
        if result.matched_skills:
            # Display each skill as a colored tag using HTML
            tags = " ".join(
                f"<span style='background:#d4edda; color:#155724; padding:3px 10px; "
                f"border-radius:12px; margin:3px; display:inline-block;'>{s}</span>"
                for s in result.matched_skills
            )
            st.markdown(tags, unsafe_allow_html=True)
        else:
            st.info("No matched skills found.")

    with col_missing:
        st.subheader("❌ Missing Skills")
        if result.missing_skills:
            # Importance-to-color mapping for visual priority
            importance_colors = {
                "high":   ("#f8d7da", "#721c24"),   # red
                "medium": ("#fff3cd", "#856404"),   # yellow
                "low":    ("#d1ecf1", "#0c5460"),   # blue
            }
            for ms in result.missing_skills:
                bg, fg = importance_colors.get(ms.importance, ("#e2e3e5", "#383d41"))
                st.markdown(
                    f"<span style='background:{bg}; color:{fg}; padding:3px 10px; "
                    f"border-radius:12px; margin:3px; display:inline-block;'>"
                    f"{ms.skill} ({ms.importance})</span>",
                    unsafe_allow_html=True
                )
        else:
            st.success("No missing skills — great fit!")

    st.divider()

    # --- Expandable Detail Sections ---
    # Using st.expander means the page stays clean; users open only what they need.
    with st.expander("💪 Strengths", expanded=True):
        for strength in result.strengths:
            st.markdown(f"- {strength}")

    with st.expander("📝 Suggestions to Improve Your Resume", expanded=True):
        for sg in result.suggestions:
            st.markdown(
                f"**[{sg.section}]** {sg.suggestion}"
            )


# ===========================================================================
# PAGE: ANALYZE
# ===========================================================================
def show_analyze_page(storage: SQLiteStorage) -> None:
    """Renders the main resume analysis page."""
    st.title("📄 Resume & Job Match Analyzer")
    st.markdown("Upload or paste your resume, paste the job description, and get an AI-powered match score.")
    st.divider()

    # --- API Key Guard ---
    # Warn the user upfront if the key is missing, before they fill in inputs.
    is_valid_config, config_error = validate_config()
    if not is_valid_config:
        st.error(f"⚠️ Configuration Error: {config_error}")
        st.info("Open the `.env` file in your project folder and add your `GEMINI_API_KEY`.")
        st.stop()  # Halt rendering — no point showing the form without an API key

    # --- Input Layout ---
    left_col, right_col = st.columns([1, 1], gap="large")

    with left_col:
        st.subheader("Your Resume")

        # Toggle between PDF upload and pasting text
        input_mode = st.radio(
            "Input method:",
            options=["📤 Upload PDF", "✏️ Paste Text"],
            horizontal=True,
            label_visibility="collapsed"
        )

        resume_text = ""

        if input_mode == "📤 Upload PDF":
            uploaded_file = st.file_uploader(
                "Upload your resume PDF",
                type=["pdf"],
                help="Only PDF files are supported. Make sure it contains real text (not a scanned image)."
            )
            if uploaded_file is not None:
                # Show a spinner while extracting text from the PDF
                with st.spinner("Reading PDF..."):
                    try:
                        resume_text = extract_text_from_pdf(uploaded_file)
                        st.success(f"✅ Resume loaded: {len(resume_text):,} characters extracted.")
                    except PDFReadError as e:
                        st.error(f"❌ Could not read PDF: {e}")
                        resume_text = ""
        else:
            resume_text = st.text_area(
                "Paste your resume text here:",
                height=300,
                placeholder="John Smith\nSoftware Engineer\nSkills: Python, Django...",
            )

    with right_col:
        st.subheader("Job Description")
        job_title = st.text_input(
            "Job Title (for your records):",
            placeholder="e.g. Senior Python Developer",
        )
        job_description = st.text_area(
            "Paste the full job description here:",
            height=300,
            placeholder="We are hiring a Python Backend Developer...",
        )

    st.divider()

    # --- Input Validation & Warnings ---
    # These checks give instant feedback before touching the API.
    resume_len = len(resume_text.strip())
    job_len = len(job_description.strip())

    can_analyze = True

    if resume_len > 0 and resume_len < config.MIN_RESUME_CHARS:
        st.warning(f"⚠️ Resume text is too short ({resume_len} chars). Minimum: {config.MIN_RESUME_CHARS}.")
        can_analyze = False
    if job_len > 0 and job_len < config.MIN_JOB_DESC_CHARS:
        st.warning(f"⚠️ Job description is too short ({job_len} chars). Minimum: {config.MIN_JOB_DESC_CHARS}.")
        can_analyze = False
    if resume_len > config.MAX_TEXT_CHARS:
        st.warning(f"⚠️ Resume too long ({resume_len:,} chars). Maximum: {config.MAX_TEXT_CHARS:,}.")
        can_analyze = False
    if job_len > config.MAX_TEXT_CHARS:
        st.warning(f"⚠️ Job description too long ({job_len:,} chars). Maximum: {config.MAX_TEXT_CHARS:,}.")
        can_analyze = False

    # Disable the button if we already know inputs are invalid
    analyze_clicked = st.button(
        "🔍 Analyze Match",
        type="primary",
        disabled=not can_analyze,
        use_container_width=True,
    )

    # --- Analysis Trigger ---
    if analyze_clicked:
        if not resume_text.strip():
            st.error("Please upload a PDF or paste your resume text first.")
            st.stop()
        if not job_description.strip():
            st.error("Please paste a job description.")
            st.stop()

        # Run the analysis with a full-page spinner
        with st.spinner("🤖 Analyzing your resume against the job description... this takes about 30–60 seconds."):
            try:
                result = analyze(resume_text, job_description)

                # Build the record to save
                record = AnalysisRecord(
                    created_at=datetime.utcnow(),
                    job_title=job_title.strip() if job_title.strip() else "Untitled Role",
                    resume_source=getattr(
                        st.session_state.get("uploaded_file"), "name", "[Pasted Text]"
                    ) if input_mode == "📤 Upload PDF" else "[Pasted Text]",
                    result=result,
                )
                saved_id = storage.save_analysis(record)

                # Store in session state so the result stays visible on rerun
                st.session_state["last_result"] = result
                st.session_state["last_record_id"] = saved_id
                st.session_state["last_job_title"] = record.job_title

                st.success(f"✅ Analysis complete! Saved to history (ID: `{saved_id[:8]}...`).")

            except ValueError as e:
                # Input validation error from analyzer.py
                st.error(f"❌ Input Error: {e}")
                st.stop()
            except AnalysisError as e:
                # Gemini API failure after all retries
                st.error(f"❌ Analysis Failed: {e}")
                st.stop()

    # --- Result Display ---
    # Show results from session state so they persist across reruns
    if "last_result" in st.session_state:
        st.divider()
        job_title_display = st.session_state.get("last_job_title", "")
        if job_title_display:
            st.markdown(f"### Results for: *{job_title_display}*")
        render_analysis(st.session_state["last_result"], job_title_display)

        # --- Download Button ---
        # Generate a plain-text markdown report for download
        result: AnalysisResult = st.session_state["last_result"]
        report_lines = [
            f"# Resume Analysis Report",
            f"**Job Title:** {st.session_state.get('last_job_title', 'N/A')}",
            f"**Date:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"",
            f"## Overall Score: {result.overall_score} / 100",
            f"_{result.one_line_summary}_",
            f"",
            f"## Category Scores",
            f"| Category | Score | Max |",
            f"|---|---|---|",
            f"| Skills Match | {result.category_scores.skills_match} | 40 |",
            f"| Experience Relevance | {result.category_scores.experience_relevance} | 25 |",
            f"| ATS Keywords | {result.category_scores.keywords_ats} | 20 |",
            f"| Education & Projects | {result.category_scores.education_and_projects} | 15 |",
            f"",
            f"## Matched Skills",
            ", ".join(result.matched_skills) if result.matched_skills else "None",
            f"",
            f"## Missing Skills",
        ]
        for ms in result.missing_skills:
            report_lines.append(f"- [{ms.importance.upper()}] {ms.skill}")
        report_lines += ["", "## Strengths"]
        for s in result.strengths:
            report_lines.append(f"- {s}")
        report_lines += ["", "## Suggestions"]
        for sg in result.suggestions:
            report_lines.append(f"**[{sg.section}]** {sg.suggestion}")

        report_text = "\n".join(report_lines)
        st.download_button(
            label="⬇️ Download Report (Markdown)",
            data=report_text,
            file_name=f"resume_analysis_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.md",
            mime="text/markdown",
        )


# ===========================================================================
# PAGE: HISTORY
# ===========================================================================
def show_history_page(storage: SQLiteStorage) -> None:
    """
    Renders the full analysis history page.

    Design: A selectbox lists all past analyses as one-line summaries.
    Selecting one loads and renders the full result below.
    WHY SELECTBOX? Streamlit doesn't natively support clickable table rows.
    A selectbox is the simplest, most accessible alternative.
    """
    st.title("📋 Analysis History")

    records = storage.get_all()
    if not records:
        st.warning("No analyses saved yet. Go to **Analyze** to run your first analysis!")
        return

    st.markdown(f"**{len(records)}** analysis result(s) saved.")
    st.divider()

    # Build display labels for the selectbox: "Job Title — Score/100 — Date"
    def record_label(rec) -> str:
        date_str = rec.created_at.strftime("%Y-%m-%d %H:%M")
        return f"{rec.job_title}  —  {rec.result.overall_score}/100  —  {date_str}"

    labels = [record_label(r) for r in records]

    selected_label = st.selectbox(
        "Select a past analysis to view:",
        options=labels,
        index=0,
    )

    # Find the selected record by matching the label
    selected_index = labels.index(selected_label)
    selected_record = records[selected_index]

    st.divider()

    # Show metadata header
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Job Title", selected_record.job_title)
    col_b.metric("Resume Source", selected_record.resume_source)
    col_c.metric("Date", selected_record.created_at.strftime("%d %b %Y, %H:%M"))

    st.divider()

    # Render the full analysis breakdown
    render_analysis(selected_record.result, selected_record.job_title)

    # Download button for historical record
    result = selected_record.result
    report_lines = [
        f"# Resume Analysis Report",
        f"**Job Title:** {selected_record.job_title}",
        f"**Date:** {selected_record.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Resume Source:** {selected_record.resume_source}",
        f"",
        f"## Overall Score: {result.overall_score} / 100",
        f"_{result.one_line_summary}_",
        f"",
        f"## Category Scores",
        f"| Category | Score | Max |",
        f"|---|---|---|",
        f"| Skills Match | {result.category_scores.skills_match} | 40 |",
        f"| Experience Relevance | {result.category_scores.experience_relevance} | 25 |",
        f"| ATS Keywords | {result.category_scores.keywords_ats} | 20 |",
        f"| Education & Projects | {result.category_scores.education_and_projects} | 15 |",
        f"",
        f"## Matched Skills",
        ", ".join(result.matched_skills) or "None",
        f"",
        f"## Missing Skills",
    ]
    for ms in result.missing_skills:
        report_lines.append(f"- [{ms.importance.upper()}] {ms.skill}")
    report_lines += ["", "## Strengths"]
    for s in result.strengths:
        report_lines.append(f"- {s}")
    report_lines += ["", "## Suggestions"]
    for sg in result.suggestions:
        report_lines.append(f"**[{sg.section}]** {sg.suggestion}")

    st.download_button(
        label="⬇️ Download This Report (Markdown)",
        data="\n".join(report_lines),
        file_name=f"analysis_{selected_record.job_title.replace(' ', '_')}_{selected_record.created_at.strftime('%Y%m%d')}.md",
        mime="text/markdown",
    )


# ===========================================================================
# PAGE: COMPARE
# ===========================================================================
def show_compare_page(storage: SQLiteStorage) -> None:
    """
    Renders the before/after comparison page.

    Lets the user pick two past analyses and see the score delta per category.
    Useful for checking whether editing a resume actually improved the match score.

    WHY DELTA DISPLAY?
    Showing raw scores side by side requires mental arithmetic. Showing the 
    delta (e.g., +8 skills, -2 ATS) gives instant, actionable insight.
    """
    st.title("⚖️ Compare Two Analyses")
    st.markdown("Select two past analyses to compare their scores side by side.")

    records = storage.get_all()

    if len(records) < 2:
        st.warning(
            "You need at least **2 saved analyses** to compare. "
            "Run more analyses on the **Analyze** page first."
        )
        return

    # Build selection labels
    def record_label(rec) -> str:
        date_str = rec.created_at.strftime("%Y-%m-%d %H:%M")
        return f"{rec.job_title}  —  {rec.result.overall_score}/100  —  {date_str}"

    labels = [record_label(r) for r in records]

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📄 Analysis A  *(e.g. before edits)*")
        label_a = st.selectbox("Select Analysis A:", options=labels, index=0, key="compare_a")

    with col2:
        st.markdown("#### 📄 Analysis B  *(e.g. after edits)*")
        # Default to second record so A ≠ B on first render
        default_b = 1 if len(labels) > 1 else 0
        label_b = st.selectbox("Select Analysis B:", options=labels, index=default_b, key="compare_b")

    if label_a == label_b:
        st.warning("Please select two different analyses to compare.")
        return

    idx_a = labels.index(label_a)
    idx_b = labels.index(label_b)
    rec_a = records[idx_a]
    rec_b = records[idx_b]

    st.divider()

    # --- Overall Score Comparison ---
    ov_a = rec_a.result.overall_score
    ov_b = rec_b.result.overall_score
    delta = ov_b - ov_a
    delta_str = f"+{delta}" if delta > 0 else str(delta)
    delta_color = "green" if delta > 0 else ("red" if delta < 0 else "gray")

    st.markdown("### Overall Score")
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Analysis A", f"{ov_a}/100")
    col_s2.metric("Analysis B", f"{ov_b}/100")
    col_s3.markdown(
        f"**Change:** <span style='color:{delta_color}; font-size:1.4rem;'>{delta_str} pts</span>",
        unsafe_allow_html=True
    )

    st.divider()

    # --- Category-by-Category Comparison Table ---
    st.markdown("### Category Breakdown")

    categories = [
        ("🛠 Skills Match",         "skills_match",         40),
        ("💼 Experience",            "experience_relevance",  25),
        ("🔍 ATS Keywords",          "keywords_ats",          20),
        ("🎓 Education & Projects",  "education_and_projects", 15),
    ]

    # Table header
    header_cols = st.columns([3, 1.5, 1.5, 1.5])
    header_cols[0].markdown("**Category**")
    header_cols[1].markdown("**Analysis A**")
    header_cols[2].markdown("**Analysis B**")
    header_cols[3].markdown("**Change**")

    st.markdown("---")

    for label, attr, max_score in categories:
        score_a = getattr(rec_a.result.category_scores, attr)
        score_b = getattr(rec_b.result.category_scores, attr)
        cat_delta = score_b - score_a
        cat_delta_str = f"+{cat_delta:.1f}" if cat_delta > 0 else f"{cat_delta:.1f}"
        cat_color = "green" if cat_delta > 0 else ("red" if cat_delta < 0 else "gray")

        row = st.columns([3, 1.5, 1.5, 1.5])
        row[0].markdown(f"{label} *(max {max_score})*")
        row[1].markdown(f"**{score_a:.1f}**")
        row[2].markdown(f"**{score_b:.1f}**")
        row[3].markdown(
            f"<span style='color:{cat_color}; font-weight:bold;'>{cat_delta_str}</span>",
            unsafe_allow_html=True
        )

    st.divider()

    # --- Skills Comparison ---
    st.markdown("### Skills Changes")

    skills_a = set(rec_a.result.matched_skills)
    skills_b = set(rec_b.result.matched_skills)
    newly_gained = skills_b - skills_a
    newly_lost   = skills_a - skills_b
    still_present = skills_a & skills_b

    col_g, col_l, col_s = st.columns(3)

    with col_g:
        st.markdown("**✅ Newly Matched**")
        if newly_gained:
            for sk in sorted(newly_gained):
                st.markdown(f"<span style='color:green;'>+ {sk}</span>", unsafe_allow_html=True)
        else:
            st.caption("None")

    with col_l:
        st.markdown("**❌ No Longer Matched**")
        if newly_lost:
            for sk in sorted(newly_lost):
                st.markdown(f"<span style='color:red;'>− {sk}</span>", unsafe_allow_html=True)
        else:
            st.caption("None")

    with col_s:
        st.markdown("**➡️ Still Matched**")
        if still_present:
            for sk in sorted(still_present):
                st.caption(sk)
        else:
            st.caption("None")


# ===========================================================================
# MAIN ROUTER
# ===========================================================================
def main() -> None:
    """
    Entry point. Sets up the sidebar navigation and routes to the correct page.

    WHY SESSION STATE?
    Streamlit reruns the entire script top-to-bottom on every user interaction
    (every button click, every text input change). st.session_state is a 
    dictionary that persists values between those reruns within one browser 
    session. We use it to hold the last analysis result so it doesn't vanish
    when the user clicks "Download".
    """
    storage = get_storage()

    # --- Sidebar Navigation ---
    with st.sidebar:
        st.markdown("## 📄 Resume Analyzer")
        st.markdown("---")
        page = st.radio(
            "Navigate to:",
            options=["🔍 Analyze", "📋 History", "⚖️ Compare"],
            label_visibility="collapsed",
        )
        st.markdown("---")
        st.caption(f"Model: `{config.GEMINI_MODEL}`")
        st.caption("Powered by Google Gemini API")

    # --- Page Routing ---
    if page == "🔍 Analyze":
        show_analyze_page(storage)
    elif page == "📋 History":
        show_history_page(storage)
    elif page == "⚖️ Compare":
        show_compare_page(storage)


if __name__ == "__main__":
    main()
