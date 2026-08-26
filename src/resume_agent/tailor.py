"""Deterministic tailoring pipeline.

Given a JD and a loaded ``ExperienceBank``, produce a ``Draft`` whose
bullets are drawn *verbatim* from the bank. Selection is a keyword-overlap
ranking; ordering within each entry preserves the ranked order. Every
draft bullet is classified by the evidence linker, so downstream export
gating is trivially satisfied for the base pipeline.

Rephrasing is deliberately absent from the POC. The data model already
records ``original_text`` and ``rewritten_text`` per draft bullet, so a
reviewer-driven edit path can live on top of this pipeline without
changing the tailoring API.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from typing import Iterable

from .evidence_linker import classify_bullet
from .keywords import extract_keywords
from .models import (
    Draft,
    DraftBullet,
    DraftEntry,
    DraftSection,
    EntryCommon,
    EvidenceItem,
    ExperienceBank,
    Gap,
    JobDescription,
    KeywordCoverage,
    Requirement,
    SkillGroup,
)
from .retriever import RankedBullet, rank_bullets

# Section-level caps to keep the tailored resume single-page-ish.
_MAX_BULLETS_PER_ENTRY = 3
_MAX_ENTRIES_PER_SECTION = {
    "experience": 3,
    "project": 3,
    "leadership": 2,
    "education": 2,
}


def _short_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{h}"


def analyze_jd(jd_text: str) -> list[Requirement]:
    """Turn a JD blob into a stable list of Requirement rows."""
    keywords = extract_keywords(jd_text)
    reqs: list[Requirement] = []
    for kw in keywords:
        reqs.append(
            Requirement(
                requirement_id=_short_id("req", kw),
                text=kw,
                category="skill",
                keywords=[kw],
            )
        )
    return reqs


def _select_bullets_for_section(
    entries: list[EntryCommon],
    ranked: list[RankedBullet],
) -> dict[str, list[RankedBullet]]:
    """Group top-ranked bullets by their parent entry_id."""
    by_entry: dict[str, list[RankedBullet]] = {}
    entry_ids = {e.entry_id for e in entries}
    for r in ranked:
        if r.entry.entry_id not in entry_ids:
            continue
        by_entry.setdefault(r.entry.entry_id, []).append(r)
    return by_entry


def _keep_top_entries(
    by_entry: dict[str, list[RankedBullet]], entries: list[EntryCommon], cap: int
) -> list[EntryCommon]:
    """Return entries ordered by best matched bullet score, then bank order."""
    scored = []
    order = {e.entry_id: i for i, e in enumerate(entries)}
    for entry in entries:
        bullets = by_entry.get(entry.entry_id, [])
        top = max((b.score for b in bullets), default=0)
        scored.append((top, order[entry.entry_id], entry))
    # Sort: higher score first, then original bank order.
    scored.sort(key=lambda t: (-t[0], t[1]))
    kept = [entry for score, _, entry in scored if score > 0][:cap]
    if not kept:
        # Fall back to the first ``cap`` entries so the section is never empty.
        kept = entries[:cap]
    kept.sort(key=lambda e: order[e.entry_id])
    return kept


def _build_draft_bullets(
    entry: EntryCommon,
    ranked_for_entry: list[RankedBullet],
    evidence_index: dict[str, EvidenceItem],
    draft_id: str,
) -> list[DraftBullet]:
    picked = ranked_for_entry[:_MAX_BULLETS_PER_ENTRY]
    if not picked:
        picked = [
            RankedBullet(entry=entry, bullet=b, score=0, matched_keywords=())
            for b in entry.bullets[:_MAX_BULLETS_PER_ENTRY]
        ]

    out: list[DraftBullet] = []
    for r in picked:
        cited = [
            evidence_index[eid]
            for eid in r.bullet.evidence_ids
            if eid in evidence_index
        ]
        classification = classify_bullet(
            rewritten_text=r.bullet.text,
            original_bullet_text=r.bullet.text,
            cited_evidence=cited,
        )
        out.append(
            DraftBullet(
                draft_bullet_id=_short_id("db", draft_id, r.bullet.bullet_id),
                source_bullet_id=r.bullet.bullet_id,
                source_entry_id=entry.entry_id,
                cited_evidence_ids=[c.evidence_id for c in cited],
                original_text=r.bullet.text,
                rewritten_text=r.bullet.text,
                classification=classification,
                edited_by_user=False,
                # Verbatim bullets require no explicit approval to export.
                approved=classification.label in {"verbatim", "paraphrased"},
            )
        )
    return out


def _draft_entry_from(
    entry: EntryCommon, bullets: list[DraftBullet]
) -> DraftEntry:
    return DraftEntry(
        source_entry_id=entry.entry_id,
        kind=entry.kind,
        title=entry.title,
        organization=entry.organization,
        location=entry.location,
        start=entry.start,
        end=entry.end,
        role=entry.role,
        degree=entry.degree,
        gpa=entry.gpa,
        coursework=entry.coursework,
        bullets=bullets,
    )


def _filter_skill_groups(
    bank_groups: Iterable[SkillGroup], keywords: list[str]
) -> list[SkillGroup]:
    """Keep only skills the JD mentions; drop empty groups."""
    kw_lower = {k.lower() for k in keywords}
    out: list[SkillGroup] = []
    for g in bank_groups:
        kept = [s for s in g.skills if s.name.lower() in kw_lower]
        if kept:
            out.append(SkillGroup(group=g.group, skills=kept))
    # If nothing matched, emit all groups (so the section is populated).
    if not out:
        out = [SkillGroup(**g.model_dump()) for g in bank_groups]
    return out


def _keyword_coverage(
    keywords: list[str], sections: list[DraftSection]
) -> KeywordCoverage:
    matched_map: dict[str, list[str]] = {}
    unmatched: list[str] = []
    for kw in keywords:
        hits: list[str] = []
        kw_lower = kw.lower()
        for section in sections:
            for entry in section.entries:
                for b in entry.bullets:
                    if kw_lower in b.rewritten_text.lower():
                        hits.append(b.draft_bullet_id)
            for g in section.skill_groups:
                for s in g.skills:
                    if s.name.lower() == kw_lower:
                        hits.append(f"skill:{s.name}")
        if hits:
            matched_map[kw] = hits
        else:
            unmatched.append(kw)
    matched = [{"keyword": k, "bullet_ids": v} for k, v in matched_map.items()]
    total = len(keywords) or 1
    return KeywordCoverage(
        jd_keywords=keywords,
        matched=matched,
        unmatched=unmatched,
        coverage_ratio=round(len(matched_map) / total, 3),
    )


def _identify_gaps(
    unmatched_keywords: list[str], requirements: list[Requirement]
) -> list[Gap]:
    req_by_text = {r.text.lower(): r for r in requirements}
    out: list[Gap] = []
    for kw in unmatched_keywords:
        req = req_by_text.get(kw.lower())
        if not req:
            continue
        out.append(
            Gap(
                requirement_id=req.requirement_id,
                requirement_text=req.text,
                reason="no_matching_evidence",
            )
        )
    return out


def tailor(bank: ExperienceBank, jd: JobDescription) -> Draft:
    keywords = [r.text for r in jd.requirements] or extract_keywords(jd.raw_text)
    evidence_index = bank.evidence_index()

    draft_id = _short_id("draft", jd.job_id, str(len(bank.experiences)))

    section_specs: list[tuple[str, str, list[EntryCommon], str]] = [
        ("experience", "experience", bank.experiences, "experience"),
        ("projects", "project", bank.projects, "project"),
        ("leadership", "leadership", bank.leadership, "leadership"),
        ("education", "education", bank.education, "education"),
    ]

    sections: list[DraftSection] = []
    for section_kind, entry_kind, entries, cap_key in section_specs:
        if not entries:
            continue
        ranked = rank_bullets(entries, keywords)
        by_entry = _select_bullets_for_section(entries, ranked)
        kept_entries = _keep_top_entries(
            by_entry, entries, _MAX_ENTRIES_PER_SECTION[cap_key]
        )
        draft_entries = [
            _draft_entry_from(
                e,
                _build_draft_bullets(
                    e, by_entry.get(e.entry_id, []), evidence_index, draft_id
                ),
            )
            for e in kept_entries
        ]
        sections.append(
            DraftSection(
                section_id=_short_id("sec", draft_id, section_kind),
                kind=section_kind,
                entries=draft_entries,
            )
        )

    skills_section = DraftSection(
        section_id=_short_id("sec", draft_id, "skills"),
        kind="skills",
        entries=[],
        skill_groups=_filter_skill_groups(bank.skills, keywords),
    )
    sections.append(skills_section)

    coverage = _keyword_coverage(keywords, sections)
    gaps = _identify_gaps(coverage.unmatched, jd.requirements)

    return Draft(
        draft_id=draft_id,
        job_id=jd.job_id,
        created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        status="ready_for_review",
        owner=bank.owner,
        sections=sections,
        gaps=gaps,
        keyword_coverage=coverage,
    )
