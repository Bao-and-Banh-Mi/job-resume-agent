"""Export-gate logic shared by the MCP tool and the tests.

Beyond the evidence/approval gate, this module enforces a *real* one-page
constraint: it compiles the rendered ``.tex`` with ``pdflatex`` in a sandbox
directory, checks the resulting page count, and if the draft overflows,
trims the least-important trailing bullet (pure removal -- wording is
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
    pdf_path: str = ""
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


# Trim order: the agent ranked content by *listing* it, so the last bullet of
# the least-important section is the safest thing to lose. Education is never
# trimmed -- it is structural, and it is header-only anyway.
_TRIM_PRIORITY = ["leadership", "projects", "experience"]


def _drop_lowest_scoring_bullet(draft: Draft) -> tuple[Draft, str | None]:
    """Remove the single least-important bullet from ``draft``.

    Selection order, least important first:

    1. Sections in ``_TRIM_PRIORITY`` order (leadership before experience).
    2. Within a section, the entry with the *most* bullets, so trimming
       levels entries out rather than gutting one of them.
    3. Within that entry, the last bullet -- the agent listed bullets in
       priority order, so the tail is what it considered least relevant.

    An entry is never reduced below one bullet while any other entry still
    has two, and entries emptied by trimming are pruned. Returns
    ``(new_draft, dropped_bullet_id)``; the id is ``None`` when nothing can
    be dropped.
    """
    new_draft = draft.model_copy(deep=True)

    by_kind = {s.kind: s for s in new_draft.sections}

    for kind in _TRIM_PRIORITY:
        section = by_kind.get(kind)
        if section is None or not section.entries:
            continue

        # Prefer trimming an entry that still has more than one bullet.
        multi = [e for e in section.entries if len(e.bullets) > 1]
        pool = multi or [e for e in section.entries if e.bullets]
        if not pool:
            continue

        target = max(pool, key=lambda e: (len(e.bullets), e.source_entry_id))
        victim = target.bullets[-1]
        dropped_id = victim.draft_bullet_id
        target.bullets = target.bullets[:-1]

        # Prune entries that lost their last bullet, except in Education
        # where a header-only entry is still meaningful content.
        if section.kind != "education":
            section.entries = [
                e for e in section.entries if e.bullets or e.kind == "education"
            ]
        return new_draft, dropped_id

    return draft, None


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
                # Keep the PDF we just verified, rather than recompiling
                # outside the sandbox and hoping for the same result.
                pdf_src = iter_dir / "draft.pdf"
                pdf_dest = output_dir / f"{draft.draft_id}.pdf"
                shutil.copyfile(pdf_src, pdf_dest)
                if dropped:
                    warnings.append(
                        f"trimmed {len(dropped)} lowest-priority bullet(s) to fit one page"
                    )
                return ExportResult(
                    tex_path=str(tex_path),
                    tex=tex,
                    exported=True,
                    page_count=page_count,
                    pdf_path=str(pdf_dest),
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
