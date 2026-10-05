"""Gupy (portal.gupy.io): the main Brazilian job portal for estágio.

Gupy has no public JSON API any more, but its search page is rendered on
the server and embeds the results as JSON in a <script id="__NEXT_DATA__">
tag. We read that JSON. Limitation: each search page only holds the 12
newest results, so we run several searches (configured in
config/search.yaml) to cover more ground.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

from ..http import get_text
from ..labels import student_level
from ..models import NO_DEADLINE, Opportunity
from ..textutil import html_to_text, iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "gupy"
SEARCH_URL = "https://portal.gupy.io/job-search/term={term}"

# Gupy's own job types. Internship-like ones are clearly for students;
# trainee / talent pool might be.
STUDENT_TYPES = {"vacancy_type_internship", "vacancy_type_apprentice", "vacancy_type_summer"}
MAYBE_TYPES = {"vacancy_type_trainee", "vacancy_type_talent_pool"}

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def extract_jobs(page_html: str) -> list[dict[str, Any]]:
    """Pull the job list out of the page's embedded JSON."""
    match = _NEXT_DATA.search(page_html)
    if not match:
        raise ValueError("no __NEXT_DATA__ block found - Gupy may have changed its page")
    data = json.loads(match.group(1))
    return data["props"]["pageProps"].get("initialJobList", {}).get("data", []) or []


def parse(page_html: str) -> list[Opportunity]:
    items: list[Opportunity] = []
    for job in extract_jobs(page_html):
        title = str(job.get("name", "")).strip()
        job_type = str(job.get("type", ""))
        level = student_level(title)
        if job_type in STUDENT_TYPES or level == "yes":
            hints = ["student"]
        elif job_type in MAYBE_TYPES or level == "unsure":
            hints = ["unsure-student"]
        else:
            continue  # e.g. "Analista Pleno" that matched the search text only
        place = ", ".join(part for part in (job.get("city"), job.get("state")) if part)
        workplace = str(job.get("workplaceType") or "")
        location = f"{place}, Brazil" if place else "Brazil"
        items.append(
            Opportunity(
                title=title,
                org=str(job.get("careerPageName") or "?"),
                source=NAME,
                url=str(job["jobUrl"]),
                location=location + (f" ({workplace})" if workplace else ""),
                remote=workplace == "remote",
                posted_date=iso_date(job.get("publishedDate")),
                deadline=iso_date(job.get("applicationDeadline")) or NO_DEADLINE,
                description=html_to_text(str(job.get("description") or "")),
                hints=hints,
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    seen: set[str] = set()
    for term in config.get("search", {}).get("gupy_terms", []) or []:
        result.checked += 1
        try:
            for opp in parse(get_text(SEARCH_URL.format(term=quote(term)))):
                if opp.id not in seen:
                    seen.add(opp.id)
                    result.items.append(opp)
        except Exception as error:  # noqa: BLE001
            log.warning("Gupy search %r failed: %s", term, error)
            result.errors.append(f"term {term!r}: {error}")
    return result
