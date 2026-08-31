"""Prose quality gate for agent-rewritten bullets.

The evidence linker answers "is this bullet *true*?". This module answers
"is this bullet *well written*, and is it a tailoring edit rather than a
rewrite?". Both must pass before a rewritten bullet can be exported.

Why this exists
---------------
Asking a language model to "tailor" a resume bullet reliably produces two
failure modes that are not fabrication, so the evidence linker waves them
through:

1. **Slop.** The bullet keeps every fact but acquires "leveraged",
   "spearheaded", "seamlessly", "cutting-edge", "robust". These are the
   tells recruiters use to spot generated text, and they make a real
   accomplishment read as filler.
2. **Rewriting instead of tailoring.** The model paraphrases the whole
   bullet into its own register. Even when the facts survive, the candidate's
   voice does not, and the result is uniform LLM cadence across every entry.

The user's requirement is "delicately placed text": a tailored bullet should
differ from the original by a *few* deliberate word choices that echo the
posting's vocabulary -- not by a full restatement. So we bound the edit.

The checks are deliberately mechanical and explainable. Every rejection
names the offending token so the agent can fix it in one retry rather than
guessing.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

# Words that signal generated prose. Split by reason so error messages can
# explain *why* a word is rejected rather than just listing it.
_INFLATED_VERBS = frozenset(
    {
        "spearheaded", "leveraged", "utilized", "utilised", "orchestrated",
        "championed", "pioneered", "helmed", "shepherded", "drove",
        "facilitated", "actualized", "operationalized", "evangelized",
        "architected", "ideated", "conceptualized",
    }
)

_EMPTY_ADJECTIVES = frozenset(
    {
        "cutting-edge", "state-of-the-art", "best-in-class", "world-class",
        "innovative", "groundbreaking", "revolutionary", "transformative",
        "robust", "scalable", "seamless", "seamlessly", "powerful",
        "comprehensive", "holistic", "synergistic", "bleeding-edge",
        "next-generation", "industry-leading", "mission-critical",
        "highly", "deeply", "extremely", "incredibly", "significantly",
    }
)

_RESUME_CLICHES = frozenset(
    {
        "passionate", "motivated", "results-driven", "detail-oriented",
        "team-player", "self-starter", "go-getter", "hardworking",
        "dynamic", "proven", "track-record", "wheelhouse",
    }
)

# First-person pronouns: resume bullets are written in implied first person.
_FIRST_PERSON = frozenset({"i", "my", "me", "myself", "we", "our", "us"})

# Weak openers. A resume bullet should lead with a concrete action verb.
_WEAK_OPENERS = frozenset(
    {
        "responsible", "worked", "helped", "assisted", "participated",
        "involved", "tasked", "contributed", "supported", "handled",
        "various", "successfully",
    }
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]*")

# A tailoring edit may change at most this fraction of the original's words.
# 0.35 permits swapping several terms for the posting's vocabulary while
# rejecting a wholesale restatement.
_MAX_EDIT_FRACTION = 0.35

# A tailored bullet must not balloon. Recruiters skim; a bullet that grows
# 40% longer is padding, not tailoring.
_MAX_LENGTH_GROWTH = 1.25


@dataclass(frozen=True)
class ProseVerdict:
    ok: bool
    edit_fraction: float = 0.0
    words_changed: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return "; ".join(self.problems)


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def edit_fraction(original: str, rewritten: str) -> tuple[float, int]:
    """Fraction of the original's words touched by ``rewritten``.

    Uses a word-level diff rather than character distance so that swapping
    one term for a synonym counts as one change, not eight.
    """
    a, b = [w.lower() for w in _words(original)], [w.lower() for w in _words(rewritten)]
    if not a:
        return (0.0, 0) if not b else (1.0, len(b))

    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    changed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            changed += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            changed += i2 - i1
        elif tag == "insert":
            changed += j2 - j1
    return round(changed / len(a), 3), changed


def check_prose(
    *, original: str, rewritten: str, strict_openers: bool = True
) -> ProseVerdict:
    """Check a rewritten bullet for slop and for edit discipline."""
    problems: list[str] = []
    frac, changed = edit_fraction(original, rewritten)

    lowered = [w.lower() for w in _words(rewritten)]
    original_lowered = {w.lower() for w in _words(original)}

    # Only flag slop the *agent introduced*. If the bank's own bullet says
    # "robust", that is the candidate's voice and not ours to police.
    def introduced(vocabulary: frozenset[str]) -> list[str]:
        return sorted(
            {w for w in lowered if w in vocabulary and w not in original_lowered}
        )

    inflated = introduced(_INFLATED_VERBS)
    if inflated:
        problems.append(
            f"inflated verb(s) not in the original: {', '.join(inflated)}. "
            "Use the plain verb the candidate actually used."
        )

    empty = introduced(_EMPTY_ADJECTIVES)
    if empty:
        problems.append(
            f"empty intensifier/adjective(s): {', '.join(empty)}. "
            "Cut them; the metric carries the weight."
        )

    cliche = introduced(_RESUME_CLICHES)
    if cliche:
        problems.append(f"resume cliche(s): {', '.join(cliche)}")

    person = sorted({w for w in lowered if w in _FIRST_PERSON})
    if person:
        problems.append(
            f"first-person pronoun(s): {', '.join(person)}. "
            "Resume bullets use implied first person."
        )

    if strict_openers and lowered:
        opener = lowered[0]
        if opener in _WEAK_OPENERS and opener not in original_lowered:
            problems.append(
                f"weak opener {opener!r}; lead with a concrete action verb"
            )

    if frac > _MAX_EDIT_FRACTION:
        problems.append(
            f"rewrite changes {frac:.0%} of the original's words "
            f"(limit {_MAX_EDIT_FRACTION:.0%}). Tailoring means swapping a few "
            "terms to match the posting's vocabulary, not restating the bullet. "
            "Keep the candidate's own phrasing and structure."
        )

    if original and len(rewritten) > len(original) * _MAX_LENGTH_GROWTH:
        problems.append(
            f"bullet grew from {len(original)} to {len(rewritten)} chars "
            f"(limit {_MAX_LENGTH_GROWTH:.0%}); tailoring should not pad"
        )

    if rewritten.strip() and not rewritten.strip()[0].isupper():
        problems.append("bullet should start with a capital letter")

    return ProseVerdict(
        ok=not problems,
        edit_fraction=frac,
        words_changed=changed,
        problems=problems,
    )
