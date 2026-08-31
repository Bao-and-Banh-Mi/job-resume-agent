"""The fit validator is the anti-optimism gate.

These tests encode the central claim of the redesign: a model's coverage
assertion is only as good as the citations behind it.
"""

from __future__ import annotations

from resume_agent.fit import analyze_fit
from resume_agent.models import AssessedRequirement, ExperienceBank


def _first_bullet_id(bank: ExperienceBank) -> str:
    for entry in bank.all_entries():
        if entry.bullets:
            return entry.bullets[0].bullet_id
    raise AssertionError("bank fixture has no bullets")


def test_covered_with_real_citation_survives(example_bank):
    bid = _first_bullet_id(example_bank)
    report = analyze_fit(
        example_bank,
        "job-1",
        [
            AssessedRequirement(
                text="Python", verdict="covered", supporting_bullet_ids=[bid]
            )
        ],
    )
    assert len(report.covered) == 1
    assert report.coverage_ratio == 1.0
    assert report.corrections == []


def test_covered_with_no_citation_is_downgraded(example_bank):
    report = analyze_fit(
        example_bank,
        "job-1",
        [AssessedRequirement(text="Kubernetes", verdict="covered")],
    )
    assert report.covered == []
    assert len(report.gaps) == 1
    assert report.coverage_ratio == 0.0
    assert any("downgraded" in c for c in report.corrections)


def test_hallucinated_bullet_id_is_stripped_and_downgraded(example_bank):
    report = analyze_fit(
        example_bank,
        "job-1",
        [
            AssessedRequirement(
                text="Rust",
                verdict="covered",
                supporting_bullet_ids=["bul-does-not-exist"],
            )
        ],
    )
    assert report.covered == []
    assert report.gaps[0].supporting_bullet_ids == []
    assert any("does not exist" in c for c in report.corrections)


def test_hallucinated_skill_is_stripped(example_bank):
    report = analyze_fit(
        example_bank,
        "job-1",
        [
            AssessedRequirement(
                text="Haskell", verdict="covered", supporting_skills=["Haskell"]
            )
        ],
    )
    assert report.covered == []
    assert any("not in the bank" in c for c in report.corrections)


def test_real_skill_citation_is_normalised_to_bank_spelling(example_bank):
    skill = example_bank.skills[0].skills[0].name
    report = analyze_fit(
        example_bank,
        "job-1",
        [
            AssessedRequirement(
                text=skill, verdict="covered", supporting_skills=[skill.lower()]
            )
        ],
    )
    assert report.covered[0].supporting_skills == [skill]
    assert report.corrections == []


def test_partial_counts_half(example_bank):
    bid = _first_bullet_id(example_bank)
    report = analyze_fit(
        example_bank,
        "job-1",
        [
            AssessedRequirement(
                text="A", verdict="covered", supporting_bullet_ids=[bid]
            ),
            AssessedRequirement(
                text="B", verdict="partial", supporting_bullet_ids=[bid]
            ),
        ],
    )
    assert report.coverage_ratio == 0.75


def test_must_have_gap_dominates_weighted_coverage(example_bank):
    bid = _first_bullet_id(example_bank)
    report = analyze_fit(
        example_bank,
        "job-1",
        [
            AssessedRequirement(
                text="nice thing",
                category="nice_to_have",
                verdict="covered",
                supporting_bullet_ids=[bid],
            ),
            AssessedRequirement(
                text="Swift", category="must_have", verdict="gap"
            ),
        ],
    )
    # Flat ratio says 50%; weighted says worse because the miss is a must-have.
    assert report.coverage_ratio == 0.5
    assert report.weighted_coverage < report.coverage_ratio
    assert report.must_have_gaps == ["Swift"]
    assert "must-have" in report.recommendation


def test_no_requirements_is_reported_not_divided_by_zero(example_bank):
    report = analyze_fit(example_bank, "job-1", [])
    assert report.coverage_ratio == 0.0
    assert report.weighted_coverage == 0.0
    assert "re-read" in report.recommendation
