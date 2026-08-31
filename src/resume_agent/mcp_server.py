"""MCP server exposing the tailoring pipeline over stdio.

Division of labour, and the reason this server is shaped the way it is:

**The calling LLM does the judgement.** It reads the posting, reads the bank
catalog, and decides which requirements matter and which experience speaks
to them. There is no keyword extractor: a matcher that sees "Redis,
DynamoDB, Kafka, low-latency" cannot infer "distributed systems", and a
matcher that sees "barista-made espresso" cannot tell it is a perk. A model
does both trivially.

**The server enforces the guarantees.** Everything the model asserts is
checked against the loaded bank before it can reach a PDF:

* cited bullet/entry/skill ids must exist -- unknown ids are hard errors;
* coverage claims with no surviving citation are downgraded to gaps;
* any rephrasing is classified by the evidence linker, and rephrasings that
  introduce new numbers or entities block the export outright;
* the compiled PDF is really compiled and really counted for page fit.

That split is what makes "let the model polish it" safe: the model gets full
editorial latitude over *selection and wording*, and zero latitude over
*facts*.

Nothing here reaches the network; the transport is stdio and all state is
process-local (see ``state.SessionStore``).
"""

from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from .bank import load_bank as _load_bank_from_disk
from .catalog import bank_catalog
from .export import ExportBlocked, check_export_gate, export_draft as _export_draft
from .fit import analyze_fit as _analyze_fit
from .jd_clean import clean_jd_text, looks_like_html
from .models import (
    AssessedRequirement,
    Draft,
    JobDescription,
    ResumeSelection,
)
from .state import SessionStore
from .tailor import SelectionError, attach_gaps, tailor_from_selection

_TEMPLATE_ENV = "RESUME_AGENT_TEMPLATE"
_BANK_ENV = "RESUME_AGENT_BANK_PATH"
_DEFAULT_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "resume.template.tex"

_INSTRUCTIONS = """\
Tailor a resume to a specific job posting using ONLY content from the loaded
experience bank. You supply the judgement; this server enforces honesty.

Workflow:
  1. load_bank        -> returns the full bank catalog. READ IT. Every
                         bullet_id you will cite later appears here.
  2. set_job_description -> returns cleaned posting text. READ IT.
  3. analyze_fit      -> YOU list the requirements you found in the posting
                         and, for each, cite the bank bullet_ids/skills that
                         support it. Cite nothing and it is recorded as a
                         gap. Fabricated ids are stripped and reported.
  4. tailor_resume    -> YOU choose which entries and bullets appear, in the
                         order you want them. Optionally supply
                         rewritten_text to align wording with the posting's
                         vocabulary.
  5. export_draft     -> compiles a real one-page PDF.

Rules you must follow:
  * Never claim a skill the bank cannot evidence. A gap is a correct answer.
  * Rephrasing must preserve every number and proper noun in the original
    bullet. You may re-frame emphasis; you may not add facts. The evidence
    linker will catch violations and block the export.
  * Order matters: list entries and bullets strongest-first, because
    one-page trimming removes from the tail.
  * FILL THE PAGE. One page is a ceiling, not a target. With a typical
    student bank, that means including nearly every entry -- an experience
    that isn't a bullseye for this posting still demonstrates shipped work,
    and a half-empty resume reads as a thin candidate, not a focused one.
    Only omit an entry when it would actively confuse the reader about the
    role you're applying for. tailor_resume reports bank_usage and warns
    when your selection is too narrow; export_draft reports fill_ratio.
    Aim for 0.85+; if you come back under it, add content and re-tailor.
"""


def _default_template_path() -> Path:
    override = os.environ.get(_TEMPLATE_ENV)
    if override:
        return Path(override)
    return _DEFAULT_TEMPLATE


def build_server(store: Optional[SessionStore] = None) -> MCPServer:
    """Create a configured ``MCPServer`` wired to ``store``."""
    session = store if store is not None else SessionStore()

    bank_env = os.environ.get(_BANK_ENV)
    if bank_env:
        try:
            session.set_bank(_load_bank_from_disk(bank_env), bank_env)
        except FileNotFoundError:
            pass

    server = MCPServer(
        name="resume-agent",
        title="Evidence-Grounded Resume Agent",
        version="0.2.0",
        instructions=_INSTRUCTIONS,
    )

    @server.tool(
        name="load_bank",
        description=(
            "Load an experience bank YAML and return its FULL catalog: every "
            "entry, every bullet, every bullet_id, and all skills. Read the "
            "returned catalog carefully -- it is the only source of resume "
            "content, and you must cite its bullet_ids in later calls."
        ),
    )
    def load_bank(path: Optional[str] = None) -> dict[str, Any]:
        target = path or session.bank_path() or os.environ.get(_BANK_ENV)
        if not target:
            raise ValueError(
                "no bank path given and RESUME_AGENT_BANK_PATH is unset"
            )
        bank = _load_bank_from_disk(target)
        session.set_bank(bank, target)
        return {"path": target, **bank_catalog(bank)}

    @server.tool(
        name="set_job_description",
        description=(
            "Capture a job posting. Raw scraped HTML is fine -- it is stripped "
            "to plain text. Returns the cleaned text plus a job_id. Read the "
            "cleaned text and decide for yourself what the role requires; the "
            "server does not extract requirements for you."
        ),
    )
    def set_job_description(
        raw_text: str,
        source_url: Optional[str] = None,
        source_provider: str = "generic",
        org: Optional[str] = None,
        role_title: Optional[str] = None,
    ) -> dict[str, Any]:
        was_html = looks_like_html(raw_text)
        cleaned = clean_jd_text(raw_text)
        if not cleaned:
            raise ValueError("job description is empty after cleaning")

        job_id = session.new_job_id(cleaned)
        jd = JobDescription(
            job_id=job_id,
            captured_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            source_url=source_url,
            source_provider=source_provider,  # type: ignore[arg-type]
            org=org,
            role_title=role_title,
            raw_text=cleaned,
            requirements=[],
        )
        session.put_job(jd)
        return {
            "job_id": job_id,
            "org": org,
            "role_title": role_title,
            "was_html": was_html,
            "char_count": len(cleaned),
            "cleaned_text": cleaned,
            "next_step": (
                "Read cleaned_text, identify the role's requirements, then call "
                "analyze_fit with each requirement and the bank bullet_ids that "
                "support it."
            ),
        }

    @server.tool(
        name="analyze_fit",
        description=(
            "Record YOUR assessment of how the bank matches the posting, and "
            "have it validated. Pass a list of requirements you identified; "
            "each needs: text, category (must_have|nice_to_have|responsibility"
            "|skill), verdict (covered|partial|gap), and the "
            "supporting_bullet_ids / supporting_skills backing that verdict. "
            "Citations that do not resolve to the bank are stripped, and any "
            "covered/partial verdict left with no evidence is downgraded to a "
            "gap and reported in 'corrections'. Returns flat and must-have-"
            "weighted coverage plus a recommendation."
        ),
    )
    def analyze_fit(
        requirements: list[dict[str, Any]],
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        jid = job_id or session.active_job_id()
        if not jid:
            raise ValueError("no job_id provided and no active job in session")
        session.get_job(jid)
        bank = session.bank()

        parsed = [AssessedRequirement.model_validate(r) for r in requirements]
        report = _analyze_fit(bank, jid, parsed)
        session.put_fit(jid, report)
        return report.model_dump()

    @server.tool(
        name="tailor_resume",
        description=(
            "Assemble a draft from YOUR selection. 'selection' takes: "
            "sections (list of {kind, entries:[{entry_id, bullets:[{bullet_id, "
            "rewritten_text?}]}]}), optional skills (list of {group, skills}), "
            "accept_inferred, and rationale. List strongest content first -- "
            "one-page trimming drops from the tail. rewritten_text lets you "
            "align wording with the posting, but it is checked against the "
            "original bullet's evidence: new numbers or new proper nouns are "
            "labelled 'unsupported' and will block export. Unknown ids are "
            "errors. Education is always included. The 'skills' field only "
            "sets EMPHASIS ORDER -- every bank skill is listed regardless, "
            "since all of them are evidence-backed and omitting them just "
            "makes the candidate look narrower."
        ),
    )
    def tailor_resume(
        selection: dict[str, Any],
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        jid = job_id or session.active_job_id()
        if not jid:
            raise ValueError("no job_id provided and no active job in session")
        jd = session.get_job(jid)
        bank = session.bank()

        parsed = ResumeSelection.model_validate(selection)
        try:
            draft = tailor_from_selection(bank, jd, parsed)
        except SelectionError as exc:
            return {"ok": False, "error": str(exc)}

        fit = session.get_fit(jid)
        if fit is not None:
            draft = attach_gaps(draft, [g.text for g in fit.gaps])

        session.put_draft(draft)

        blockers = check_export_gate(draft)

        # Tell the agent how much of the bank it actually used. A one-page
        # cap is a ceiling, not a target: with a small bank, omitting entries
        # is the main cause of a half-empty resume, and the agent cannot see
        # that from its own selection without being told.
        used_entries = sum(
            len(s.entries) for s in draft.sections if s.kind != "skills"
        )
        used_bullets = sum(
            len(e.bullets) for s in draft.sections for e in s.entries
        )
        avail_entries = len(bank.all_entries())
        avail_bullets = sum(len(e.bullets) for e in bank.all_entries())

        usage = {
            "entries_used": used_entries,
            "entries_available": avail_entries,
            "bullets_used": used_bullets,
            "bullets_available": avail_bullets,
        }
        advice = None
        if avail_bullets and used_bullets / avail_bullets < 0.6:
            advice = (
                f"You selected {used_bullets}/{avail_bullets} bullets and "
                f"{used_entries}/{avail_entries} entries. That will likely "
                "leave the page half empty, which reads as a thin candidate. "
                "Unless an entry is genuinely irrelevant, include it -- a "
                "full page of real experience beats a sparse 'focused' one."
            )

        return {
            "ok": True,
            "draft_id": draft.draft_id,
            "bank_usage": usage,
            "sections": [
                {
                    "kind": s.kind,
                    "entries": [
                        {
                            "title": e.title,
                            "organization": e.organization,
                            "bullets": [
                                {
                                    "draft_bullet_id": b.draft_bullet_id,
                                    "source_bullet_id": b.source_bullet_id,
                                    "text": b.rewritten_text,
                                    "label": b.classification.label,
                                    "approved": b.approved,
                                    "reason": b.classification.reason,
                                }
                                for b in e.bullets
                            ],
                        }
                        for e in s.entries
                    ],
                    "skill_groups": [
                        {"group": g.group, "skills": [k.name for k in g.skills]}
                        for g in s.skill_groups
                    ],
                }
                for s in draft.sections
            ],
            "gaps": [g.requirement_text for g in draft.gaps],
            "export_blockers": blockers,
            "sparse_warning": advice,
            "next_step": (
                "export_draft to compile a one-page PDF."
                if not blockers
                else "Fix the blocked bullets (use original wording) and re-tailor."
            ),
        }

    @server.tool(
        name="get_draft",
        description="Retrieve a previously tailored Draft by draft_id.",
    )
    def get_draft(draft_id: str) -> dict[str, Any]:
        return session.get_draft(draft_id).model_dump()

    @server.tool(
        name="export_draft",
        description=(
            "Render the draft to .tex and compile it with pdflatex, enforcing a "
            "real one-page fit by counting pages in the produced PDF. Refuses "
            "to export if any bullet is unsupported or an inferred bullet is "
            "unapproved. On overflow the least-important trailing bullets are "
            "removed (never reworded) and it recompiles; dropped bullets are "
            "reported. Also returns fill_ratio (fraction of the page actually "
            "used): below ~0.75 the resume reads as thin rather than concise, "
            "so add more genuinely-relevant bank content instead of shipping it."
        ),
    )
    def export_draft(
        draft_id: str,
        output_dir: Optional[str] = None,
        template_path: Optional[str] = None,
    ) -> dict[str, Any]:
        draft = session.get_draft(draft_id)
        gate_reasons = check_export_gate(draft)
        if gate_reasons:
            return {"exported": False, "reasons": gate_reasons}
        out_dir = Path(output_dir) if output_dir else Path.cwd() / "out"
        tpl = Path(template_path) if template_path else _default_template_path()
        try:
            result = _export_draft(draft, output_dir=out_dir, template_path=tpl)
        except ExportBlocked as exc:
            return {"exported": False, "reasons": [str(exc)]}
        return {
            "exported": result.exported,
            "tex_path": result.tex_path,
            "pdf_path": result.pdf_path,
            "draft_id": draft.draft_id,
            "page_count": result.page_count,
            "fill_ratio": result.fill_ratio,
            "dropped_bullet_ids": result.dropped_bullet_ids,
            "warnings": result.warnings,
        }

    _ = (
        load_bank,
        set_job_description,
        analyze_fit,
        tailor_resume,
        get_draft,
        export_draft,
    )
    return server


def run_stdio(store: Optional[SessionStore] = None) -> None:
    """Blocking entry point: run the server over stdio."""
    import asyncio

    server = build_server(store)
    asyncio.run(server.run_stdio_async())


def preview_draft(draft: Draft) -> dict[str, Any]:
    """Compact dict snapshot of a draft, used by the CLI."""
    return {
        "draft_id": draft.draft_id,
        "job_id": draft.job_id,
        "status": draft.status,
        "gaps": [g.requirement_text for g in draft.gaps],
        "sections": [
            {
                "kind": s.kind,
                "entries": [
                    {
                        "title": e.title,
                        "organization": e.organization,
                        "bullets": [
                            {
                                "text": b.rewritten_text,
                                "label": b.classification.label,
                                "overlap": b.classification.token_overlap,
                            }
                            for b in e.bullets
                        ],
                    }
                    for e in s.entries
                ],
                "skill_groups": [
                    {"group": g.group, "skills": [k.name for k in g.skills]}
                    for g in s.skill_groups
                ],
            }
            for s in draft.sections
        ],
    }
