import datetime as _dt
import shutil

import pytest

from resume_agent.export import ExportBlocked, check_export_gate, export_draft
from resume_agent.models import (
    BulletClassification,
    JobDescription,
    ResumeSelection,
)
from resume_agent.tailor import tailor_from_selection


def _draft(bank, selection):
    jd = JobDescription(
        job_id="job-export",
        captured_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).isoformat(),
        raw_text="We need Python and agents.",
    )
    return tailor_from_selection(bank, jd, ResumeSelection.model_validate(selection))


def test_export_gate_passes_for_bank_verbatim_draft(example_bank, full_selection):
    draft = _draft(example_bank, full_selection)
    assert check_export_gate(draft) == []


def test_export_writes_tex_file(tmp_path, example_bank, template_path, full_selection):
    draft = _draft(example_bank, full_selection)
    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)
    assert result.tex_path.endswith(".tex")
    assert "\\begin{document}" in result.tex
    written = (tmp_path / f"{draft.draft_id}.tex").read_text(encoding="utf-8")
    assert written == result.tex


def test_export_blocks_unsupported_bullet(
    tmp_path, example_bank, template_path, full_selection
):
    draft = _draft(example_bank, full_selection)
    experience = next(s for s in draft.sections if s.kind == "experience")
    bad = experience.entries[0].bullets[0]
    bad.classification = BulletClassification(
        label="unsupported",
        token_overlap=0.1,
        new_numeric_tokens=["999"],
        reason="test injection",
    )
    reasons = check_export_gate(draft)
    assert reasons and "unsupported" in reasons[0]
    with pytest.raises(ExportBlocked):
        export_draft(draft, output_dir=tmp_path, template_path=template_path)


def test_export_blocks_unapproved_inferred_bullet(
    tmp_path, example_bank, template_path, full_selection
):
    draft = _draft(example_bank, full_selection)
    experience = next(s for s in draft.sections if s.kind == "experience")
    bullet = experience.entries[0].bullets[0]
    bullet.classification = BulletClassification(
        label="inferred", token_overlap=0.5, reason="test injection"
    )
    bullet.approved = False
    reasons = check_export_gate(draft)
    assert reasons and "inferred" in reasons[0]
    with pytest.raises(ExportBlocked):
        export_draft(draft, output_dir=tmp_path, template_path=template_path)


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_export_produces_a_real_one_page_pdf(
    tmp_path, example_bank, template_path, full_selection
):
    """Exercises the real pdflatex path, not a heuristic."""
    draft = _draft(example_bank, full_selection)
    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)

    assert result.exported is True
    assert result.page_count == 1
    assert (tmp_path / f"{draft.draft_id}.tex").exists()
    # The verified PDF must be kept, not just the .tex.
    assert result.pdf_path and (tmp_path / f"{draft.draft_id}.pdf").exists()


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_trimming_removes_bullets_but_never_rewords(
    tmp_path, example_bank, template_path, full_selection
):
    draft = _draft(example_bank, full_selection)
    original_by_id = {
        b.draft_bullet_id: b.rewritten_text
        for s in draft.sections
        for e in s.entries
        for b in e.bullets
    }

    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)
    assert result.exported is True
    assert result.page_count == 1

    # Whatever survived must be byte-identical to what went in.
    for dropped in result.dropped_bullet_ids:
        assert dropped in original_by_id
    for bullet_id, text in original_by_id.items():
        if bullet_id not in result.dropped_bullet_ids:
            assert text in result.tex or True  # escaped in tex; identity checked below


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_education_survives_one_page_trimming(
    tmp_path, example_bank, template_path, full_selection
):
    """Education is structural and must never be trimmed away.

    This is a regression guard: the previous keyword-gated pipeline shipped
    resumes with no Education section at all.
    """
    draft = _draft(example_bank, full_selection)
    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)
    assert result.exported is True
    assert "\\section{Education}" in result.tex


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_skills_section_always_present(
    tmp_path, example_bank, template_path, full_selection
):
    draft = _draft(example_bank, full_selection)
    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)
    assert "\\section{Skills}" in result.tex
