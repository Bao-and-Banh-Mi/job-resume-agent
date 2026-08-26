import datetime as _dt

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
