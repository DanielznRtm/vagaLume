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


def load_config() -> dict[str, Any]:
    """Everything the sources need, in one dictionary."""
    return {
        "companies": _load("companies.yaml") or {},
        "programs": (_load("programs.yaml") or {}).get("programs", []),
        "search": _load("search.yaml") or {},
        "status": _load("status.yaml") or {},
    }
