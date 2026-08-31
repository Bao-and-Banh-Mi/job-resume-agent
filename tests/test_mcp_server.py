"""Smoke tests for the MCP server tool wiring.

We do not spin up the stdio transport; instead we build the server, look
up each tool by name, and invoke its underlying callable. That exercises
the exact code paths a real MCP client would hit while keeping the tests
fast and synchronous.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_agent.mcp_server import build_server, preview_draft
from resume_agent.state import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[1]
BANK = REPO_ROOT / "docs" / "example-experience-bank.yaml"
TEMPLATE = REPO_ROOT / "templates" / "resume.template.tex"


def _tool_callable(server, name: str):
    tools = server._tool_manager.list_tools()
    match = next((t for t in tools if t.name == name), None)
    assert match is not None, f"tool not registered: {name}"
    return match.fn


def test_server_registers_the_tool_surface():
    server = build_server(SessionStore())
    names = {t.name for t in server._tool_manager.list_tools()}
    assert {
        "load_bank",
        "set_job_description",
        "analyze_fit",
        "tailor_resume",
        "get_draft",
        "export_draft",
    }.issubset(names)


def test_load_bank_returns_a_readable_catalog_with_bullet_ids():
    server = build_server(SessionStore())
    catalog = _tool_callable(server, "load_bank")(path=str(BANK))
    assert catalog["totals"]["bullets"] > 0
    bullets = catalog["experiences"][0]["bullets"]
    assert bullets[0]["bullet_id"]
    assert bullets[0]["text"]


def test_set_job_description_cleans_html_and_returns_text():
    server = build_server(SessionStore())
    set_jd = _tool_callable(server, "set_job_description")
    info = set_jd(raw_text="<div><p>We need Python.</p><script>junk()</script></div>")
    assert info["was_html"] is True
    assert "junk()" not in info["cleaned_text"]
    assert "We need Python." in info["cleaned_text"]
    # No requirements are invented for the caller.
    assert "requirements" not in info


def test_full_agent_flow(tmp_path, sample_jd_text):
    store = SessionStore()
    server = build_server(store)

    catalog = _tool_callable(server, "load_bank")(path=str(BANK))
    jd = _tool_callable(server, "set_job_description")(raw_text=sample_jd_text)

    first_entry = catalog["experiences"][0]
    first_bullet = first_entry["bullets"][0]["bullet_id"]

    fit = _tool_callable(server, "analyze_fit")(
        job_id=jd["job_id"],
        requirements=[
            {
                "text": "Python",
                "category": "must_have",
                "verdict": "covered",
                "supporting_bullet_ids": [first_bullet],
            },
            {"text": "Kubernetes", "category": "nice_to_have", "verdict": "gap"},
        ],
    )
    assert fit["total_requirements"] == 2
    assert len(fit["covered"]) == 1
    assert fit["corrections"] == []

    result = _tool_callable(server, "tailor_resume")(
        job_id=jd["job_id"],
        selection={
            "sections": [
                {
                    "kind": "experience",
                    "entries": [
                        {
                            "entry_id": first_entry["entry_id"],
                            "bullets": [{"bullet_id": first_bullet}],
                        }
                    ],
                }
            ],
            "rationale": "strongest Python evidence",
        },
    )
    assert result["ok"] is True
    assert result["export_blockers"] == []
    # Gaps from analyze_fit are carried onto the draft.
    assert "Kubernetes" in result["gaps"]

    fetched = _tool_callable(server, "get_draft")(draft_id=result["draft_id"])
    assert fetched["draft_id"] == result["draft_id"]

    export = _tool_callable(server, "export_draft")(
        draft_id=result["draft_id"],
        output_dir=str(tmp_path),
        template_path=str(TEMPLATE),
    )
    assert export["exported"] is True
    assert Path(export["tex_path"]).exists()


def test_tailor_resume_reports_bad_ids_without_crashing(sample_jd_text):
    server = build_server(SessionStore())
    _tool_callable(server, "load_bank")(path=str(BANK))
    jd = _tool_callable(server, "set_job_description")(raw_text=sample_jd_text)
    out = _tool_callable(server, "tailor_resume")(
        job_id=jd["job_id"],
        selection={
            "sections": [
                {
                    "kind": "experience",
                    "entries": [{"entry_id": "exp-fake", "bullets": []}],
                }
            ]
        },
    )
    assert out["ok"] is False
    assert "exp-fake" in out["error"]


def test_analyze_fit_reports_hallucinated_citations(sample_jd_text):
    server = build_server(SessionStore())
    _tool_callable(server, "load_bank")(path=str(BANK))
    jd = _tool_callable(server, "set_job_description")(raw_text=sample_jd_text)
    fit = _tool_callable(server, "analyze_fit")(
        job_id=jd["job_id"],
        requirements=[
            {
                "text": "Rust",
                "verdict": "covered",
                "supporting_bullet_ids": ["bul-nope"],
            }
        ],
    )
    assert fit["coverage_ratio"] == 0.0
    assert fit["corrections"]


def test_tailor_resume_needs_job_id():
    server = build_server(SessionStore())
    with pytest.raises(ValueError):
        _tool_callable(server, "tailor_resume")(selection={"sections": []})


def test_preview_draft_shape(example_bank, full_selection):
    import datetime as _dt

    from resume_agent.models import JobDescription, ResumeSelection
    from resume_agent.tailor import tailor_from_selection

    jd = JobDescription(
        job_id="job-preview",
        captured_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).isoformat(),
        raw_text="anything",
    )
    draft = tailor_from_selection(
        example_bank, jd, ResumeSelection.model_validate(full_selection)
    )
    preview = preview_draft(draft)
    assert preview["draft_id"] == draft.draft_id
    assert preview["sections"]
