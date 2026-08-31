"""Assemble a Draft from the agent's selection.

This module used to *decide* what belonged on the resume, using keyword
overlap. It no longer does. The calling LLM decides -- it can read the
posting and the bank and understands that "Redis, DynamoDB, Kafka" implies
distributed-systems work, which no keyword matcher ever will.

What survives here is the part a model should not be trusted with:

* **Reference integrity** -- every selected bullet/entry/skill must exist in
  the bank. Unknown ids are rejected loudly, not silently skipped, so a
  hallucinated id fails the call instead of quietly shrinking the resume.
* **Rephrase gating** -- if the agent supplied ``rewritten_text``, the
  evidence linker classifies it against the original bullet and its cited
  evidence. New numbers or new named entities => ``unsupported`` => export
  is blocked. This is what makes "let the LLM polish it" safe.
* **Structural completeness** -- Education is always emitted when the bank
  has any, and a Skills section is always emitted when the bank has any
  skills. A resume without Education is disqualifying regardless of what a
  keyword matcher thought, and this was a real defect in the previous
  keyword-gated pipeline.
"""

from __future__ import annotations

import datetime as _dt
import hashlib

from .catalog import bullet_index, entry_index, skill_index
from .evidence_linker import classify_bullet
from .prose import check_prose
from .models import (
    Draft,
    DraftBullet,
    DraftEntry,
    DraftSection,
    EntryCommon,
    ExperienceBank,
    Gap,
    JobDescription,
    ResumeSelection,
    Skill,
    SkillGroup,
)

_SECTION_ORDER = ["education", "experience", "projects", "leadership"]
_SECTION_TO_BANK_ATTR = {
    "education": "education",
    "experience": "experiences",
    "projects": "projects",
    "leadership": "leadership",
}


class SelectionError(ValueError):
    """Raised when a selection references content that is not in the bank."""


def _short_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{h}"


def _build_bullet(
    entry: EntryCommon,
    bullet,
    rewritten: str | None,
    evidence_index,
    draft_id: str,
    accept_inferred: bool,
) -> DraftBullet:
    cited = [
        evidence_index[eid] for eid in bullet.evidence_ids if eid in evidence_index
    ]

    # A bullet marked do_not_paraphrase is a hard "verbatim only" instruction
    # from the bank owner -- typically because it carries an exact metric or
    # an official title. Honour it over the agent's preference.
    if rewritten and bullet.do_not_paraphrase:
        raise SelectionError(
            f"bullet {bullet.bullet_id} is marked do_not_paraphrase but a "
            "rewritten_text was supplied; use the original wording"
        )

    text = rewritten.strip() if rewritten and rewritten.strip() else bullet.text

    # Order matters. The evidence linker runs FIRST and its verdict wins:
    # fabrication is a factual defect and must be reported as 'unsupported'
    # rather than being masked by a style complaint about the same edit. A
    # rewrite that both invents a number and says "leveraged" is an honesty
    # problem first.
    classification = classify_bullet(
        rewritten_text=text,
        original_bullet_text=bullet.text,
        cited_evidence=cited,
    )

    # The prose gate is the second, independent check: "is this well written,
    # and is it a tailoring edit rather than a restatement?". A rewrite that
    # keeps every fact but arrives draped in "leveraged" and "seamlessly"
    # passes the linker -- and is exactly what makes a resume read as
    # generated. Only evaluated for factually-sound rewrites, so the error
    # the agent sees is always the most serious one.
    prose_verdict = None
    if rewritten and text != bullet.text and classification.label != "unsupported":
        prose_verdict = check_prose(original=bullet.text, rewritten=text)
        if not prose_verdict.ok:
            raise SelectionError(
                f"bullet {bullet.bullet_id}: {prose_verdict.reason}"
            )

    if classification.label in ("verbatim", "paraphrased"):
        approved = True
    elif classification.label == "inferred":
        approved = accept_inferred
    else:  # unsupported -- never auto-approvable
        approved = False

    return DraftBullet(
        draft_bullet_id=_short_id("db", draft_id, bullet.bullet_id),
        source_bullet_id=bullet.bullet_id,
        source_entry_id=entry.entry_id,
        cited_evidence_ids=[c.evidence_id for c in cited],
        original_text=bullet.text,
        rewritten_text=text,
        classification=classification,
        edited_by_user=bool(rewritten),
        approved=approved,
        edit_fraction=prose_verdict.edit_fraction if prose_verdict else 0.0,
    )


def _draft_entry_from(entry: EntryCommon, bullets: list[DraftBullet]) -> DraftEntry:
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


def _resolve_skills(
    bank: ExperienceBank, selection: ResumeSelection
) -> list[SkillGroup]:
    """Resolve the Skills section: the agent reorders, it never omits.

    Every skill in the bank is already evidence-backed, so there is no
    honesty argument for hiding one -- and a posting that does not *mention*
    Julia is not a posting that penalises knowing Julia. Dropping unmatched
    skills only made the resume shorter and the candidate look narrower,
    which is the opposite of what tailoring is for.

    So the agent's selection is treated as an *emphasis* signal: the groups
    and skills it names lead, in the order it gave, and every remaining bank
    skill is appended afterwards under its own bank group. Selecting nothing
    yields the bank's own ordering.
    """
    index = skill_index(bank)

    groups: list[SkillGroup] = []
    used: set[str] = set()

    for sel in selection.skills:
        kept: list[Skill] = []
        for name in sel.skills:
            skill = index.get(name.lower())
            if skill is None:
                raise SelectionError(
                    f"skill {name!r} is not in the bank; a resume may only "
                    "list skills the bank can evidence"
                )
            if skill.name.lower() in used:
                continue
            kept.append(skill)
            used.add(skill.name.lower())
        if kept:
            groups.append(SkillGroup(group=sel.group, skills=kept))

    # Append everything the agent did not mention, preserving bank grouping.
    for bank_group in bank.skills:
        remaining = [s for s in bank_group.skills if s.name.lower() not in used]
        if not remaining:
            continue
        existing = next(
            (g for g in groups if g.group.lower() == bank_group.group.lower()), None
        )
        if existing is not None:
            existing.skills.extend(remaining)
        else:
            groups.append(SkillGroup(group=bank_group.group, skills=remaining))
        used.update(s.name.lower() for s in remaining)

    return groups


def tailor_from_selection(
    bank: ExperienceBank,
    jd: JobDescription,
    selection: ResumeSelection,
) -> Draft:
    """Assemble a Draft from an agent-provided selection."""
    bullets = bullet_index(bank)
    entries = entry_index(bank)
    evidence_index = bank.evidence_index()

    draft_id = _short_id("draft", jd.job_id, selection.rationale[:64])

    chosen_by_kind: dict[str, list[DraftEntry]] = {}

    for section in selection.sections:
        built: list[DraftEntry] = []
        for sel_entry in section.entries:
            entry = entries.get(sel_entry.entry_id)
            if entry is None:
                raise SelectionError(
                    f"entry_id {sel_entry.entry_id!r} is not in the bank"
                )

            draft_bullets: list[DraftBullet] = []
            for sel_bullet in sel_entry.bullets:
                found = bullets.get(sel_bullet.bullet_id)
                if found is None:
                    raise SelectionError(
                        f"bullet_id {sel_bullet.bullet_id!r} is not in the bank"
                    )
                parent, bullet = found
                if parent.entry_id != entry.entry_id:
                    raise SelectionError(
                        f"bullet {sel_bullet.bullet_id!r} belongs to entry "
                        f"{parent.entry_id!r}, not {entry.entry_id!r}"
                    )
                draft_bullets.append(
                    _build_bullet(
                        entry,
                        bullet,
                        sel_bullet.rewritten_text,
                        evidence_index,
                        draft_id,
                        selection.accept_inferred,
                    )
                )
            built.append(_draft_entry_from(entry, draft_bullets))
        chosen_by_kind.setdefault(section.kind, []).extend(built)

    # Education is structural: always include it when the bank has any, even
    # if the agent did not select it. An intern resume without Education is
    # rejected by humans and parsers alike.
    if not chosen_by_kind.get("education") and bank.education:
        chosen_by_kind["education"] = [
            _draft_entry_from(e, []) for e in bank.education
        ]

    sections: list[DraftSection] = []
    for kind in _SECTION_ORDER:
        built = chosen_by_kind.get(kind, [])
        if not built:
            continue
        sections.append(
            DraftSection(
                section_id=_short_id("sec", draft_id, kind),
                kind=kind,  # type: ignore[arg-type]
                entries=built,
            )
        )

    sections.append(
        DraftSection(
            section_id=_short_id("sec", draft_id, "skills"),
            kind="skills",
            entries=[],
            skill_groups=_resolve_skills(bank, selection),
        )
    )

    return Draft(
        draft_id=draft_id,
        job_id=jd.job_id,
        created_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        status="ready_for_review",
        owner=bank.owner,
        sections=sections,
        gaps=[],
    )


def attach_gaps(draft: Draft, gap_texts: list[str]) -> Draft:
    """Record the fit report's gaps on the draft for reviewer visibility."""
    draft.gaps = [
        Gap(
            requirement_id=_short_id("req", text),
            requirement_text=text,
            reason="no_matching_evidence",
        )
        for text in gap_texts
    ]
    return draft
