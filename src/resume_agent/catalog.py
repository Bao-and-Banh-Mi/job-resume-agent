"""Render the experience bank as a compact catalog for the calling agent.

``load_bank`` hands this structure back so the model can *read* the bank --
every entry, every bullet, every bullet_id -- and then reason about which
items fit a posting. The whole design of this server depends on the agent
seeing real bullet text and referring back to it by id, so this is the
contract that makes evidence-grounding work: the model never supplies
resume content, it only ever cites ids that already exist here.

Banks are small (a few dozen bullets), so returning the whole thing is
cheaper and far more accurate than any retrieval step.
"""

from __future__ import annotations

from typing import Any

from .models import EntryCommon, ExperienceBank


def _entry_catalog(entry: EntryCommon) -> dict[str, Any]:
    out: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "kind": entry.kind,
        "title": entry.title,
        "organization": entry.organization,
        "bullets": [
            {
                "bullet_id": b.bullet_id,
                "text": b.text,
                "evidence_ids": list(b.evidence_ids),
                # Bullets carrying hard numbers are the ones a model is most
                # tempted to "improve"; flagging them up front discourages it.
                "has_quantities": bool(b.quantities),
                "do_not_paraphrase": b.do_not_paraphrase,
            }
            for b in entry.bullets
        ],
    }
    if not entry.bullets:
        # Education entries carry their content in degree/gpa/coursework
        # rather than bullets. Say so explicitly: agents otherwise assume a
        # bullet-less entry has nothing citable and report a false gap.
        out["note"] = (
            "This entry has no bullets; cite its entry_id directly in "
            "analyze_fit for degree/GPA/coursework requirements."
        )

    for field in ("location", "start", "end", "role", "degree", "gpa", "url"):
        value = getattr(entry, field, None)
        if value:
            out[field] = value
    if entry.coursework:
        out["coursework"] = list(entry.coursework)
    if entry.tags:
        out["tags"] = list(entry.tags)
    return out


def bank_catalog(bank: ExperienceBank) -> dict[str, Any]:
    """A complete, agent-readable view of the bank."""
    return {
        "owner": {
            "name": bank.owner.name,
            "email": bank.owner.email,
        },
        "education": [_entry_catalog(e) for e in bank.education],
        "experiences": [_entry_catalog(e) for e in bank.experiences],
        "projects": [_entry_catalog(e) for e in bank.projects],
        "leadership": [_entry_catalog(e) for e in bank.leadership],
        "skills": [
            {
                "group": g.group,
                "skills": [
                    {"name": s.name, "proficiency": s.proficiency}
                    for s in g.skills
                ],
            }
            for g in bank.skills
        ],
        "totals": {
            "entries": len(bank.all_entries()),
            "bullets": sum(len(e.bullets) for e in bank.all_entries()),
            "skills": sum(len(g.skills) for g in bank.skills),
            "evidence": len(bank.evidence),
        },
    }


def bullet_index(bank: ExperienceBank) -> dict[str, tuple[EntryCommon, Any]]:
    """Map ``bullet_id -> (parent_entry, bullet)`` for O(1) validation."""
    index: dict[str, tuple[EntryCommon, Any]] = {}
    for entry in bank.all_entries():
        for bullet in entry.bullets:
            index[bullet.bullet_id] = (entry, bullet)
    return index


def entry_index(bank: ExperienceBank) -> dict[str, EntryCommon]:
    return {e.entry_id: e for e in bank.all_entries()}


def skill_index(bank: ExperienceBank) -> dict[str, Any]:
    """Map lowercased skill name -> Skill, for validating agent selections."""
    return {s.name.lower(): s for g in bank.skills for s in g.skills}
