import datetime as _dt

from resume_agent.latex_renderer import escape_latex, render_draft
from resume_agent.models import JobDescription
from resume_agent.tailor import analyze_jd, tailor


def test_escape_latex_handles_specials():
    assert escape_latex("50% & $100 gain") == r"50\% \& \$100 gain"
    assert escape_latex("a_b") == r"a\_b"
    assert escape_latex("~^") == r"\textasciitilde{}\textasciicircum{}"
    # Backslash must be escaped first so it doesn't wrap later replacements.
    assert escape_latex("\\") == r"\textbackslash{}"


def test_render_draft_produces_document(example_bank, template_path, sample_jd_text):
    jd = JobDescription(
        job_id="job-render",
        captured_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).isoformat(),
        raw_text=sample_jd_text,
        requirements=analyze_jd(sample_jd_text),
    )
    draft = tailor(example_bank, jd)
    tex = render_draft(draft, template_path)
    assert "\\begin{document}" in tex
    assert "\\end{document}" in tex
    assert "\\section{Experience}" in tex
    assert "\\resumeItemListStart" in tex
    # Owner name should appear in the header.
    assert example_bank.owner.name in tex
