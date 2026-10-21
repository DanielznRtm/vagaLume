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
import time
from datetime import date
from typing import Any

import requests

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
    the page is built by JavaScript, so we open it in a headless browser.

    Some sites behind Cloudflare (Embraer's, for one) don't answer plain
    requests from GitHub's servers (no answer at all, or a 403/429/5xx) but do
    answer a real browser, so then we try once more in the browser.
    """
    if program.get("render"):
        return render(program["url"]).text
    try:
        return main_text(get_text(program["url"]))
    except (requests.Timeout, requests.ConnectionError) as error:
        reason = error
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else 0
        if status not in (403, 429) and status < 500:
            raise  # e.g. 404: the page is gone, a browser won't help
        reason = error
    log.info("Program page %s: plain request failed (%s), trying the browser", program.get("name"), reason)
    try:
        # The same text extraction as a plain request, so the page hash doesn't
        # change (and raise a false "page changed") just because we used the browser.
        return main_text(render(program["url"]).html)
    except Exception as browser_error:  # noqa: BLE001
        raise RuntimeError(f"{reason}; the browser failed too: {browser_error}") from browser_error


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def application_months(window: str) -> list[int]:
    """The `applications` field of programs.yaml as months, in order.

    "Nov–Jan" -> [11, 12, 1]; "Feb, Aug" (two rounds) -> [2, 8]; "Mar" -> [3]; "" -> [].
    """
    months: list[int] = []
    for part in re.split(r"[,;/]| and ", window.lower()):
        ends = [MONTHS.index(m[:3]) + 1 for m in re.findall(r"[a-z]{3,}", part) if m[:3] in MONTHS]
        if not ends:
            continue
        month, last = ends[0], ends[-1]
        while True:
            if month not in months:
                months.append(month)
            if month == last:
                break
            month = month % 12 + 1
    return months


def content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# The page says this year's applications are over ("The deadline for applications has passed",
# "Inscrições encerradas"). The program stays in the Programs tab, marked closed, for next year.
CLOSED = re.compile(
    r"deadline for (?:the )?applications? (?:has|have) (?:now )?passed|applications? (?:are|is|have|has been) (?:now )?closed"
    r"|applications? (?:period|window|round) (?:is|has) (?:now )?(?:closed|ended)|(?:call|registration) (?:is|has) (?:now )?closed"
    r"|(?:we are|we're) no longer accepting applications|applications? closed for (?:the )?20\d\d"
    r"|inscri[çc][õo]es (?:est[ãa]o |foram )?encerradas|per[íi]odo de inscri[çc][õo]es (?:est[áa] )?encerrado"
    r"|inscripciones (?:est[áa]n )?cerradas",
    re.I,
)
# ...unless something on the page is still open: a page listing several programs ("Estágio Clariant:
# Inscrições encerradas", next to "Programa X: Inscreva-se") is not closed.
STILL_OPEN = re.compile(
    r"applications? (?:are|is) (?:now )?open\b|now accepting applications|\bapply now\b|apply by\b|accepting applications"
    r"|inscri[çc][õo]es (?:est[ãa]o )?abertas|inscreva-se|fazer (?:a )?inscri[çc][ãa]o|candidate-se|inscri[çc][õo]es at[ée]",
    re.I,
)
CLOSED_NOTE = "applications closed"


def build_opportunity(program: dict[str, Any], text: str, changed: bool, last_changed: str) -> Opportunity:
    """One Opportunity per watched page, with the labels you set in programs.yaml."""
    note = f"page changed on {last_changed}" if changed else f"page unchanged since {last_changed}"
    if CLOSED.search(text) and not STILL_OPEN.search(text):
        note = f"{CLOSED_NOTE} · {note}"
    preset = {key: program[key] for key in ("area", "season", "regions", "warnings", "levels") if program.get(key)}
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


# A university server that times out or answers 503 is often back a few minutes later
# (DESY, MPIA and KAIST on 2026-10-21): pages that didn't answer get one more try at the end.
RETRY_PAUSE_SECONDS = 60


def _check(program: dict[str, Any], conn: sqlite3.Connection | None, today: str) -> Opportunity:
    text = page_text(program)
    if len(text) < MIN_TEXT_CHARS:
        raise ValueError("page has almost no text (blocked, or built by JavaScript: try render: true)")
    changed, last_changed = (False, today)
    if conn is not None:
        changed, last_changed = page_hash_changed(conn, program["url"], content_hash(text), today)
    return build_opportunity(program, text, changed, last_changed)


def fetch(config: dict[str, Any], conn: sqlite3.Connection | None = None, today: str | None = None) -> SourceResult:
    """Check every page. Needs the database connection to compare hashes."""
    result = SourceResult()
    today = today or date.today().isoformat()
    failed: list[dict[str, Any]] = []
    for program in config.get("programs", []) or []:
        result.checked += 1
        try:
            result.items.append(_check(program, conn, today))
        except ValueError as error:  # the page answered, with almost no text: trying again won't help
            log.warning("Program page %s failed: %s", program.get("name"), error)
            result.errors.append(f"{program.get('name')}: {error}")
        except Exception as error:  # noqa: BLE001
            log.info("Program page %s failed, trying again later: %s", program.get("name"), error)
            failed.append(program)
    if failed:
        time.sleep(RETRY_PAUSE_SECONDS)
    for program in failed:
        result.checked += 1
        try:
            result.items.append(_check(program, conn, today))
        except Exception as error:  # noqa: BLE001
            log.warning("Program page %s failed: %s", program.get("name"), error)
            result.errors.append(f"{program.get('name')}: {error}")
    return result
