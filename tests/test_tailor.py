"""Selection assembly: reference integrity, rephrase gating, structure."""

from __future__ import annotations

import datetime as _dt

import pytest

from resume_agent.models import JobDescription, ResumeSelection
from resume_agent.tailor import SelectionError, tailor_from_selection


def _jd() -> JobDescription:
    return JobDescription(
        job_id="job-1",
        captured_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        raw_text="We need Python and multi-agent systems.",
    )


def _sel(d: dict) -> ResumeSelection:
    return ResumeSelection.model_validate(d)


def test_selection_is_honoured_verbatim(example_bank, full_selection):
    draft = tailor_from_selection(example_bank, _jd(), _sel(full_selection))
    texts = {
        b.rewritten_text
        for s in draft.sections
        for e in s.entries
        for b in e.bullets
    }
    bank_texts = {
        b.text for e in example_bank.all_entries() for b in e.bullets
    }
    assert texts <= bank_texts
    assert all(
        b.classification.label == "verbatim"
        for s in draft.sections
        for e in s.entries
        for b in e.bullets
    )


def test_unknown_entry_id_is_rejected(example_bank):
    with pytest.raises(SelectionError, match="not in the bank"):
        tailor_from_selection(
            example_bank,
            _jd(),
            _sel(
                {
                    "sections": [
                        {
                            "kind": "experience",
                            "entries": [{"entry_id": "exp-nope", "bullets": []}],
                        }
                    ]
                }
            ),
        )


def test_unknown_bullet_id_is_rejected(example_bank):
    entry = example_bank.experiences[0]
    with pytest.raises(SelectionError, match="bullet_id"):
        tailor_from_selection(
            example_bank,
            _jd(),
            _sel(
                {
                    "sections": [
                        {
                            "kind": "experience",
                            "entries": [
                                {
                                    "entry_id": entry.entry_id,
                                    "bullets": [{"bullet_id": "bul-nope"}],
                                }
                            ],
                        }
                    ]
                }
            ),
        )


def test_bullet_must_belong_to_its_claimed_entry(example_bank):
    if len(example_bank.experiences) < 2:
        pytest.skip("needs two experience entries")
    a, b = example_bank.experiences[0], example_bank.experiences[1]
    with pytest.raises(SelectionError, match="belongs to entry"):
        tailor_from_selection(
            example_bank,
            _jd(),
            _sel(
                {
                    "sections": [
                        {
                            "kind": "experience",
                            "entries": [
                                {
                                    "entry_id": a.entry_id,
                                    "bullets": [
                                        {"bullet_id": b.bullets[0].bullet_id}
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ),
        )


def test_unknown_skill_is_rejected(example_bank, full_selection):
    sel = dict(full_selection)
    sel["skills"] = [{"group": "Programming", "skills": ["Malbolge"]}]
    with pytest.raises(SelectionError, match="not in the bank"):
        tailor_from_selection(example_bank, _jd(), _sel(sel))


# --- the part that makes "let the LLM polish it" safe ----------------------


def _experience_bullet(draft):
    """First bullet of the Experience section, addressed by kind.

    Section order is Education-first, so positional indexing is wrong.
    """
    section = next(s for s in draft.sections if s.kind == "experience")
    return section.entries[0].bullets[0]


def _one_bullet_selection(example_bank, rewritten: str) -> dict:
    entry = example_bank.experiences[0]
    return {
        "sections": [
            {
                "kind": "experience",
                "entries": [
                    {
                        "entry_id": entry.entry_id,
                        "bullets": [
                            {
                                "bullet_id": entry.bullets[0].bullet_id,
                                "rewritten_text": rewritten,
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_rephrase_inventing_a_number_is_unsupported_and_blocks_export(example_bank):
    draft = tailor_from_selection(
        example_bank,
        _jd(),
        _sel(
            _one_bullet_selection(
                example_bank, "Improved throughput by 400% across 12 services."
            )
        ),
    )
    bullet = _experience_bullet(draft)
    assert bullet.classification.label == "unsupported"
    assert bullet.approved is False
    assert bullet.classification.new_numeric_tokens


def test_rephrase_inventing_a_company_is_unsupported(example_bank):
    draft = tailor_from_selection(
        example_bank,
        _jd(),
        _sel(
            _one_bullet_selection(
                example_bank, "Shipped the Nvidia Triton integration for Datadog."
            )
        ),
    )
    bullet = _experience_bullet(draft)
    assert bullet.classification.label == "unsupported"
    assert bullet.classification.new_named_entities


def test_faithful_rephrase_is_allowed(example_bank):
    original = example_bank.experiences[0].bullets[0].text
    # Reorder the original's own words: no new facts, so this must pass.
    words = original.rstrip(".").split()
    reworded = " ".join(words[2:] + words[:2]) + "."
    draft = tailor_from_selection(
        example_bank, _jd(), _sel(_one_bullet_selection(example_bank, reworded))
    )
    bullet = _experience_bullet(draft)
    assert bullet.classification.label in ("verbatim", "paraphrased")
    assert bullet.approved is True
    assert bullet.edited_by_user is True


def test_inferred_needs_accept_inferred(example_bank):
    sel = _one_bullet_selection(example_bank, "Did some engineering work.")
    draft = tailor_from_selection(example_bank, _jd(), _sel(sel))
    bullet = _experience_bullet(draft)
    if bullet.classification.label != "inferred":
        pytest.skip("bank bullet did not produce an 'inferred' classification")
    assert bullet.approved is False

    sel["accept_inferred"] = True
    draft2 = tailor_from_selection(example_bank, _jd(), _sel(sel))
    assert _experience_bullet(draft2).approved is True


def test_do_not_paraphrase_is_enforced(example_bank):
    entry = example_bank.experiences[0]
    bullet = entry.bullets[0]
    bullet.do_not_paraphrase = True
    try:
        with pytest.raises(SelectionError, match="do_not_paraphrase"):
            tailor_from_selection(
                example_bank,
                _jd(),
                _sel(_one_bullet_selection(example_bank, "Anything else at all.")),
            )
    finally:
        bullet.do_not_paraphrase = False


# --- structural guarantees (the old pipeline's real-world failure) ---------


def test_education_is_included_even_when_not_selected(example_bank):
    draft = tailor_from_selection(
        example_bank,
        _jd(),
        _sel({"sections": [], "rationale": "agent forgot education"}),
    )
    kinds = {s.kind for s in draft.sections}
    assert "education" in kinds


def test_skills_section_falls_back_to_bank_when_agent_selects_none(example_bank):
    draft = tailor_from_selection(example_bank, _jd(), _sel({"sections": []}))
    skills = [s for s in draft.sections if s.kind == "skills"]
    assert skills and skills[0].skill_groups, "resume must never ship with no skills"


def test_agent_section_order_is_preserved(example_bank, full_selection):
    draft = tailor_from_selection(example_bank, _jd(), _sel(full_selection))
    entry_ids = [
        e.source_entry_id
        for s in draft.sections
        if s.kind == "experience"
        for e in s.entries
    ]
    assert entry_ids == [e.entry_id for e in example_bank.experiences]
