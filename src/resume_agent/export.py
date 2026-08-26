"""Export-gate logic shared by the MCP tool and the tests.

Keeping this out of ``mcp_server`` lets the tests exercise the exact gate
without spinning up the MCP transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .latex_renderer import render_draft
from .models import Draft


class ExportBlocked(Exception):
    """Raised when the export gate refuses a draft."""


@dataclass(frozen=True)
class ExportResult:
    tex_path: str
    tex: str


def check_export_gate(draft: Draft) -> list[str]:
    """Return a list of gate-blocking reasons. Empty list means safe to export."""
    reasons: list[str] = []
    for section in draft.sections:
        for entry in section.entries:
            for b in entry.bullets:
                label = b.classification.label
                if label == "unsupported":
                    reasons.append(
                        f"bullet {b.draft_bullet_id} is unsupported "
                        f"({b.classification.reason})"
                    )
                elif label == "inferred" and not b.approved:
                    reasons.append(
                        f"bullet {b.draft_bullet_id} is inferred and unapproved"
                    )
    return reasons


def export_draft(
    draft: Draft, *, output_dir: Path, template_path: Path
) -> ExportResult:
    reasons = check_export_gate(draft)
    if reasons:
        raise ExportBlocked("; ".join(reasons))
    output_dir.mkdir(parents=True, exist_ok=True)
    tex = render_draft(draft, template_path)
    tex_path = output_dir / f"{draft.draft_id}.tex"
    tex_path.write_text(tex, encoding="utf-8")
    return ExportResult(tex_path=str(tex_path), tex=tex)
