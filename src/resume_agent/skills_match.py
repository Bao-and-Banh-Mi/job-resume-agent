"""Pure requirement-vs-bank matcher.

``match_skills`` reports which JD requirements are supported by the loaded
experience bank and which are gaps. It never rewrites, drafts, or exports
anything; an agent is expected to call this first to decide whether the
bank has enough evidence for a given role before invoking ``tailor_resume``.

The matching semantics reuse :func:`resume_agent.retriever.find_matching_keywords`
so the report and the ranker never drift apart.
"""

from __future__ import annotations

from .models import (
    ExperienceBank,
    JobDescription,
    RequirementMatch,
    SkillsMatch,
)
from .retriever import bullet_haystack, find_matching_keywords


def _requirement_keywords(requirement_text: str, keywords: list[str]) -> list[str]:
    if keywords:
        return keywords
    return [requirement_text]


def match_skills(bank: ExperienceBank, jd: JobDescription) -> SkillsMatch:
    """Return per-requirement evidence pointers plus a coverage ratio."""
    matched: list[RequirementMatch] = []
    unmatched: list[RequirementMatch] = []

    entries = bank.all_entries()

    for req in jd.requirements:
        req_kws = _requirement_keywords(req.text, list(req.keywords))
        req_kws_lower = {k.lower() for k in req_kws}

        matched_kws: set[str] = set()
        evidence_ids: set[str] = set()
        bullet_ids: set[str] = set()
        skill_names: set[str] = set()

        for entry in entries:
            for bullet in entry.bullets:
                hits = find_matching_keywords(req_kws, bullet_haystack(entry, bullet))
                if hits:
                    matched_kws.update(hits)
                    bullet_ids.add(bullet.bullet_id)
                    evidence_ids.update(bullet.evidence_ids)

        for group in bank.skills:
            for skill in group.skills:
                if skill.name.lower() in req_kws_lower:
                    # Record whichever spelling the requirement used.
                    for kw in req_kws:
                        if kw.lower() == skill.name.lower():
                            matched_kws.add(kw)
                    skill_names.add(skill.name)
                    evidence_ids.update(skill.evidence_ids)

        row = RequirementMatch(
            requirement_id=req.requirement_id,
            requirement_text=req.text,
            matched_keywords=sorted(matched_kws),
            evidence_ids=sorted(evidence_ids),
            bullet_ids=sorted(bullet_ids),
            skill_names=sorted(skill_names),
        )
        if row.bullet_ids or row.skill_names:
            matched.append(row)
        else:
            unmatched.append(row)

    total = len(jd.requirements) or 1
    return SkillsMatch(
        job_id=jd.job_id,
        total_requirements=len(jd.requirements),
        matched=matched,
        unmatched=unmatched,
        coverage_ratio=round(len(matched) / total, 3),
    )
