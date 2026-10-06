"""Page-change watcher for program pages listed in config/programs.yaml.

Many of the best opportunities (ISTA ISTernship, ETH SSRF, summer schools)
are not job postings but a single web page that gets updated once a year.
For each page we:

1. download it,
2. keep only the visible text (no scripts, styles or menus),
3. hash that text,
4. compare with the hash from the previous run.

Each program always appears in the report; when its page changed since the
last run it gets a "page changed" note so you know to go and look.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from datetime import date
from typing import Any

from ..browser import render
from ..db import page_hash_changed
from ..http import get_text
from ..models import NO_DEADLINE, Opportunity
from ..textutil import find_deadline, html_to_text
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "programs"

# Pages with less text than this are probably built by JavaScript in the
# browser; their hash would never change, so we report them as a problem.
MIN_TEXT_CHARS = 200

# Lines that change on every visit and would cause false "changed" alerts.
_NOISE = re.compile(
    r"(©|copyright|cookie|all rights reserved|\b\d{1,2}:\d{2}\b|last updated|páginas? \d+|skip to)",
    re.I,
)


def main_text(page_html: str) -> str:
    """The page's readable text, preferring the <main> element if it has real content."""
    match = re.search(r"<main\b.*?</main>", page_html, re.S | re.I)
    text = _visible_text(match.group(0)) if match else ""
    if len(text) < MIN_TEXT_CHARS:
        text = _visible_text(page_html)  # no useful <main>: use the whole page
    return text


def _visible_text(fragment: str) -> str:
    # Navigation, header and footer change often but say nothing about the program.
    body = re.sub(r"<(nav|header|footer|form)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    lines = [line for line in html_to_text(body).splitlines() if not _NOISE.search(line)]
    return "\n".join(lines)


def page_text(program: dict[str, Any]) -> str:
    """Visible text of a program page. `render: true` in programs.yaml means
    the page is built by JavaScript, so we open it in a headless browser."""
    if program.get("render"):
        return render(program["url"]).text
    return main_text(get_text(program["url"]))


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_opportunity(program: dict[str, Any], text: str, changed: bool, last_changed: str) -> Opportunity:
    """One Opportunity per watched page, with the labels you set in programs.yaml."""
    note = f"page changed on {last_changed}" if changed else f"page unchanged since {last_changed}"
    preset = {key: program[key] for key in ("area", "season", "regions", "warnings") if program.get(key)}
    return Opportunity(
        title=program["name"],
        org=program.get("org", ""),
        source=NAME,
        url=program["url"],
        location=program.get("location", ""),
        deadline=find_deadline(text) or NO_DEADLINE,
        description=text[:6000],
        hints=["student"] if program.get("student", True) else ["unsure-student"],
        preset=preset,
        note=note + (f" · {program['notes']}" if program.get("notes") else ""),
    )


def fetch(config: dict[str, Any], conn: sqlite3.Connection | None = None, today: str | None = None) -> SourceResult:
    """Check every page. Needs the database connection to compare hashes."""
    result = SourceResult()
    today = today or date.today().isoformat()
    for program in config.get("programs", []) or []:
        result.checked += 1
        try:
            text = page_text(program)
            if len(text) < MIN_TEXT_CHARS:
                raise ValueError("page has almost no text (blocked, or built by JavaScript: try render: true)")
            changed, last_changed = (False, today)
            if conn is not None:
                changed, last_changed = page_hash_changed(conn, program["url"], content_hash(text), today)
            result.items.append(build_opportunity(program, text, changed, last_changed))
        except Exception as error:  # noqa: BLE001
            log.warning("Program page %s failed: %s", program.get("name"), error)
            result.errors.append(f"{program.get('name')}: {error}")
    return result
