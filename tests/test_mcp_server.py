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


# --- regressions found by a live Claude Code agent run (Stripe posting) ----


def test_selection_accepts_singular_project_kind_from_catalog(sample_jd_text):
    """load_bank reports kind 'project'; tailor_resume demanded 'projects'.

    A live agent copied the spelling out of the catalog and got a validation
    error. The tool contradicting its own output is our bug, so both spellings
    are now accepted and normalised.
    """
    server = build_server(SessionStore())
    catalog = _tool_callable(server, "load_bank")(path=str(BANK))
    jd = _tool_callable(server, "set_job_description")(raw_text=sample_jd_text)

    project = catalog["projects"][0]
    assert project["kind"] == "project", "catalog still reports singular"

    result = _tool_callable(server, "tailor_resume")(
        job_id=jd["job_id"],
        selection={
            "sections": [
                {
                    "kind": "project",  # the spelling the catalog handed back
                    "entries": [
                        {
                            "entry_id": project["entry_id"],
                            "bullets": [
                                {"bullet_id": project["bullets"][0]["bullet_id"]}
                            ],
                        }
                    ],
                }
            ]
        },
    )
    assert result["ok"] is True
    assert any(s["kind"] == "projects" and s["entries"] for s in result["sections"])


def test_analyze_fit_accepts_an_entry_id_for_degree_requirements(sample_jd_text):
    """Education entries have no bullets, so a 'CS degree' requirement had
    nothing legitimate to cite. entry_id is now a valid citation."""
    server = build_server(SessionStore())
    catalog = _tool_callable(server, "load_bank")(path=str(BANK))
    jd = _tool_callable(server, "set_job_description")(raw_text=sample_jd_text)
    edu_id = catalog["education"][0]["entry_id"]

    fit = _tool_callable(server, "analyze_fit")(
        job_id=jd["job_id"],
        requirements=[
            {
                "text": "BS in Computer Science",
                "category": "must_have",
                "verdict": "covered",
                "supporting_bullet_ids": [edu_id],
            }
        ],
    )
    assert fit["corrections"] == []
    assert len(fit["covered"]) == 1
    assert fit["coverage_ratio"] == 1.0


def test_set_job_description_reads_a_large_file_itself(tmp_path):
    """A 175KB scrape blew past the agent's own file-read cap, forcing it to
    chunk the file by hand. The server absorbs that work now."""
    big = tmp_path / "posting.html"
    filler = "<div>" + ("boilerplate locale data " * 4000) + "</div>"
    big.write_text(
        f"<html><body>{filler}<p>We need Python and Go.</p></body></html>",
        encoding="utf-8",
    )
    assert big.stat().st_size > 90_000

    server = build_server(SessionStore())
    info = _tool_callable(server, "set_job_description")(raw_text_path=str(big))
    assert info["raw_char_count"] > 90_000
    assert "We need Python and Go." in info["cleaned_text"]


def test_set_job_description_requires_some_input():
    server = build_server(SessionStore())
    with pytest.raises(ValueError, match="raw_text"):
        _tool_callable(server, "set_job_description")()


def test_catalog_flags_bullet_less_entries_as_citable():
    """Two live runs reported a false 'CS degree' gap because the education
    entry has no bullets and nothing said its entry_id was citable."""
    server = build_server(SessionStore())
    catalog = _tool_callable(server, "load_bank")(path=str(BANK))
    edu = catalog["education"][0]
    assert edu["bullets"] == []
    assert "note" in edu and "entry_id" in edu["note"]
