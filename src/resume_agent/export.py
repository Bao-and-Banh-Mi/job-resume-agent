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

import re
import shutil
import subprocess
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from .latex_renderer import render_draft
from .models import Draft

_MAX_TRIM_ITERATIONS = 15

# Below this fraction of page height, a one-page resume reads as thin rather
# than concise. Not a hard failure -- an honest sparse resume is still the
# right output for a weak-fit posting -- but the caller must be told.
_SPARSE_FILL_THRESHOLD = 0.75


class ExportBlocked(Exception):
    """Raised when the export gate refuses a draft outright (not page-fit)."""


@dataclass(frozen=True)
class ExportResult:
    tex_path: str
    tex: str
    exported: bool = True
    page_count: int | None = None
    pdf_path: str = ""
    # Fraction of page height covered by content. ~0.90+ is a full page;
    # below _SPARSE_FILL_THRESHOLD the caller is warned the resume looks thin.
    fill_ratio: float | None = None
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


def _measure_fill_ratio(pdf_path: Path) -> float | None:
    """Fraction of the page height between the top margin and the last content.

    A one-page cap alone lets a thin draft ship as a half-empty page, which
    reads to a recruiter as a thin candidate. We measure the real ink extent
    so callers can react.

    Method: decompress the content streams and track vertical text positions.
    pdfTeX emits absolute ``1 0 0 1 x y cm`` for rules and relative ``dx dy
    Td`` for text runs within a ``BT``/``ET`` block, so we accumulate ``Td``
    offsets per block and take the lowest resulting baseline. Returns
    ``None`` if the PDF cannot be parsed rather than guessing.
    """
    try:
        data = pdf_path.read_bytes()
    except OSError:
        return None

    box = re.search(
        rb"/MediaBox\s*\[\s*[\d.-]+\s+[\d.-]+\s+[\d.-]+\s+([\d.-]+)", data
    )
    if not box:
        return None
    height = float(box.group(1))
    if height <= 0:
        return None

    ys: list[float] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            stream = zlib.decompress(m.group(1))
        except zlib.error:
            continue
        cursor: float | None = None
        for tok in re.finditer(
            rb"BT|ET|([-\d.]+)\s+([-\d.]+)\s+Td|1 0 0 1 ([-\d.]+) ([-\d.]+) cm",
            stream,
        ):
            raw = tok.group(0)
            if raw in (b"BT", b"ET"):
                cursor = None
            elif tok.group(4) is not None:  # absolute placement (rules)
                ys.append(float(tok.group(4)))
            else:  # relative text placement
                dy = float(tok.group(2))
                cursor = dy if cursor is None else cursor + dy
                ys.append(cursor)

    on_page = [y for y in ys if 0.0 < y < height]
    if not on_page:
        return None

    top, bottom = max(on_page), min(on_page)
    return round((top - bottom) / height, 3)


def _iter_page_type_matches(data: bytes):
    for m in re.finditer(rb"/Type\s*/Page(?![a-zA-Z])", data):
        yield m


def _all_bullets(draft: Draft):
    """Yield (section, entry, bullet) triples for every bullet in the draft."""
    for section in draft.sections:
        for entry in section.entries:
            for bullet in entry.bullets:
                yield section, entry, bullet


# Section trim order, least protected first. Education is absent because it
# is structural and header-only; it is never trimmed.
_TRIM_PRIORITY = ["leadership", "projects", "experience"]

# Never reduce an entry below this many bullets while any entry anywhere
# still has more. An entry shown with a single bullet still demonstrates the
# role; an entry deleted outright loses the role entirely, which is a much
# bigger loss than one bullet from a longer entry.
_MIN_BULLETS_PER_ENTRY = 1


def _drop_lowest_scoring_bullet(draft: Draft) -> tuple[Draft, str | None]:
    """Remove the single least-important bullet from ``draft``.

    Trimming is *depth-first across all sections*, not section-by-section.
    An earlier version drained the lowest-priority section to zero before
    touching the next one, which deleted the entire Leadership and Projects
    sections while three Experience entries sat untouched at six bullets
    each. That is the wrong trade: a six-bullet entry can spare its tail
    without loss, while a deleted entry costs the reader a whole role.

    Selection order:

    1. Consider every entry whose bullet count is above the current maximum
       floor -- i.e. trim the *longest* entries first, wherever they live.
    2. Break ties by section priority (leadership before projects before
       experience), then by entry order, so the choice is deterministic.
    3. Within the chosen entry, drop the last bullet: the agent lists
       bullets strongest-first, so the tail is what it valued least.

    Entries are only reduced to zero (and pruned) once every remaining entry
    is already at ``_MIN_BULLETS_PER_ENTRY``, and only in priority order.
    Returns ``(new_draft, dropped_bullet_id)``; the id is ``None`` when
    nothing can be dropped.
    """
    new_draft = draft.model_copy(deep=True)

    trimmable: list[tuple[int, int, int, object, object]] = []
    for section in new_draft.sections:
        if section.kind == "skills" or section.kind == "education":
            continue
        try:
            priority = _TRIM_PRIORITY.index(section.kind)
        except ValueError:
            priority = len(_TRIM_PRIORITY)
        for order, entry in enumerate(section.entries):
            if entry.bullets:
                trimmable.append(
                    (len(entry.bullets), priority, order, section, entry)
                )

    if not trimmable:
        return draft, None

    deepest = max(t[0] for t in trimmable)

    if deepest > _MIN_BULLETS_PER_ENTRY:
        # Phase 1: shave the longest entries, wherever they are. Ties go to
        # the least-protected section.
        pool = [t for t in trimmable if t[0] == deepest]
        pool.sort(key=lambda t: (-t[1], t[2]))
        _, _, _, section, entry = pool[0]
    else:
        # Phase 2: every entry is at the floor, so further trimming must
        # sacrifice whole entries. Protect the last entry of each section:
        # a section that loses its final entry disappears from the resume
        # entirely, and a missing Experience section is far worse than a
        # missing bullet. Only when every section is down to a single entry
        # do we allow a section to be dissolved, least-protected first.
        multi_entry = [t for t in trimmable if len(t[3].entries) > 1]
        pool = multi_entry or trimmable
        pool.sort(key=lambda t: (-t[1], t[2]))
        _, _, _, section, entry = pool[0]

    victim = entry.bullets[-1]
    dropped_id = victim.draft_bullet_id
    entry.bullets = entry.bullets[:-1]

    if not entry.bullets:
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
        # The cap must scale with the draft: a fixed 15 was silently too low
        # for a large bank, so a 36-bullet draft exhausted the budget at two
        # pages and exported nothing. Every iteration removes exactly one
        # bullet, so allowing one pass per bullet (plus headroom) makes the
        # one-page guarantee hold for any draft that can fit at all.
        total_bullets = sum(
            len(e.bullets) for s in draft.sections for e in s.entries
        )
        max_iterations = max(_MAX_TRIM_ITERATIONS, total_bullets + 2)

        for iteration in range(max_iterations + 1):
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
                fill = _measure_fill_ratio(pdf_dest)
                if fill is not None and fill < _SPARSE_FILL_THRESHOLD:
                    warnings.append(
                        f"resume fills only {fill:.0%} of the page; "
                        f"{1 - fill:.0%} is empty. This reads as a thin "
                        "candidate. Include more genuinely-relevant bank "
                        "content, or reconsider whether this posting is a fit."
                    )
                return ExportResult(
                    tex_path=str(tex_path),
                    tex=tex,
                    exported=True,
                    page_count=page_count,
                    pdf_path=str(pdf_dest),
                    fill_ratio=fill,
                    dropped_bullet_ids=dropped,
                    warnings=warnings,
                )

            if iteration == max_iterations:
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
