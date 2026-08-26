import datetime as _dt

from resume_agent.models import JobDescription
from resume_agent.tailor import analyze_jd, tailor


def _mk_jd(text: str) -> JobDescription:
    return JobDescription(
        job_id="job-test",
        captured_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).isoformat(),
        raw_text=text,
        requirements=analyze_jd(text),
    )


def test_tailor_picks_relevant_bullets(example_bank, sample_jd_text):
    draft = tailor(example_bank, _mk_jd(sample_jd_text))

    # Draft always has at least the four bank-populated sections + skills.
    kinds = [s.kind for s in draft.sections]
    assert "experience" in kinds
    assert "skills" in kinds

    experience = next(s for s in draft.sections if s.kind == "experience")
    top_titles = [(e.organization, e.title) for e in experience.entries]
    # The IBM experience is heavy on MCP/Slack/Microsoft Graph, so it should be present.
    assert any("IBM" in org for org, _ in top_titles)


def test_tailor_bullets_are_verbatim_from_bank(example_bank, sample_jd_text):
    draft = tailor(example_bank, _mk_jd(sample_jd_text))
    for section in draft.sections:
        for entry in section.entries:
            for b in entry.bullets:
                # POC pipeline picks bullets whole from the bank; no rephrasing.
                assert b.rewritten_text == b.original_text
                assert b.classification.label in {"verbatim", "paraphrased", "inferred"}


def test_tailor_is_deterministic(example_bank, sample_jd_text):
    d1 = tailor(example_bank, _mk_jd(sample_jd_text))
    d2 = tailor(example_bank, _mk_jd(sample_jd_text))
    # created_at and draft_id encode time-independent inputs; assert core shape:
    assert d1.draft_id == d2.draft_id
    assert [s.section_id for s in d1.sections] == [s.section_id for s in d2.sections]


def test_tailor_reports_gaps_for_unsupported_keywords(example_bank):
    text = "Must have: kubernetes, terraform, and dbt. Also snowflake."
    draft = tailor(example_bank, _mk_jd(text))
    unmatched_lower = {u.lower() for u in draft.keyword_coverage.unmatched}
    assert "kubernetes" in unmatched_lower
    assert "terraform" in unmatched_lower
