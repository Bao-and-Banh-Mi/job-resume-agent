from resume_agent.evidence_linker import classify_bullet
from resume_agent.models import EvidenceItem


def _ev(body: str, eid: str = "ev-1") -> EvidenceItem:
    return EvidenceItem(evidence_id=eid, kind="note", title="", body=body)


def test_verbatim_bullet_is_verbatim():
    text = "Built multi-agent workflows on WatsonX Orchestrate serving 50 hiring managers."
    c = classify_bullet(
        rewritten_text=text,
        original_bullet_text=text,
        cited_evidence=[_ev(text)],
    )
    assert c.label == "verbatim"
    assert c.new_numeric_tokens == []
    assert c.new_named_entities == []


def test_new_numeric_token_flags_unsupported():
    ev = _ev("Built multi-agent workflows on WatsonX Orchestrate.")
    c = classify_bullet(
        rewritten_text="Built multi-agent workflows on WatsonX Orchestrate serving 999 hiring managers.",
        original_bullet_text="Built multi-agent workflows on WatsonX Orchestrate.",
        cited_evidence=[ev],
    )
    assert c.label == "unsupported"
    assert "999" in c.new_numeric_tokens


def test_new_named_entity_flags_unsupported():
    ev = _ev("Built a multi-agent workflow on WatsonX Orchestrate.")
    c = classify_bullet(
        rewritten_text="Built a multi-agent workflow on WatsonX Orchestrate for Netflix.",
        original_bullet_text="Built a multi-agent workflow on WatsonX Orchestrate.",
        cited_evidence=[ev],
    )
    assert c.label == "unsupported"
    assert "Netflix" in c.new_named_entities


def test_paraphrase_within_evidence_stays_supported():
    ev = _ev(
        "Built multi-agent recruiter automation on WatsonX Orchestrate integrated "
        "with Slack and Microsoft Graph."
    )
    c = classify_bullet(
        rewritten_text="Built multi-agent automation on WatsonX Orchestrate with Slack integration.",
        original_bullet_text="Built multi-agent recruiter automation on WatsonX Orchestrate.",
        cited_evidence=[ev],
    )
    assert c.label in {"verbatim", "paraphrased"}
    assert c.new_numeric_tokens == []
    assert c.new_named_entities == []


def test_sentence_position_shift_is_not_a_fabricated_entity():
    """Regression: reordering a bullet must not read as inventing a noun.

    The entity heuristic keys off capitalisation, so "Built X for Y" ->
    "For Y, built X" previously flagged "Built" as a brand-new proper noun
    and blocked an edit that invented nothing. This is the single most
    common shape of agent rephrasing, so it must pass.
    """
    original = "Built a RAG pipeline for the Slack bot."
    ev = EvidenceItem(evidence_id="ev-1", body=original)
    c = classify_bullet(
        rewritten_text="For the Slack bot, built a RAG pipeline.",
        original_bullet_text=original,
        cited_evidence=[ev],
    )
    assert c.new_named_entities == []
    assert c.label in {"verbatim", "paraphrased"}


def test_genuinely_new_proper_noun_is_still_caught():
    original = "Built a RAG pipeline for the Slack bot."
    ev = EvidenceItem(evidence_id="ev-1", body=original)
    c = classify_bullet(
        rewritten_text="Built a RAG pipeline for the Datadog integration.",
        original_bullet_text=original,
        cited_evidence=[ev],
    )
    assert "Datadog" in c.new_named_entities
    assert c.label == "unsupported"
