"""Microsoft careers (apply.careers.microsoft.com).

The search page calls a JSON endpoint ("pcsx/search") that returns 10 jobs
per request. We call it directly, page by page.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..labels import is_student_candidate
from ..models import Opportunity
from ..textutil import iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "microsoft"
BASE = "https://apply.careers.microsoft.com"
SEARCH_URL = BASE + "/api/pcsx/search?"
PAGE_SIZE = 10  # fixed by Microsoft
MAX_PAGES = 30


def parse(data: dict[str, Any]) -> tuple[list[Opportunity], int]:
    """Return (student-level jobs on this page, total number of results)."""
    block = data.get("data") or {}
    items: list[Opportunity] = []
    for job in block.get("positions") or []:
        title = str(job.get("name", "")).strip().rstrip(",")
        if not is_student_candidate(title):
            continue  # the search also returns e.g. "Internal Audit Manager"
        # "locations" spells countries out ("India, Karnataka, Bangalore"); we flip
        # each to "Bangalore, Karnataka, India" so it reads like other sources.
        full = [", ".join(reversed([part.strip() for part in place.split(",")])) for place in job.get("locations") or []]
        locations = full or job.get("standardizedLocations") or []
        items.append(
            Opportunity(
                title=title,
                org="Microsoft",
                source=NAME,
                url=BASE + str(job["positionUrl"]),
                location=" / ".join(locations),
                remote=str(job.get("workLocationOption", "")).lower() == "remote",
                posted_date=iso_date(job.get("postedTs")),
                description=str(job.get("department") or ""),
            )
        )
    return items, int(block.get("count") or 0)


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    seen: set[str] = set()
    for query in config.get("search", {}).get("microsoft_queries", ["intern"]) or []:
        for page in range(MAX_PAGES):
            result.checked += 1
            params = {"domain": "microsoft.com", "query": query, "location": "", "start": page * PAGE_SIZE, "sort_by": "relevance"}
            try:
                items, total = parse(get_json(SEARCH_URL + urlencode(params), headers={"Accept": "application/json"}))
            except Exception as error:  # noqa: BLE001
                log.warning("Microsoft query %r failed: %s", query, error)
                result.errors.append(f"query {query!r} start {page * PAGE_SIZE}: {error}")
                break
            for opp in items:
                if opp.id not in seen:
                    seen.add(opp.id)
                    result.items.append(opp)
            if (page + 1) * PAGE_SIZE >= total:
                break
    return result
