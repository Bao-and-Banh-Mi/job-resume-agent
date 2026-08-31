"""Small command-line surface around the tailoring pipeline.

Three subcommands:

- ``serve``   -- run the MCP server over stdio (the primary interface).
- ``catalog`` -- dump the bank catalog as JSON, i.e. exactly what an agent
                 sees from ``load_bank``. Useful for building a selection by
                 hand and for eyeballing bullet_ids.
- ``tailor``  -- apply a selection JSON to a bank + JD and optionally export.

There is deliberately no "tailor this JD for me" CLI mode: choosing what
belongs on the resume is the language model's job, and this package does not
call one. The CLI exists so the *enforcement* half can be exercised without
an MCP client, which is what the tests rely on.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .bank import load_bank
from .catalog import bank_catalog
from .export import ExportBlocked, check_export_gate, export_draft
from .jd_clean import clean_jd_text
from .mcp_server import _default_template_path, preview_draft, run_stdio
from .models import JobDescription, ResumeSelection
from .state import SessionStore
from .tailor import SelectionError, tailor_from_selection


def _cmd_serve(_: argparse.Namespace) -> int:
    run_stdio()
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    bank_path = Path(args.bank)
    if not bank_path.exists():
        print(f"error: bank not found: {bank_path}", file=sys.stderr)
        return 2
    print(json.dumps(bank_catalog(load_bank(bank_path)), indent=2))
    return 0


def _cmd_tailor(args: argparse.Namespace) -> int:
    bank_path = Path(args.bank)
    jd_path = Path(args.jd)
    sel_path = Path(args.selection)
    for label, path in (
        ("bank", bank_path),
        ("JD file", jd_path),
        ("selection", sel_path),
    ):
        if not path.exists():
            print(f"error: {label} not found: {path}", file=sys.stderr)
            return 2

    bank = load_bank(bank_path)
    jd_text = clean_jd_text(jd_path.read_text(encoding="utf-8", errors="ignore"))
    selection = ResumeSelection.model_validate(
        json.loads(sel_path.read_text(encoding="utf-8"))
    )

    store = SessionStore()
    store.set_bank(bank, str(bank_path))
    jd = JobDescription(
        job_id=store.new_job_id(jd_text),
        captured_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        raw_text=jd_text,
    )
    store.put_job(jd)

    try:
        draft = tailor_from_selection(bank, jd, selection)
    except SelectionError as exc:
        print(f"error: invalid selection: {exc}", file=sys.stderr)
        return 2
    store.put_draft(draft)

    if args.json:
        print(json.dumps(preview_draft(draft), indent=2))
    else:
        _print_human(draft)

    if args.export:
        out_dir = Path(args.out or Path.cwd() / "out")
        template = Path(args.template) if args.template else _default_template_path()
        gate = check_export_gate(draft)
        if gate:
            print("\nEXPORT BLOCKED:", file=sys.stderr)
            for reason in gate:
                print(f"  - {reason}", file=sys.stderr)
            return 3
        try:
            result = export_draft(draft, output_dir=out_dir, template_path=template)
        except ExportBlocked as exc:
            print(f"\nEXPORT BLOCKED: {exc}", file=sys.stderr)
            return 3
        if not result.exported:
            print("\nEXPORT BLOCKED (one-page fit):", file=sys.stderr)
            for w in result.warnings:
                print(f"  - {w}", file=sys.stderr)
            return 3
        print(f"\nwrote {result.tex_path} (page_count={result.page_count})")
        if result.pdf_path:
            print(f"wrote {result.pdf_path}")
        if result.dropped_bullet_ids:
            print(
                f"trimmed {len(result.dropped_bullet_ids)} bullet(s) to fit one page: "
                + ", ".join(result.dropped_bullet_ids)
            )
        for w in result.warnings:
            print(f"warning: {w}")
    return 0


def _print_human(draft) -> None:  # type: ignore[no-untyped-def]
    print(f"draft_id: {draft.draft_id}")
    print(f"job_id:   {draft.job_id}")
    if draft.gaps:
        print("gaps:")
        for g in draft.gaps:
            print(f"  - {g.requirement_text}")
    for section in draft.sections:
        print(f"\n[{section.kind}]")
        for entry in section.entries:
            print(f"  * {entry.title} - {entry.organization}")
            for b in entry.bullets:
                print(f"      - ({b.classification.label}) {b.rewritten_text}")
        for group in section.skill_groups:
            names = ", ".join(s.name for s in group.skills)
            print(f"  * {group.group}: {names}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resume-agent",
        description="Evidence-grounded resume tailoring.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the MCP server over stdio.")
    p_serve.set_defaults(func=_cmd_serve)

    p_catalog = sub.add_parser(
        "catalog", help="Print the bank catalog JSON (what load_bank returns)."
    )
    p_catalog.add_argument("--bank", required=True, help="Path to experience bank YAML.")
    p_catalog.set_defaults(func=_cmd_catalog)

    p_tailor = sub.add_parser(
        "tailor",
        help="Apply a selection JSON to a bank + JD; optionally export.",
    )
    p_tailor.add_argument("--bank", required=True, help="Path to experience bank YAML.")
    p_tailor.add_argument("--jd", required=True, help="Path to JD text file.")
    p_tailor.add_argument(
        "--selection", required=True, help="Path to a ResumeSelection JSON file."
    )
    p_tailor.add_argument(
        "--export",
        action="store_true",
        help="Also render/compile to --out (subject to the export gate).",
    )
    p_tailor.add_argument("--out", help="Output directory for exports (default: ./out).")
    p_tailor.add_argument(
        "--template",
        help="LaTeX template path (default: templates/resume.template.tex).",
    )
    p_tailor.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON preview instead of the human-readable summary.",
    )
    p_tailor.set_defaults(func=_cmd_tailor)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
