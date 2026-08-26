"""YAML-file-backed experience bank.

The bank format is the one documented at `docs/example-experience-bank.yaml`.
This module is intentionally read-mostly: the POC does not mutate the bank
on disk. Writes are relegated to a future persistence layer (see the
data-model doc's `bank.version` monotonic-mutation contract).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import ExperienceBank


def load_bank(path: str | Path) -> ExperienceBank:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"experience bank not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"experience bank at {p} did not parse to a mapping")
    return ExperienceBank.model_validate(data)
