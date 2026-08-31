"""Deterministic evidence-vs-bullet classifier.

Implements the algorithm sketched in ``docs/technical-architecture.md`` (S5).
The linker is the single gate on export: for a bullet with new numeric
tokens or named entities absent from its cited evidence, we refuse to
classify it any better than ``unsupported``.

The classifier is intentionally simple and testable:

- ``verbatim``    -> >= 90% content-token overlap with evidence, no new numbers.
- ``paraphrased`` -> >= 70% overlap, no new numbers, no new named entities.
- ``inferred``    -> < 70% overlap, but no new numbers/entities.
- ``unsupported`` -> any new numeric token or named entity.

"New" is defined against the union of all cited evidence bodies plus the
original bank bullet text (which is itself a first-class evidence anchor by
the data model's invariant), and is compared case-insensitively so that
moving a word away from the start of a sentence does not read as a
fabricated proper noun.

This classifier is what makes agent rephrasing safe. The calling LLM is
free to re-frame a bullet for a posting's vocabulary; if the result asserts
a number or a proper noun the evidence does not contain, it is labelled
``unsupported`` and the export gate refuses it.
"""

from __future__ import annotations

import re

from .keywords import content_token_set
from .models import BulletClassification, EvidenceItem

_NUMBER_RE = re.compile(r"\b\d[\d,\.]*[+]?%?\b|\b\d+[+]?\b")
# Named-entity heuristic: any capitalized token that is not the first token of
# a sentence and not an all-caps stopword. This mirrors the docs' spirit
# without shipping a full NER model.
_ENTITY_TOKEN_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*\b")
_SENTENCE_START_RE = re.compile(r"(^|[.!?]\s+)")


def _numeric_tokens(text: str) -> set[str]:
    return {m.group(0) for m in _NUMBER_RE.finditer(text)}


def _named_entities(text: str) -> set[str]:
    """Approximate named entities: capitalized tokens/acronyms."""
    # Mask sentence starts by uppercasing all first-letters uniformly is hard.
    # Instead: collect all capitalized/acronym tokens, then remove those that
    # only appear at a sentence start position.
    candidates = list(_ENTITY_TOKEN_RE.finditer(text))
    starts: set[int] = set()
    for m in _SENTENCE_START_RE.finditer(text):
        starts.add(m.end())
    out: set[str] = set()
    for m in candidates:
        # If the token starts a sentence and is not all-caps, skip it.
        if m.start() in starts and not m.group(0).isupper():
            continue
        # Skip single ambiguous words like "The", "A".
        if len(m.group(0)) < 2:
            continue
        out.add(m.group(0))
    return out


def _combined_evidence_text(
    original_bullet_text: str, evidence: list[EvidenceItem]
) -> str:
    return "\n".join([original_bullet_text, *(e.body for e in evidence)])


def _new_entities(bullet_text: str, evidence_text: str) -> list[str]:
    """Entities in ``bullet_text`` that do not occur in ``evidence_text``.

    Comparison is case-insensitive on purpose. The entity heuristic keys off
    capitalisation, so a word's *casing* changes with its sentence position:
    rephrasing "Built X for Y" into "For Y, built X" makes "Built" look like
    a brand-new proper noun and would block an edit that invented nothing.
    Matching case-insensitively against the evidence removes that false
    positive while still catching genuinely new names -- "Datadog" does not
    appear in the evidence in any casing.
    """
    evidence_lower = {e.lower() for e in _named_entities(evidence_text)}
    # Also allow any word present in the evidence at all, regardless of the
    # entity heuristic's opinion about it (handles casing shifts on ordinary
    # words that happen to start a sentence).
    evidence_words = set(content_token_set(evidence_text))
    return sorted(
        e
        for e in _named_entities(bullet_text)
        if e.lower() not in evidence_lower and e.lower() not in evidence_words
    )


def classify_bullet(
    *,
    rewritten_text: str,
    original_bullet_text: str,
    cited_evidence: list[EvidenceItem],
) -> BulletClassification:
    """Classify a candidate bullet against its cited evidence."""
    combined = _combined_evidence_text(original_bullet_text, cited_evidence)

    bullet_tokens = content_token_set(rewritten_text)
    evidence_tokens = content_token_set(combined)

    bullet_numbers = _numeric_tokens(rewritten_text)
    evidence_numbers = _numeric_tokens(combined)
    new_numbers = sorted(bullet_numbers - evidence_numbers)

    new_entities = _new_entities(rewritten_text, combined)

    if bullet_tokens:
        overlap_ratio = (
            len(bullet_tokens & evidence_tokens) / len(bullet_tokens)
        )
    else:
        overlap_ratio = 1.0

    if new_numbers or new_entities:
        reason_parts: list[str] = []
        if new_numbers:
            reason_parts.append(
                f"introduces numeric claims not in evidence: {', '.join(new_numbers)}"
            )
        if new_entities:
            reason_parts.append(
                f"introduces named entities not in evidence: {', '.join(new_entities)}"
            )
        return BulletClassification(
            label="unsupported",
            token_overlap=round(overlap_ratio, 3),
            new_numeric_tokens=new_numbers,
            new_named_entities=new_entities,
            reason="; ".join(reason_parts),
        )

    if overlap_ratio >= 0.90:
        label = "verbatim"
        reason = "high overlap with cited evidence, no new numerics or entities"
    elif overlap_ratio >= 0.70:
        label = "paraphrased"
        reason = "moderate overlap with cited evidence, no new numerics or entities"
    else:
        label = "inferred"
        reason = (
            "low token overlap with cited evidence; wording is inferred and "
            "must be approved before export"
        )

    return BulletClassification(
        label=label,
        token_overlap=round(overlap_ratio, 3),
        new_numeric_tokens=[],
        new_named_entities=[],
        reason=reason,
    )
