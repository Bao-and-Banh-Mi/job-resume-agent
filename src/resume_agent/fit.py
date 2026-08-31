"""Validate an agent's fit assessment against the loaded bank.

The calling LLM reads the posting and the bank catalog and reports, per
requirement, whether the bank supports it. This module is the adversarial
check on that report. It exists because a model asked "does your evidence
cover this?" is systematically optimistic, and an optimistic coverage
number is worse than no number at all -- it produces resumes that claim
skills the candidate cannot defend in an interview.

Two rules do the work:

1. **Citations must resolve.** A ``covered``/``partial`` verdict citing a
   bullet_id or skill that is not in the bank is downgraded to ``gap`` and
   the fabricated id is reported in ``corrections``.
2. **Verdicts must be earned.** ``covered`` with zero resolving citations is
   downgraded, full stop. The model cannot assert coverage into existence.

Coverage is then reported two ways: a flat ratio, and a ``weighted_coverage``
that counts must-haves double, because missing a must-have matters more than
missing a nice-to-have and a flat ratio hides that.
"""

from __future__ import annotations

from .catalog import bullet_index, entry_index, skill_index
from .models import AssessedRequirement, ExperienceBank, FitReport

# A must-have counts this many times a nice-to-have in weighted coverage.
_MUST_HAVE_WEIGHT = 2.0
_DEFAULT_WEIGHT = 1.0


def _weight(req: AssessedRequirement) -> float:
    return _MUST_HAVE_WEIGHT if req.category == "must_have" else _DEFAULT_WEIGHT


def _score(req: AssessedRequirement) -> float:
    if req.verdict == "covered":
        return 1.0
    if req.verdict == "partial":
        return 0.5
    return 0.0


def analyze_fit(
    bank: ExperienceBank,
    job_id: str,
    requirements: list[AssessedRequirement],
) -> FitReport:
    """Validate ``requirements`` against ``bank`` and produce a FitReport."""
    bullets = bullet_index(bank)
    skills = skill_index(bank)
    entries = entry_index(bank)

    corrections: list[str] = []
    validated: list[AssessedRequirement] = []

    for req in requirements:
        checked = req.model_copy(deep=True)

        real_bullets = []
        for bid in checked.supporting_bullet_ids:
            if bid in bullets:
                real_bullets.append(bid)
            elif bid in entries:
                # Degree/coursework requirements have no bullet to cite --
                # a live agent hit this citing "CS degree" and had to point
                # at unrelated experience bullets instead. An entry_id is a
                # legitimate citation for entry-level facts, so accept it.
                real_bullets.append(bid)
            else:
                corrections.append(
                    f"requirement {checked.text!r}: cited bullet_id {bid!r} "
                    "does not exist in the bank; citation dropped"
                )

        real_skills = []
        for name in checked.supporting_skills:
            if name.lower() in skills:
                # Normalise to the bank's own spelling.
                real_skills.append(skills[name.lower()].name)
            else:
                corrections.append(
                    f"requirement {checked.text!r}: cited skill {name!r} is "
                    "not in the bank; citation dropped"
                )

        checked.supporting_bullet_ids = real_bullets
        checked.supporting_skills = real_skills

        # Rule 2: a verdict with no surviving evidence is not a verdict.
        if checked.verdict in ("covered", "partial") and not (
            real_bullets or real_skills
        ):
            corrections.append(
                f"requirement {checked.text!r}: verdict {checked.verdict!r} "
                "downgraded to 'gap' -- no bank evidence was cited"
            )
            checked.verdict = "gap"

        validated.append(checked)

    covered = [r for r in validated if r.verdict == "covered"]
    partial = [r for r in validated if r.verdict == "partial"]
    gaps = [r for r in validated if r.verdict == "gap"]

    total = len(validated)
    flat = (len(covered) + 0.5 * len(partial)) / total if total else 0.0

    weight_sum = sum(_weight(r) for r in validated)
    weighted = (
        sum(_weight(r) * _score(r) for r in validated) / weight_sum
        if weight_sum
        else 0.0
    )

    must_have_gaps = [r.text for r in gaps if r.category == "must_have"]

    return FitReport(
        job_id=job_id,
        total_requirements=total,
        covered=covered,
        partial=partial,
        gaps=gaps,
        coverage_ratio=round(flat, 3),
        weighted_coverage=round(weighted, 3),
        must_have_gaps=must_have_gaps,
        corrections=corrections,
        recommendation=_recommend(weighted, must_have_gaps, total),
    )


def _recommend(weighted: float, must_have_gaps: list[str], total: int) -> str:
    if total == 0:
        return "No requirements were assessed; re-read the posting."
    if must_have_gaps:
        listed = ", ".join(must_have_gaps[:3])
        more = f" (+{len(must_have_gaps) - 3} more)" if len(must_have_gaps) > 3 else ""
        return (
            f"Missing {len(must_have_gaps)} must-have requirement(s): {listed}{more}. "
            "Tailoring will still produce an honest resume, but do not claim these."
        )
    if weighted >= 0.7:
        return "Strong fit. Proceed to tailor_resume."
    if weighted >= 0.4:
        return (
            "Moderate fit. Tailor, but lead with the strongest matched entries "
            "and expect to address gaps in a cover letter."
        )
    return (
        "Weak fit on the stated requirements. The resume will be honest but thin; "
        "consider whether this posting is worth an application."
    )
