"""Adversarial tests: the model must not be able to fabricate into a PDF.

These encode the security property of the whole design. Selection and
wording are the agent's job; facts are not. Each test is a thing a real LLM
does when it wants the candidate to look better, and each must be refused.

They run against the public example bank so they work in CI.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from resume_agent.mcp_server import build_server
from resume_agent.state import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[1]
BANK = REPO_ROOT / "docs" / "example-experience-bank.yaml"
TEMPLATE = REPO_ROOT / "templates" / "resume.template.tex"


def _tool(server, name):
    return next(t for t in server._tool_manager.list_tools() if t.name == name).fn


@pytest.fixture()
def agent(sample_jd_text):
    """A loaded server plus handles into the bank, as an agent would have."""
    server = build_server(SessionStore())
    catalog = _tool(server, "load_bank")(path=str(BANK))
    jd = _tool(server, "set_job_description")(raw_text=sample_jd_text)
    entry = catalog["experiences"][0]
    return {
        "server": server,
        "job_id": jd["job_id"],
        "entry_id": entry["entry_id"],
        "bullet_id": entry["bullets"][0]["bullet_id"],
        "bullet_text": entry["bullets"][0]["text"],
        "fit": _tool(server, "analyze_fit"),
        "tailor": _tool(server, "tailor_resume"),
        "export": _tool(server, "export_draft"),
    }


def _experience_bullet(result):
    section = next(s for s in result["sections"] if s["kind"] == "experience")
    return section["entries"][0]["bullets"][0]


def _rewrite(agent, text):
    return agent["tailor"](
        job_id=agent["job_id"],
        selection={
            "sections": [
                {
                    "kind": "experience",
                    "entries": [
                        {
                            "entry_id": agent["entry_id"],
                            "bullets": [
                                {"bullet_id": agent["bullet_id"], "rewritten_text": text}
                            ],
                        }
                    ],
                }
            ]
        },
    )


# --- coverage inflation ----------------------------------------------------


def test_uncited_coverage_claim_is_downgraded(agent):
    fit = agent["fit"](
        job_id=agent["job_id"],
        requirements=[
            {"text": "Swift / iOS", "category": "must_have", "verdict": "covered"},
            {"text": "Kotlin", "category": "must_have", "verdict": "covered"},
        ],
    )
    assert fit["covered"] == []
    assert fit["coverage_ratio"] == 0.0
    assert len(fit["must_have_gaps"]) == 2
    assert len(fit["corrections"]) == 2


def test_fabricated_bullet_id_citation_is_stripped(agent):
    fit = agent["fit"](
        job_id=agent["job_id"],
        requirements=[
            {
                "text": "Swift",
                "verdict": "covered",
                "supporting_bullet_ids": ["bul-ios-app-2024"],
            }
        ],
    )
    assert fit["coverage_ratio"] == 0.0
    assert fit["gaps"][0]["supporting_bullet_ids"] == []


# --- content fabrication ---------------------------------------------------


def test_wholly_invented_bullet_is_unsupported_and_unexportable(agent, tmp_path):
    result = _rewrite(
        agent, "Shipped a SwiftUI iOS app to 50,000 users on the App Store."
    )
    assert _experience_bullet(result)["label"] == "unsupported"
    assert result["export_blockers"]
    export = agent["export"](
        draft_id=result["draft_id"],
        output_dir=str(tmp_path),
        template_path=str(TEMPLATE),
    )
    assert export["exported"] is False


def test_inflating_an_existing_metric_is_caught(agent):
    """The subtlest and most damaging edit: a real bullet with a bigger number."""
    original = agent["bullet_text"]
    inflated = original.replace("50+", "500+").replace("10+", "100+")
    if inflated == original:
        inflated = original.rstrip(".") + " for 500+ customers."
    result = _rewrite(agent, inflated)
    assert _experience_bullet(result)["label"] == "unsupported"
    assert result["export_blockers"]


def test_accept_inferred_cannot_launder_an_unsupported_bullet(agent):
    result = agent["tailor"](
        job_id=agent["job_id"],
        selection={
            "accept_inferred": True,
            "sections": [
                {
                    "kind": "experience",
                    "entries": [
                        {
                            "entry_id": agent["entry_id"],
                            "bullets": [
                                {
                                    "bullet_id": agent["bullet_id"],
                                    "rewritten_text": "Led iOS engineering at Apple for 3 years.",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    )
    assert result["export_blockers"], "accept_inferred must not approve 'unsupported'"


def test_invented_skill_is_rejected(agent):
    result = agent["tailor"](
        job_id=agent["job_id"],
        selection={
            "sections": [],
            "skills": [{"group": "Mobile", "skills": ["Swift", "SwiftUI"]}],
        },
    )
    assert result["ok"] is False
    assert "Swift" in result["error"]


# --- control: honest use must remain easy ----------------------------------


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")
def test_honest_selection_exports_a_complete_one_page_resume(agent, tmp_path):
    result = agent["tailor"](
        job_id=agent["job_id"],
        selection={
            "sections": [
                {
                    "kind": "experience",
                    "entries": [
                        {
                            "entry_id": agent["entry_id"],
                            "bullets": [{"bullet_id": agent["bullet_id"]}],
                        }
                    ],
                }
            ],
            "rationale": "honest",
        },
    )
    assert result["ok"] is True
    assert result["export_blockers"] == []

    kinds = {s["kind"] for s in result["sections"]}
    assert "education" in kinds, "Education must be present even when unselected"
    skills = next(s for s in result["sections"] if s["kind"] == "skills")
    assert skills["skill_groups"], "Skills must never be empty"

    export = agent["export"](
        draft_id=result["draft_id"],
        output_dir=str(tmp_path),
        template_path=str(TEMPLATE),
    )
    assert export["exported"] is True
    assert export["page_count"] == 1
    assert Path(export["pdf_path"]).exists()
