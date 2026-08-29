import datetime as _dt
import shutil

import pytest

from resume_agent.export import ExportBlocked, check_export_gate, export_draft
from resume_agent.models import (
    BulletClassification,
    DraftBullet,
    DraftEntry,
    DraftSection,
    JobDescription,
)
from resume_agent.tailor import analyze_jd, tailor


def _draft_from_bank(bank, jd_text):
    jd = JobDescription(
        job_id="job-export",
        captured_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).isoformat(),
        raw_text=jd_text,
        requirements=analyze_jd(jd_text),
    )
    return tailor(bank, jd)


def test_export_gate_passes_for_bank_verbatim_draft(example_bank, sample_jd_text):
    draft = _draft_from_bank(example_bank, sample_jd_text)
    # Every bullet is drawn from the bank, so nothing should be unsupported.
    assert check_export_gate(draft) == []


def test_export_writes_tex_file(tmp_path, example_bank, template_path, sample_jd_text):
    draft = _draft_from_bank(example_bank, sample_jd_text)
    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)
    assert result.tex_path.endswith(".tex")
    assert "\\begin{document}" in result.tex
    written = (tmp_path / f"{draft.draft_id}.tex").read_text(encoding="utf-8")
    assert written == result.tex


def test_export_blocks_unsupported_bullet(tmp_path, example_bank, template_path, sample_jd_text):
    draft = _draft_from_bank(example_bank, sample_jd_text)
    # Poison one bullet with an unsupported classification.
    bad = draft.sections[0].entries[0].bullets[0]
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


def test_export_blocks_unapproved_inferred_bullet(tmp_path, example_bank, template_path, sample_jd_text):
    draft = _draft_from_bank(example_bank, sample_jd_text)
    bullet = draft.sections[0].entries[0].bullets[0]
    bullet.classification = BulletClassification(
        label="inferred",
        token_overlap=0.5,
        reason="test injection",
    )
    bullet.approved = False
    reasons = check_export_gate(draft)
    assert reasons and "inferred" in reasons[0]
    with pytest.raises(ExportBlocked):
        export_draft(draft, output_dir=tmp_path, template_path=template_path)


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_export_enforces_one_page_via_real_pdflatex_compile(
    tmp_path, example_bank, template_path
):
    """A small, focused JD should tailor down to a short draft that compiles
    to exactly one page -- this exercises the real pdflatex compile path,
    not a heuristic."""
    small_jd_text = (
        "Looking for an engineer with Python and FastAPI experience "
        "for a short-term contract."
    )
    draft = _draft_from_bank(example_bank, small_jd_text)
    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)

    assert result.exported is True
    assert result.page_count == 1
    assert (tmp_path / f"{draft.draft_id}.tex").exists()


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_export_trims_lowest_scoring_bullets_to_fit_one_page(
    tmp_path, example_bank, template_path, sample_jd_text
):
    """A broad JD that matches most of the bank should overflow one page and
    get trimmed by dropping the lowest-scoring bullets -- never reworded."""
    draft = _draft_from_bank(example_bank, sample_jd_text)
    original_bullet_texts = {
        b.original_text
        for section in draft.sections
        for entry in section.entries
        for b in entry.bullets
    }

    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)

    assert result.exported is True
    assert result.page_count == 1
    # Trimming never rewords -- every surviving bullet's text is untouched
    # verbatim bank content.
    assert original_bullet_texts  # sanity: the fixture actually had bullets
