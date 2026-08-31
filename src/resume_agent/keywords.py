"""Tokenization used by the evidence linker.

This module used to host a heuristic "extract the requirements from a job
description" keyword analyzer. It was removed: that job belongs to the
language model calling this server, which can tell a required skill from a
compensation footnote and can infer "distributed systems" from "Redis,
Kafka, low-latency" -- neither of which a token matcher can do. The old
extractor produced denominators full of ``barista-made`` and ``well-being``,
which made honest coverage numbers impossible.

What remains is the deterministic tokenizer the evidence linker uses to
measure overlap between a rephrased bullet and its evidence. That comparison
must stay mechanical and stable, so it lives here rather than being
delegated to a model.
"""

from __future__ import annotations

import re

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "at", "by", "from", "as", "is", "are", "be", "was", "were", "been",
        "will", "would", "should", "could", "may", "might", "can", "must",
        "we", "you", "our", "your", "their", "this", "that", "these", "those",
        "have", "has", "had", "do", "does", "did", "not", "no", "yes",
        "who", "what", "when", "where", "why", "how", "which", "than", "then",
        "if", "so", "but", "because", "while", "about", "into", "over", "under",
        "such", "some", "any", "all", "each", "every", "other", "same",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#\-]*")


def tokenize(text: str) -> list[str]:
    """Case-folded content tokens, minus stopwords."""
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


def content_token_set(text: str) -> set[str]:
    return set(tokenize(text))
