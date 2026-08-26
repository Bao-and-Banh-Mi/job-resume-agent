"""Ranks bank bullets against a set of JD keywords.

Deterministic scoring: for each bullet we count how many JD keywords match
(case-insensitive) against the bullet's own text, its parent entry's tags,
its named entities, and its organization. Ties are broken by bullet order
in the bank so the output is stable across runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import BulletEntry, EntryCommon


@dataclass(frozen=True)
class RankedBullet:
    entry: EntryCommon
    bullet: BulletEntry
    score: int
    matched_keywords: tuple[str, ...]


def _match_keywords(keywords: list[str], haystack: str) -> list[str]:
    hay_lower = haystack.lower()
    matched: list[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        # Word-boundary-ish check: the keyword must appear as a substring but not
        # inside a longer word. Cheap approximation: pad haystack with spaces.
        padded = f" {hay_lower} "
        # For hyphenated / multi-word keywords, plain substring is fine.
        if " " in kw_lower or "-" in kw_lower:
            if kw_lower in hay_lower:
                matched.append(kw)
            continue
        # Single-token: enforce a non-alphanumeric boundary.
        i = padded.find(kw_lower)
        while i != -1:
            before = padded[i - 1]
            after = padded[i + len(kw_lower)]
            if not before.isalnum() and not after.isalnum():
                matched.append(kw)
                break
            i = padded.find(kw_lower, i + 1)
    return matched


def _bullet_haystack(entry: EntryCommon, bullet: BulletEntry) -> str:
    parts: list[str] = [
        bullet.text,
        " ".join(bullet.named_entities),
        " ".join(entry.tags),
        entry.title,
        entry.organization,
    ]
    if entry.role:
        parts.append(entry.role)
    return " \n ".join(parts)


def rank_bullets(
    entries: list[EntryCommon], keywords: list[str]
) -> list[RankedBullet]:
    ranked: list[RankedBullet] = []
    for entry in entries:
        for bullet in entry.bullets:
            haystack = _bullet_haystack(entry, bullet)
            matched = _match_keywords(keywords, haystack)
            ranked.append(
                RankedBullet(
                    entry=entry,
                    bullet=bullet,
                    score=len(matched),
                    matched_keywords=tuple(matched),
                )
            )
    ranked.sort(key=lambda r: (-r.score, r.entry.entry_id, r.bullet.bullet_id))
    return ranked
