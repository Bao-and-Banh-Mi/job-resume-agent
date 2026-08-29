"""Export-gate logic shared by the MCP tool and the tests.

Beyond the evidence/approval gate, this module enforces a *real* one-page
constraint: it compiles the rendered ``.tex`` with ``pdflatex`` in a sandbox
directory, checks the resulting page count, and if the draft overflows,
trims the single lowest ``match_score`` bullet (pure removal -- wording is
never touched) and recompiles. This repeats until the draft fits one page,
bullets are exhausted, or an iteration cap is hit.

Keeping this out of ``mcp_server`` lets the tests exercise the exact gate
without spinning up the MCP transport.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .latex_renderer import render_draft
from .models import Draft

_MAX_TRIM_ITERATIONS = 15


class ExportBlocked(Exception):
    """Raised when the export gate refuses a draft outright (not page-fit)."""


@dataclass(frozen=True)
class ExportResult:
    tex_path: str
    tex: str
    exported: bool = True
    page_count: int | None = None
    dropped_bullet_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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


def _pdflatex_available() -> bool:
    return shutil.which("pdflatex") is not None


def _compile_page_count(tex: str, workdir: Path) -> tuple[int | None, str]:
    """Compile ``tex`` in ``workdir`` with pdflatex; return (page_count, log_tail).

    Returns ``page_count=None`` when pdflatex is unavailable or compilation
    failed outright (the caller decides how to degrade).
    """
    if not _pdflatex_available():
        return None, "pdflatex not found on PATH"

    tex_path = workdir / "draft.tex"
    tex_path.write_text(tex, encoding="utf-8")

    try:
        proc = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-no-shell-escape",
                "-output-directory",
                ".",
                tex_path.name,
            ],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"pdflatex invocation failed: {exc}"

    pdf_path = workdir / "draft.pdf"
    log_tail = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-2000:]
    if proc.returncode != 0 or not pdf_path.exists():
        return None, f"pdflatex exited {proc.returncode}: {log_tail}"

    page_count = _count_pdf_pages(pdf_path)
    return page_count, log_tail


def _count_pdf_pages(pdf_path: Path) -> int | None:
    """Return the page count of ``pdf_path``, preferring ``pdfinfo``."""
    if shutil.which("pdfinfo"):
        try:
            proc = subprocess.run(
                ["pdfinfo", str(pdf_path)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            for line in proc.stdout.splitlines():
                if line.lower().startswith("pages:"):
                    return int(line.split(":", 1)[1].strip())
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
    # Fallback: count distinct page objects via a regex over the raw PDF
    # bytes. Not exact for every producer, but pdfTeX output is consistent.
    try:
        data = pdf_path.read_bytes()
        count = len(list(_iter_page_type_matches(data)))
        return count or None
    except OSError:
        return None


def _iter_page_type_matches(data: bytes):
    import re

    for m in re.finditer(rb"/Type\s*/Page(?![a-zA-Z])", data):
        yield m


def _all_bullets(draft: Draft):
    """Yield (section, entry, bullet) triples for every bullet in the draft."""
    for section in draft.sections:
        for entry in section.entries:
            for bullet in entry.bullets:
                yield section, entry, bullet


def _drop_lowest_scoring_bullet(draft: Draft) -> tuple[Draft, str | None]:
    """Return a copy of ``draft`` with its single lowest-``match_score`` bullet
    removed. Empty entries left behind are pruned; sections left with no
    entries/skill_groups are pruned by the renderer, not here (renderer
    already skips empty sections).

    Returns ``(new_draft, dropped_bullet_id)``; ``dropped_bullet_id`` is
    ``None`` if there was nothing left to drop.
    """
    candidates = list(_all_bullets(draft))
    if not candidates:
        return draft, None

    # Lowest score first; ties broken by draft_bullet_id for determinism.
    _, _, victim = min(
        candidates, key=lambda t: (t[2].match_score, t[2].draft_bullet_id)
    )
    dropped_id = victim.draft_bullet_id

    new_draft = draft.model_copy(deep=True)
    for section in new_draft.sections:
        for entry in section.entries:
            entry.bullets = [
                b for b in entry.bullets if b.draft_bullet_id != dropped_id
            ]
        # Drop entries that lost their last bullet (no content left to show).
        section.entries = [e for e in section.entries if e.bullets]
    return new_draft, dropped_id


def export_draft(
    draft: Draft, *, output_dir: Path, template_path: Path
) -> ExportResult:
    reasons = check_export_gate(draft)
    if reasons:
        raise ExportBlocked("; ".join(reasons))

    output_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    dropped: list[str] = []
    current = draft
    page_count: int | None = None

    if not _pdflatex_available():
        warnings.append(
            "pdflatex not found on PATH; skipping one-page compile check. "
            "Install a TeX distribution (e.g. MiKTeX/TeX Live) to enforce it."
        )
        tex = render_draft(current, template_path)
        tex_path = output_dir / f"{current.draft_id}.tex"
        tex_path.write_text(tex, encoding="utf-8")
        return ExportResult(
            tex_path=str(tex_path),
            tex=tex,
            exported=True,
            page_count=None,
            dropped_bullet_ids=dropped,
            warnings=warnings,
        )

    with tempfile.TemporaryDirectory(prefix="resume-agent-pdflatex-") as tmp:
        tmp_dir = Path(tmp)
        for iteration in range(_MAX_TRIM_ITERATIONS + 1):
            tex = render_draft(current, template_path)
            iter_dir = tmp_dir / f"iter-{iteration}"
            iter_dir.mkdir(parents=True, exist_ok=True)
            page_count, log_tail = _compile_page_count(tex, iter_dir)

            if page_count is None:
                # Compilation itself failed -- do not ship anything.
                raise ExportBlocked(
                    f"pdflatex compilation failed on iteration {iteration}: {log_tail}"
                )

            if page_count <= 1:
                tex_path = output_dir / f"{draft.draft_id}.tex"
                tex_path.write_text(tex, encoding="utf-8")
                if dropped:
                    warnings.append(
                        f"trimmed {len(dropped)} lowest-scoring bullet(s) to fit one page"
                    )
                return ExportResult(
                    tex_path=str(tex_path),
                    tex=tex,
                    exported=True,
                    page_count=page_count,
                    dropped_bullet_ids=dropped,
                    warnings=warnings,
                )

            if iteration == _MAX_TRIM_ITERATIONS:
                break

            new_draft, dropped_id = _drop_lowest_scoring_bullet(current)
            if dropped_id is None:
                break
            dropped.append(dropped_id)
            current = new_draft

    return ExportResult(
        tex_path="",
        tex="",
        exported=False,
        page_count=page_count,
        dropped_bullet_ids=dropped,
        warnings=[
            f"could not fit one page even after trimming {len(dropped)} bullet(s); "
            "not exporting an overflowing PDF"
        ],
    )
