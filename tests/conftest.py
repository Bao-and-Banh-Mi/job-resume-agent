from __future__ import annotations

from pathlib import Path

import pytest

from resume_agent.bank import load_bank
from resume_agent.models import ExperienceBank

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_BANK = REPO_ROOT / "docs" / "example-experience-bank.yaml"
TEMPLATE_PATH = REPO_ROOT / "templates" / "resume.template.tex"


@pytest.fixture(scope="session")
def example_bank() -> ExperienceBank:
    return load_bank(EXAMPLE_BANK)


@pytest.fixture(scope="session")
def template_path() -> Path:
    return TEMPLATE_PATH


@pytest.fixture()
def sample_jd_text() -> str:
    return (
        "We are hiring an AI Engineer to build multi-agent systems on top of RAG "
        "pipelines. You will design MCP servers, integrate with Slack and Microsoft "
        "Graph APIs, and ship evaluations for tool-call accuracy. Required: Python, "
        "PyTorch, FastAPI, Docker, and experience with LLMs and agents. Nice to have: "
        "quantum computing, PennyLane, and federated learning with Flower."
    )


@pytest.fixture()
def full_selection(example_bank: ExperienceBank) -> dict:
    """A selection covering every entry and bullet in the example bank."""
    sections = []
    for kind, entries in (
        ("experience", example_bank.experiences),
        ("projects", example_bank.projects),
        ("leadership", example_bank.leadership),
        ("education", example_bank.education),
    ):
        if not entries:
            continue
        sections.append(
            {
                "kind": kind,
                "entries": [
                    {
                        "entry_id": e.entry_id,
                        "bullets": [{"bullet_id": b.bullet_id} for b in e.bullets],
                    }
                    for e in entries
                ],
            }
        )
    return {"sections": sections, "rationale": "test: everything"}
