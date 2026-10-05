"""Google Careers (best effort).

Google has no public jobs API. Its results page, however, embeds the job
list as a JavaScript data blob (`AF_initDataCallback({key: 'ds:1', ...})`).
We read that blob. The blob is a list of positional arrays, so if Google
changes the layout this parser will break: the source health table in the
report will then show an error, and the Google student page in
programs.yaml still acts as a backup.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

from ..http import get_text
from ..models import NO_DEADLINE, Opportunity
from ..textutil import find_deadline, html_to_text, iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "google"
SEARCH_URL = (
    "https://www.google.com/about/careers/applications/jobs/results"
    "?q={query}&target_level=INTERN_AND_APPRENTICE&page={page}"
)
JOB_URL = "https://www.google.com/about/careers/applications/jobs/results/{job_id}"
MAX_PAGES = 15

_BLOB = re.compile(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(.*?), sideChannel: \{\}\}\);", re.S)


def _text(field: Any) -> str:
    """Fields like the description are stored as [None, "<html>"]."""
    if isinstance(field, list) and len(field) > 1 and isinstance(field[1], str):
        return html_to_text(field[1])
    return ""


def parse(page_html: str) -> tuple[list[Opportunity], int]:
    """Return (items on this page, total number of results)."""
    match = _BLOB.search(page_html)
    if not match:
        raise ValueError("job data blob not found - Google may have changed its page")
    data = json.loads(match.group(1))
    jobs, total = data[0] or [], (data[2] if len(data) > 2 and isinstance(data[2], int) else 0)
    items: list[Opportunity] = []
    for job in jobs:
        job_id, title = str(job[0]), str(job[1])
        locations = [str(place[0]) for place in (job[9] or []) if place]
        description = "\n".join(_text(job[i]) for i in (3, 4, 10, 19) if i < len(job))
        apply_note = _text(job[15]) if len(job) > 15 else ""
        posted = job[12][0] if len(job) > 12 and isinstance(job[12], list) and job[12] else None
        items.append(
            Opportunity(
                title=title,
                org=str(job[7] or "Google"),
                source=NAME,
                url=JOB_URL.format(job_id=job_id),
                location=" / ".join(locations),
                remote=any("remote" in place.lower() for place in locations),
                posted_date=iso_date(posted),
                deadline=find_deadline(apply_note) or NO_DEADLINE,
                description=f"{apply_note}\n{description}",
                hints=["student"],  # we only search the intern/apprentice level
            )
        )
    return items, total


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for query in config.get("search", {}).get("google_queries", ["intern"]) or []:
        for page in range(1, MAX_PAGES + 1):
            result.checked += 1
            try:
                items, total = parse(get_text(SEARCH_URL.format(query=quote(query), page=page)))
            except Exception as error:  # noqa: BLE001
                log.warning("Google query %r page %d failed: %s", query, page, error)
                result.errors.append(f"query {query!r} page {page}: {error}")
                break
            result.items.extend(items)
            if not items or page * 20 >= total:
                break
    return result
