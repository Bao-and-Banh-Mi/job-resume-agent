from __future__ import annotations

import datetime as _dt

from resume_agent.models import JobDescription
from resume_agent.skills_match import match_skills
from resume_agent.tailor import analyze_jd


def _mk_jd(text: str, job_id: str = "job-skills-test") -> JobDescription:
    return JobDescription(
        job_id=job_id,
        captured_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).isoformat(),
        raw_text=text,
        requirements=analyze_jd(text),
    )


def test_match_skills_reports_matched_and_unmatched(example_bank, sample_jd_text):
    jd = _mk_jd(sample_jd_text)
    result = match_skills(example_bank, jd)

    assert result.job_id == jd.job_id
    assert result.total_requirements == len(jd.requirements)
    assert result.matched, "expected at least one matched requirement"

    matched_texts_lower = {m.requirement_text.lower() for m in result.matched}
    # Python/FastAPI/Docker/MCP are all directly present in the bank.
    assert "python" in matched_texts_lower or "fastapi" in matched_texts_lower

    for row in result.matched:
        # Every matched requirement must point at real evidence.
        assert row.bullet_ids or row.skill_names
        assert row.evidence_ids


def test_match_skills_reports_gaps_for_unsupported_keywords(example_bank):
    text = "Must have: kubernetes, terraform, and dbt. Also snowflake."
    jd = _mk_jd(text)
    result = match_skills(example_bank, jd)

    unmatched_lower = {u.requirement_text.lower() for u in result.unmatched}
    assert "kubernetes" in unmatched_lower
    assert "terraform" in unmatched_lower
    for row in result.unmatched:
        assert not row.bullet_ids
        assert not row.skill_names
        assert not row.evidence_ids


def test_match_skills_coverage_ratio_matches_counts(example_bank, sample_jd_text):
    jd = _mk_jd(sample_jd_text)
    result = match_skills(example_bank, jd)
    total = result.total_requirements or 1
    assert result.coverage_ratio == round(len(result.matched) / total, 3)


def test_match_skills_does_not_create_a_draft(example_bank, sample_jd_text):
    """match_skills is pure analysis: it must not mutate the bank or JD."""
    jd = _mk_jd(sample_jd_text)
    bank_snapshot = example_bank.model_dump()
    jd_snapshot = jd.model_dump()

    match_skills(example_bank, jd)

    assert example_bank.model_dump() == bank_snapshot
    assert jd.model_dump() == jd_snapshot
