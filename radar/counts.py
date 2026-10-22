"""Numbers the README and the guide quote ("45 fontes", "cerca de 31.000 vagas"), kept up to date
by the daily run.

A number followed by a marker, like `45<!--n:sources-->`, is replaced with today's count. GitHub
doesn't show the marker. The site counts its sources itself, from data.json.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# file -> its thousands separator ("31.000" in Portuguese, "31,000" in English)
FILES = {"README.md": ".", ".github/README.en.md": ",", ".github/GUIDE.md": ","}
MARKED = re.compile(r"\d[\d.,]*(?=<!--n:(\w+)-->)")
# The company pages the README names: "Greenhouse, Lever, Ashby, SmartRecruiters and Workday boards of N companies".
BOARDS = ["greenhouse", "lever", "ashby", "smartrecruiters", "workday_brazil", "workday_global"]


def counts(config: dict[str, Any], sources: int, open_items: list[Any] | None = None) -> dict[str, int]:
    """The counts by name. With the open roles (anything with `regions`), also how many there are:
    "open" rounded to the thousand ("cerca de 31.000"), the Brazil/abroad split rounded down
    ("mais de 13.000"). Abroad counts every open role not in Brazil, remote ones included."""
    programs = config.get("programs") or []
    companies = config.get("companies") or {}
    values = {
        "sources": sources,
        "programs": len(programs),
        "programs_brazil": sum(1 for p in programs if "Brazil" in (p.get("regions") or [])),
        "boards": sum(len(companies.get(name) or []) for name in BOARDS),
    }
    if open_items:
        brazil = sum(1 for o in open_items if "Brazil" in o.regions)
        abroad = sum(1 for o in open_items if "Brazil" not in o.regions and set(o.regions) - {"unknown"})
        values |= {"open": round(len(open_items), -3), "open_brazil": brazil // 1000 * 1000, "open_abroad": abroad // 1000 * 1000}
    return values


def fill(text: str, values: dict[str, int], separator: str = ",") -> str:
    """Each marked number replaced with its count; a marker with an unknown name is left as it is."""
    return MARKED.sub(lambda m: f"{values[m[1]]:,}".replace(",", separator) if m[1] in values else m[0], text)


def update(root: Path, values: dict[str, int]) -> list[Path]:
    """Rewrite the files whose numbers changed; returns them."""
    changed = []
    for name, separator in FILES.items():
        path = root / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new = fill(text, values, separator)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(path)
    return changed
