"""Prose gate: reject slop and enforce edit discipline on agent rewrites."""

from __future__ import annotations

from resume_agent.prose import check_prose, edit_fraction

ORIGINAL = (
    "Built multi-agent workflows on WatsonX Orchestrate to automate "
    "recruiter operations for 50+ Hiring Managers."
)


def test_verbatim_is_a_zero_edit():
    frac, changed = edit_fraction(ORIGINAL, ORIGINAL)
    assert frac == 0.0
    assert changed == 0


def test_small_vocabulary_swap_is_allowed():
    """The intended use: echo the posting's words, keep the candidate's voice."""
    tailored = ORIGINAL.replace("workflows", "backend services")
    verdict = check_prose(original=ORIGINAL, rewritten=tailored)
    assert verdict.ok, verdict.reason
    assert 0 < verdict.edit_fraction < 0.35


def test_inflated_verb_is_rejected():
    slop = ORIGINAL.replace("Built", "Spearheaded")
    verdict = check_prose(original=ORIGINAL, rewritten=slop)
    assert not verdict.ok
    assert "spearheaded" in verdict.reason.lower()


def test_empty_adjectives_are_rejected():
    slop = ORIGINAL.replace(
        "multi-agent workflows", "robust, scalable multi-agent workflows"
    )
    verdict = check_prose(original=ORIGINAL, rewritten=slop)
    assert not verdict.ok
    assert "robust" in verdict.reason or "scalable" in verdict.reason


def test_resume_cliche_is_rejected():
    slop = "Passionate engineer who built multi-agent workflows on WatsonX."
    verdict = check_prose(original=ORIGINAL, rewritten=slop)
    assert not verdict.ok
    assert "passionate" in verdict.reason.lower()


def test_first_person_is_rejected():
    slop = "I built multi-agent workflows on WatsonX Orchestrate."
    verdict = check_prose(original=ORIGINAL, rewritten=slop)
    assert not verdict.ok
    assert "first-person" in verdict.reason


def test_weak_opener_is_rejected():
    slop = "Responsible for multi-agent workflows on WatsonX Orchestrate."
    verdict = check_prose(original=ORIGINAL, rewritten=slop)
    assert not verdict.ok
    assert "weak opener" in verdict.reason


def test_wholesale_restatement_is_rejected():
    """Facts preserved, voice destroyed. The linker passes this; we must not."""
    restated = (
        "Designed and delivered an agentic automation platform on WatsonX "
        "Orchestrate that streamlined talent acquisition processes serving "
        "over fifty hiring stakeholders."
    )
    verdict = check_prose(original=ORIGINAL, rewritten=restated)
    assert not verdict.ok
    assert "changes" in verdict.reason and "%" in verdict.reason


def test_padding_is_rejected():
    padded = ORIGINAL.rstrip(".") + (
        ", collaborating across teams to deliver measurable business outcomes "
        "and drive adoption throughout the organization."
    )
    verdict = check_prose(original=ORIGINAL, rewritten=padded)
    assert not verdict.ok


def test_slop_already_in_the_original_is_not_the_agents_fault():
    """We police what the agent introduces, not the candidate's own voice."""
    original = "Built a robust, scalable pipeline for 10+ services."
    tailored = original.replace("pipeline", "data pipeline")
    verdict = check_prose(original=original, rewritten=tailored)
    assert verdict.ok, verdict.reason


def test_lowercase_start_is_rejected():
    verdict = check_prose(
        original=ORIGINAL, rewritten="built multi-agent workflows on WatsonX."
    )
    assert not verdict.ok
    assert "capital" in verdict.reason
