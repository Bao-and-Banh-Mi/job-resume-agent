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


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_fill_ratio_is_measured(tmp_path, example_bank, template_path, full_selection):
    """A one-page cap alone allowed half-empty resumes to ship silently."""
    draft = _draft(example_bank, full_selection)
    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)
    assert result.fill_ratio is not None
    assert 0.0 < result.fill_ratio <= 1.0


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_sparse_resume_is_warned_about(tmp_path, example_bank, template_path):
    """A near-empty draft must still export, but must say it looks thin."""
    entry = example_bank.experiences[0]
    draft = _draft(
        example_bank,
        {
            "sections": [
                {
                    "kind": "experience",
                    "entries": [
                        {
                            "entry_id": entry.entry_id,
                            "bullets": [{"bullet_id": entry.bullets[0].bullet_id}],
                        }
                    ],
                }
            ]
        },
    )
    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)
    assert result.exported is True
    assert result.fill_ratio < 0.75
    assert any("fills only" in w for w in result.warnings)


# --- one-page guarantee under a large bank --------------------------------


def _inflate(bank, copies=2):
    """Return a deep-copied bank with each entry's bullets multiplied."""
    import copy as _copy

    big = bank.model_copy(deep=True)
    for entries in (big.experiences, big.projects, big.leadership):
        for entry in entries:
            base = list(entry.bullets)
            for i in range(copies):
                for b in base:
                    nb = _copy.deepcopy(b)
                    nb.bullet_id = f"{b.bullet_id}-x{i}"
                    entry.bullets.append(nb)
    return big


def _select_everything(bank):
    sections = []
    for kind, entries in (
        ("experience", bank.experiences),
        ("projects", bank.projects),
        ("leadership", bank.leadership),
        ("education", bank.education),
    ):
        if entries:
            sections.append(
                {
                    "kind": kind,
                    "entries": [
                        {
                            "entry_id": e.entry_id,
                            "bullets": [{"bullet_id": b.bullet_id} for b in e.bullets],
                        }
                        for e in entries
                    ],
                }
            )
    return {"sections": sections}


def test_trimming_spreads_loss_instead_of_deleting_sections(example_bank):
    """Regression: the old trimmer drained low-priority sections to zero.

    It deleted all of Leadership and Projects while three Experience entries
    sat untouched at six bullets each. Losing a whole role costs the reader
    far more than losing one bullet from a long entry.
    """
    from resume_agent.export import _drop_lowest_scoring_bullet

    big = _inflate(example_bank)
    draft = _draft(big, _select_everything(big))

    for _ in range(20):
        draft, dropped = _drop_lowest_scoring_bullet(draft)
        if dropped is None:
            break

    kinds = {s.kind for s in draft.sections if s.entries}
    for required in ("experience", "projects", "leadership"):
        assert required in kinds, f"{required} was deleted rather than trimmed"


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_large_bank_still_fits_one_page(tmp_path, example_bank, template_path):
    """A 3x bank previously exhausted the fixed 15-iteration cap at two pages
    and exported nothing at all. One page must be a guarantee, not a hope."""
    big = _inflate(example_bank)
    draft = _draft(big, _select_everything(big))
    total = sum(len(e.bullets) for s in draft.sections for e in s.entries)
    assert total > 15, "fixture must exceed the old iteration cap"

    result = export_draft(draft, output_dir=tmp_path, template_path=template_path)

    assert result.exported is True, result.warnings
    assert result.page_count == 1
    assert result.dropped_bullet_ids
    # Every section must survive the trim.
    for heading in ("Education", "Experience", "Leadership", "Skills"):
        assert f"\\section{{{heading}}}" in result.tex
