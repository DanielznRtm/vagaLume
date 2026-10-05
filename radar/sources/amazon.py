"""Amazon Jobs (amazon.jobs) via the JSON endpoint its own search page uses."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..labels import is_student_candidate
from ..models import Opportunity
from ..textutil import html_to_text, iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "amazon"
SEARCH_URL = "https://www.amazon.jobs/en/search.json?"
PAGE_SIZE = 100
MAX_PAGES = 10


def parse(data: dict[str, Any]) -> list[Opportunity]:
    items: list[Opportunity] = []
    for job in data.get("jobs", []):
        title = str(job.get("title", "")).strip()
        university = str(job.get("business_category", "")) == "university"
        if not (university or is_student_candidate(title)):
            continue
        description = "\n".join(
            html_to_text(str(job.get(key) or ""))
            for key in ("description", "basic_qualifications", "preferred_qualifications")
        )
        location = str(job.get("normalized_location") or job.get("location") or "")
        items.append(
            Opportunity(
                title=title,
                org=str(job.get("company_name") or "Amazon"),
                source=NAME,
                url="https://www.amazon.jobs" + str(job["job_path"]),
                location=location,
                remote="virtual" in location.lower() or "remote" in location.lower(),
                posted_date=iso_date(job.get("posted_date")),
                description=description,
                hints=["student"] if university else [],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    seen: set[str] = set()
    for query in config.get("search", {}).get("amazon_queries", ["intern"]) or []:
        for page in range(MAX_PAGES):
            result.checked += 1
            params = {"base_query": query, "result_limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "sort": "recent"}
            try:
                data = get_json(SEARCH_URL + urlencode(params))
            except Exception as error:  # noqa: BLE001
                log.warning("Amazon query %r failed: %s", query, error)
                result.errors.append(f"query {query!r} offset {page * PAGE_SIZE}: {error}")
                break
            for opp in parse(data):
                if opp.id not in seen:
                    seen.add(opp.id)
                    result.items.append(opp)
            if (page + 1) * PAGE_SIZE >= int(data.get("hits", 0)):
                break
    return result
