"""Curated internship lists on GitHub (SimplifyJobs and similar).

These repos keep a big table in their README. Some write it as an HTML
<table>, others as a Markdown pipe table, so we support both. Rows whose
company cell is "↳" belong to the company of the row above. Rows marked
with 🔒 are closed and skipped.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from ..http import get_text
from ..models import Opportunity
from ..textutil import html_to_text, iso_date, parse_english_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "github_lists"

# Emoji flags used by the lists, mapped to hints for the labeller.
FLAG_HINTS = {
    "🛂": "no-sponsorship",
    "🇺🇸": "us-citizen",
    "🎓": "advanced-degree",
}
EMOJI_TO_STRIP = ["🛂", "🇺🇸", "🎓", "🔥", "🔒", "⭐", "💰"]

# Section headings -> area to fall back on when the title says nothing.
HEADING_AREAS = [
    ("quant", "quant"),
    ("hardware", "hardware"),
    ("machine learning", "ML"),
    ("data science", "data"),
    ("software", "SWE"),
]

_HREF = re.compile(r'href="([^"]+)"')


def _cell_text(cell: str) -> str:
    """Plain text of a table cell; <br> / <details> lists become ' / '."""
    cell = re.sub(r"<summary>.*?</summary>", "", cell, flags=re.S)
    text = html_to_text(cell.replace("<br>", "\n").replace("<br/>", "\n"))
    return " / ".join(part.strip() for part in text.splitlines() if part.strip())


def _clean_title(title: str) -> str:
    for emoji in EMOJI_TO_STRIP:
        title = title.replace(emoji, "")
    return re.sub(r"\s+", " ", title).strip()


def _posted_date(age: str, today: date) -> str:
    """'0d' / '12d' / '3mo' (Simplify) or 'Aug 21' (other lists) -> ISO date."""
    age = age.strip()
    match = re.fullmatch(r"(\d+)\s*d", age)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    match = re.fullmatch(r"(\d+)\s*mo", age)
    if match:
        return (today - timedelta(days=30 * int(match.group(1)))).isoformat()
    parsed = parse_english_date(f"{age} {today.year}") if re.fullmatch(r"[A-Za-z]{3,9}\.? \d{1,2}", age) else None
    if parsed:
        if parsed > today:  # "Dec 30" seen in January belongs to last year
            parsed = parsed.replace(year=today.year - 1)
        return parsed.isoformat()
    return iso_date(age)


def _rows(markdown: str) -> list[tuple[str, list[str], list[str]]]:
    """Yield (current_heading, header_names, raw_cells) for every table row."""
    rows: list[tuple[str, list[str], list[str]]] = []
    heading = ""
    header: list[str] = []
    for block in re.split(r"(?=^#{2,3} )|(?=<table\b)", markdown, flags=re.M):
        first_line = block.splitlines()[0] if block else ""
        if first_line.startswith("#"):
            heading = first_line.lstrip("# ").strip()
        if re.search(r"<table\b", block):
            header = [html_to_text(h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", block, re.S)]
            for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", block, re.S):
                cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
                if cells:
                    rows.append((heading, header, cells))
        else:
            for line in block.splitlines():
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if cells and cells[0].lower() == "company":
                    header = cells
                elif cells and not set(cells[0]) <= set("-: "):
                    rows.append((heading, header, cells))
    return rows


def parse(
    markdown: str,
    list_name: str,
    kind: str = "internship",
    today: date | None = None,
    season: str | None = None,
) -> list[Opportunity]:
    """Parse one README. `kind` is "internship" or "new-grad".

    `season` (from search.yaml) is used for lists that are all one season,
    e.g. the Summer list, whose titles rarely say "summer".
    """
    today = today or date.today()
    items: list[Opportunity] = []
    last_company = ""
    for heading, header, cells in _rows(markdown):
        columns = {name.lower(): i for i, name in enumerate(header)}

        def cell(*names: str) -> str:
            for name in names:
                for column, index in columns.items():
                    if column.startswith(name) and index < len(cells):
                        return cells[index]
            return ""

        company = _cell_text(cell("company"))
        if company in ("↳", ""):
            company = last_company
        last_company = company
        role_raw = cell("role")
        apply_cell = cell("application", "link")
        whole_row = " ".join(cells)
        if "🔒" in whole_row:
            continue  # closed
        links = _HREF.findall(apply_cell)
        if not links or not company:
            continue
        hints = ["new-grad"] if kind == "new-grad" else ["student"]
        hints += [hint for emoji, hint in FLAG_HINTS.items() if emoji in whole_row]
        terms = _cell_text(cell("terms"))
        if terms:
            hints.append(terms)  # e.g. "Fall 2026" helps the season rule
        for key, area in HEADING_AREAS:
            if key in heading.lower():
                hints.append(f"area:{area}")
                break
        location = _cell_text(cell("location"))
        items.append(
            Opportunity(
                title=_clean_title(_cell_text(role_raw)) + (f" ({terms})" if terms else ""),
                org=_clean_title(company),
                source=NAME,
                url=links[0].replace("&amp;", "&"),
                location=location,
                remote="remote" in location.lower(),
                posted_date=_posted_date(_cell_text(cell("age", "date")), today),
                hints=hints,
                preset={"season": season} if season and not terms else {},
                note=f"from {list_name}",
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for entry in config.get("search", {}).get("github_lists", []) or []:
        result.checked += 1
        try:
            markdown = get_text(entry["url"])
            found = parse(markdown, entry["name"], entry.get("kind", "internship"), season=entry.get("season"))
            if not found:
                raise ValueError("parsed 0 rows - the README format may have changed")
            result.items.extend(found)
        except Exception as error:  # noqa: BLE001
            log.warning("GitHub list %s failed: %s", entry.get("name"), error)
            result.errors.append(f"{entry.get('name')}: {error}")
    return result
