import datetime as _dt

from resume_agent.latex_renderer import escape_latex, render_draft
from resume_agent.models import JobDescription, ResumeSelection
from resume_agent.tailor import tailor_from_selection


def test_escape_latex_handles_specials():
    assert escape_latex("50% & $100 gain") == r"50\% \& \$100 gain"
    assert escape_latex("a_b") == r"a\_b"
    assert escape_latex("~^") == r"\textasciitilde{}\textasciicircum{}"
    # Backslash must be escaped first so it doesn't wrap later replacements.
    assert escape_latex("\\") == r"\textbackslash{}"


def _draft(example_bank, selection):
    jd = JobDescription(
        job_id="job-render",
        captured_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).isoformat(),
        raw_text="anything",
    )
    return tailor_from_selection(
        example_bank, jd, ResumeSelection.model_validate(selection)
    )


def test_render_draft_produces_document(example_bank, template_path, full_selection):
    draft = _draft(example_bank, full_selection)
    tex = render_draft(draft, template_path)
    assert "\\begin{document}" in tex
    assert "\\end{document}" in tex
    assert "\\section{Experience}" in tex
    assert "\\resumeItemListStart" in tex
    assert example_bank.owner.name in tex


def test_education_renders_even_with_no_bullets(
    example_bank, template_path, full_selection
):
    """Education entries are header-only in most banks; they must still render.

    The renderer previously relied on the tailor never emitting a bullet-less
    entry. Education is now always included, so this path is load-bearing.
    """
    draft = _draft(example_bank, {"sections": [], "rationale": "education only"})
    tex = render_draft(draft, template_path)
    assert "\\section{Education}" in tex
    assert example_bank.education[0].organization in tex


def test_skills_section_renders_from_bank_fallback(
    example_bank, template_path
):
    draft = _draft(example_bank, {"sections": []})
    tex = render_draft(draft, template_path)
    assert "\\section{Skills}" in tex
