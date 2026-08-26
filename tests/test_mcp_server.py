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
from resume_agent.tailor import tailor as _tailor


def _tool_callable(server, name: str):
    """Return the plain Python function the server registered for ``name``."""
    tools = server._tool_manager.list_tools()
    match = next((t for t in tools if t.name == name), None)
    assert match is not None, f"tool not registered: {name}"
    return match.fn


def test_server_registers_all_five_tools():
    server = build_server(SessionStore())
    names = {t.name for t in server._tool_manager.list_tools()}
    expected = {
        "load_bank",
        "set_job_description",
        "tailor_resume",
        "get_draft",
        "export_draft",
    }
    assert expected.issubset(names)


def test_full_flow_via_tools(tmp_path, sample_jd_text):
    store = SessionStore()
    server = build_server(store)

    load_bank = _tool_callable(server, "load_bank")
    set_jd = _tool_callable(server, "set_job_description")
    tailor_resume = _tool_callable(server, "tailor_resume")
    get_draft = _tool_callable(server, "get_draft")
    export_draft = _tool_callable(server, "export_draft")

    repo_root = Path(__file__).resolve().parents[1]
    bank_info = load_bank(path=str(repo_root / "docs" / "example-experience-bank.yaml"))
    assert bank_info["experience_count"] >= 1

    jd_info = set_jd(raw_text=sample_jd_text)
    assert jd_info["job_id"].startswith("job-")
    assert jd_info["requirements"]

    draft = tailor_resume(job_id=jd_info["job_id"])
    assert draft["draft_id"].startswith("draft-")
    assert draft["sections"]

    fetched = get_draft(draft_id=draft["draft_id"])
    assert fetched["draft_id"] == draft["draft_id"]

    export_result = export_draft(
        draft_id=draft["draft_id"],
        output_dir=str(tmp_path),
        template_path=str(repo_root / "templates" / "resume.template.tex"),
    )
    assert export_result["exported"] is True
    assert Path(export_result["tex_path"]).exists()


def test_tailor_resume_needs_job_id():
    server = build_server(SessionStore())
    tailor_resume = _tool_callable(server, "tailor_resume")
    with pytest.raises(ValueError):
        tailor_resume()


def test_preview_draft_shape(example_bank, sample_jd_text):
    from resume_agent.models import JobDescription
    from resume_agent.tailor import analyze_jd
    import datetime as _dt

    jd = JobDescription(
        job_id="job-preview",
        captured_at=_dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc).isoformat(),
        raw_text=sample_jd_text,
        requirements=analyze_jd(sample_jd_text),
    )
    draft = _tailor(example_bank, jd)
    preview = preview_draft(draft)
    assert preview["draft_id"] == draft.draft_id
    assert "sections" in preview
    assert isinstance(preview["coverage_ratio"], float)
