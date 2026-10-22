"""Numbers the README and the guide quote ("45 fontes"), kept up to date by the daily run.

A number followed by a marker, like `45<!--n:sources-->`, is replaced with today's count. GitHub
doesn't show the marker. The site counts its sources itself, from data.json.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

FILES = ["README.md", ".github/README.en.md", ".github/GUIDE.md"]
MARKED = re.compile(r"\d[\d.,]*(?=<!--n:(\w+)-->)")
# The company pages the README names: "Greenhouse, Lever, Ashby, SmartRecruiters and Workday boards of N companies".
BOARDS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday_brazil", "workday_global"]


def counts(config: dict[str, Any], sources: int) -> dict[str, int]:
    programs = config.get("programs") or []
    companies = config.get("companies") or {}
    return {
        "sources": sources,
        "programs": len(programs),
        "programs_brazil": sum(1 for p in programs if "Brazil" in (p.get("regions") or [])),
        "boards": sum(len(companies.get(name) or []) for name in BOARDS),
    }


def fill(text: str, values: dict[str, int]) -> str:
    """Each marked number replaced with its count; a marker with an unknown name is left as it is."""
    return MARKED.sub(lambda m: str(values[m[1]]) if m[1] in values else m[0], text)


def update(root: Path, values: dict[str, int]) -> list[Path]:
    """Rewrite the files whose numbers changed; returns them."""
    changed = []
    for name in FILES:
        path = root / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new = fill(text, values)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(path)
    return changed
