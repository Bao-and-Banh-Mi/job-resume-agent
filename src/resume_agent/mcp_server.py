"""MCP server exposing the tailoring pipeline over stdio.

The server exposes five tools that together cover the POC flow: load the
bank, capture a JD, tailor a draft, inspect a draft, and export it.
Nothing here reaches the network; the transport is stdio and all state is
process-local (see ``state.SessionStore``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from .bank import load_bank as _load_bank_from_disk
from .export import ExportBlocked, check_export_gate, export_draft as _export_draft
from .models import Draft, JobDescription
from .state import SessionStore
from .tailor import analyze_jd, tailor as _tailor

_TEMPLATE_ENV = "RESUME_AGENT_TEMPLATE"
_BANK_ENV = "RESUME_AGENT_BANK_PATH"
_DEFAULT_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "resume.template.tex"


def _default_template_path() -> Path:
    override = os.environ.get(_TEMPLATE_ENV)
    if override:
        return Path(override)
    return _DEFAULT_TEMPLATE


def build_server(store: Optional[SessionStore] = None) -> MCPServer:
    """Create a configured ``MCPServer`` with the five tools wired to ``store``."""
    session = store if store is not None else SessionStore()

    # If the caller set RESUME_AGENT_BANK_PATH, eagerly load the bank so that
    # tools work without an explicit ``load_bank`` call.
    bank_env = os.environ.get(_BANK_ENV)
    if bank_env:
        try:
            session.set_bank(_load_bank_from_disk(bank_env), bank_env)
        except FileNotFoundError:
            pass

    server = MCPServer(
        name="resume-agent",
        title="Evidence-Grounded Resume Agent",
        version="0.1.0",
        instructions=(
            "Tailor resumes to a specific job description using only claims from "
            "the loaded experience bank. Never invents content."
        ),
    )

    @server.tool(
        name="load_bank",
        description="Load an experience bank YAML file into the session.",
    )
    def load_bank(path: str) -> dict[str, Any]:
        bank = _load_bank_from_disk(path)
        session.set_bank(bank, path)
        return {
            "path": path,
            "owner": bank.owner.name,
            "experience_count": len(bank.experiences),
            "project_count": len(bank.projects),
            "leadership_count": len(bank.leadership),
            "education_count": len(bank.education),
            "evidence_count": len(bank.evidence),
        }

    @server.tool(
        name="set_job_description",
        description=(
            "Capture a job description for the current session and return its "
            "job_id. Requirements are extracted deterministically from the raw text."
        ),
    )
    def set_job_description(
        raw_text: str,
        source_url: Optional[str] = None,
        source_provider: str = "generic",
        org: Optional[str] = None,
        role_title: Optional[str] = None,
    ) -> dict[str, Any]:
        import datetime as _dt

        job_id = session.new_job_id(raw_text)
        requirements = analyze_jd(raw_text)
        jd = JobDescription(
            job_id=job_id,
            captured_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            source_url=source_url,
            source_provider=source_provider,  # type: ignore[arg-type]
            org=org,
            role_title=role_title,
            raw_text=raw_text,
            requirements=requirements,
        )
        session.put_job(jd)
        return {
            "job_id": job_id,
            "requirements": [r.model_dump() for r in requirements],
        }

    @server.tool(
        name="tailor_resume",
        description=(
            "Produce a tailored Draft for the given job_id (or the active JD)."
        ),
    )
    def tailor_resume(job_id: Optional[str] = None) -> dict[str, Any]:
        jid = job_id or session.active_job_id()
        if not jid:
            raise ValueError("no job_id provided and no active job in session")
        jd = session.get_job(jid)
        bank = session.bank()
        draft = _tailor(bank, jd)
        session.put_draft(draft)
        return draft.model_dump()

    @server.tool(
        name="get_draft",
        description="Retrieve a previously tailored Draft by draft_id.",
    )
    def get_draft(draft_id: str) -> dict[str, Any]:
        draft = session.get_draft(draft_id)
        return draft.model_dump()

    @server.tool(
        name="export_draft",
        description=(
            "Render an approved Draft to a .tex file. Refuses to export if any "
            "bullet is unsupported or an inferred bullet is unapproved."
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
            return {
                "exported": False,
                "reasons": gate_reasons,
            }
        out_dir = Path(output_dir) if output_dir else Path.cwd() / "out"
        tpl = Path(template_path) if template_path else _default_template_path()
        try:
            result = _export_draft(draft, output_dir=out_dir, template_path=tpl)
        except ExportBlocked as exc:
            return {"exported": False, "reasons": [str(exc)]}
        return {
            "exported": True,
            "tex_path": result.tex_path,
            "draft_id": draft.draft_id,
        }

    # Retain references so type-checkers/linters don't flag them as unused.
    _ = (load_bank, set_job_description, tailor_resume, get_draft, export_draft)
    return server


def run_stdio(store: Optional[SessionStore] = None) -> None:
    """Blocking entry point: run the server over stdio."""
    import asyncio

    server = build_server(store)
    asyncio.run(server.run_stdio_async())


def preview_draft(draft: Draft) -> dict[str, Any]:
    """Convenience helper used by the CLI: a compact dict snapshot of a draft."""
    return {
        "draft_id": draft.draft_id,
        "job_id": draft.job_id,
        "status": draft.status,
        "coverage_ratio": draft.keyword_coverage.coverage_ratio,
        "unmatched": draft.keyword_coverage.unmatched,
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
