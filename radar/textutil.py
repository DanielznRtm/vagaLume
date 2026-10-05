"""Small text helpers: HTML -> plain text, date parsing, deadline finding."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timezone

_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|svg|template)\b.*?</\1>", re.S | re.I)
_SPACES = re.compile(r"\s+")


def html_to_text(raw: str) -> str:
    """Turn an HTML snippet into readable plain text."""
    if not raw:
        return ""
    no_code = _SCRIPT_STYLE.sub(" ", raw)
    # Keep line structure for block tags so sentences don't run together.
    no_code = re.sub(r"<(br|/p|/li|/h\d|/div|/tr)\b[^>]*>", "\n", no_code, flags=re.I)
    text = html.unescape(_TAG.sub(" ", no_code))
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def iso_date(value: object) -> str:
    """Best-effort conversion of many date formats to "YYYY-MM-DD".

    Accepts ISO strings ("2026-10-02T17:56:27Z"), unix timestamps in seconds
    or milliseconds, and English dates like "September 15, 2026".
    Returns "" if nothing sensible can be parsed.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
    text = str(value).strip()
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    parsed = parse_english_date(text)
    return parsed.isoformat() if parsed else ""


_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan", "janeiro"),
            ("february", "feb", "fevereiro", "fev"),
            ("march", "mar", "março", "marco"),
            ("april", "apr", "abril", "abr"),
            ("may", "maio", "mai"),
            ("june", "jun", "junho"),
            ("july", "jul", "julho"),
            ("august", "aug", "agosto", "ago"),
            ("september", "sep", "sept", "setembro", "set"),
            ("october", "oct", "outubro", "out"),
            ("november", "nov", "novembro"),
            ("december", "dec", "dezembro", "dez"),
        ],
        start=1,
    )
    for name in names
}
_MONTH_WORD = "|".join(sorted(_MONTHS, key=len, reverse=True))
# "October 9, 2026" / "Oct 9 2026"
_MDY = re.compile(rf"\b({_MONTH_WORD})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)
# "9 October 2026" / "9 de outubro de 2026"
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:de\s+)?({_MONTH_WORD})\.?,?\s+(?:de\s+)?(\d{{4}})\b", re.I)
# "15/12/2026" (Brazilian/European day-first order)
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def parse_english_date(text: str) -> date | None:
    """Find the first date written in words (English or Portuguese)."""
    for pattern, order in ((_MDY, "mdy"), (_DMY, "dmy")):
        match = pattern.search(text)
        if not match:
            continue
        if order == "mdy":
            month_word, day, year = match.groups()
        else:
            day, month_word, year = match.groups()
        try:
            return date(int(year), _MONTHS[month_word.lower()], int(day))
        except (KeyError, ValueError):
            continue
    match = _NUMERIC.search(text)
    if match:
        day, month, year = (int(x) for x in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


# Words that usually appear right before an application deadline.
_DEADLINE_CUES = re.compile(
    r"(deadline|apply by|applications? (?:close|closes|due|are due|will close)|"
    r"application before|submit (?:your application|applications) by|no later than|"
    r"prazo|inscri\w+ até|inscri\w+ (?:vão|vai) até|candidaturas até)",
    re.I,
)


def find_deadline(text: str) -> str:
    """Look for "deadline: <date>" style sentences. Returns ISO date or ""."""
    if not text:
        return ""
    for cue in _DEADLINE_CUES.finditer(text):
        window = text[cue.start() : cue.end() + 80]
        found = parse_english_date(window)
        if found:
            return found.isoformat()
    return ""
