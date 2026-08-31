from __future__ import annotations

import json
from pathlib import Path

from resume_agent.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
BANK = REPO_ROOT / "docs" / "example-experience-bank.yaml"
TEMPLATE = REPO_ROOT / "templates" / "resume.template.tex"


def _write_jd(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "jd.txt"
    p.write_text(text, encoding="utf-8")
    return p


def _write_selection(tmp_path: Path, selection: dict) -> Path:
    p = tmp_path / "selection.json"
    p.write_text(json.dumps(selection), encoding="utf-8")
    return p


def test_cli_catalog_lists_bullet_ids(capsys):
    rc = main(["catalog", "--bank", str(BANK)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["totals"]["bullets"] > 0
    assert payload["experiences"][0]["bullets"][0]["bullet_id"]


def test_cli_tailor_json(tmp_path, capsys, sample_jd_text, full_selection):
    jd_path = _write_jd(tmp_path, sample_jd_text)
    sel_path = _write_selection(tmp_path, full_selection)
    rc = main(
        [
            "tailor",
            "--bank", str(BANK),
            "--jd", str(jd_path),
            "--selection", str(sel_path),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["draft_id"].startswith("draft-")


def test_cli_tailor_and_export(tmp_path, sample_jd_text, full_selection):
    jd_path = _write_jd(tmp_path, sample_jd_text)
    sel_path = _write_selection(tmp_path, full_selection)
    out_dir = tmp_path / "out"
    rc = main(
        [
            "tailor",
            "--bank", str(BANK),
            "--jd", str(jd_path),
            "--selection", str(sel_path),
            "--export",
            "--out", str(out_dir),
            "--template", str(TEMPLATE),
        ]
    )
    assert rc == 0
    tex_files = list(out_dir.glob("*.tex"))
    assert tex_files, "expected at least one .tex file"
    tex_body = tex_files[0].read_text(encoding="utf-8")
    assert "\\begin{document}" in tex_body


def test_cli_rejects_bad_selection(tmp_path, sample_jd_text, capsys):
    jd_path = _write_jd(tmp_path, sample_jd_text)
    sel_path = _write_selection(
        tmp_path,
        {"sections": [{"kind": "experience", "entries": [{"entry_id": "nope"}]}]},
    )
    rc = main(
        [
            "tailor",
            "--bank", str(BANK),
            "--jd", str(jd_path),
            "--selection", str(sel_path),
        ]
    )
    assert rc == 2
    assert "nope" in capsys.readouterr().err
