"""Load the YAML files in config/."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def _load(name: str) -> Any:
    path = CONFIG_DIR / name
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def merge_discovered(companies: dict[str, Any], discovered: dict[str, Any] | None) -> dict[str, Any]:
    """companies.yaml plus the boards radar/discover.py found that it doesn't list yet."""
    merged = dict(companies)
    for platform, rows in (discovered or {}).items():
        mine = list(companies.get(platform) or [])
        known = {str(c["slug"]).lower() for c in mine}
        merged[platform] = mine + [r for r in rows or [] if str(r["slug"]).lower() not in known]
    return merged


def load_config() -> dict[str, Any]:
    """Everything the sources need, in one dictionary."""
    return {
        # The companies you list, plus the ones found by radar/discover.py (config/discovered.yaml).
        "companies": merge_discovered(_load("companies.yaml") or {}, _load("discovered.yaml")),
        "programs": (_load("programs.yaml") or {}).get("programs", []),
        "search": _load("search.yaml") or {},
        "status": _load("status.yaml") or {},
        "digest": _load("digest.yaml") or {},
    }
