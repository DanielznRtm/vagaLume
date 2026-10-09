"""Gupy (portal.gupy.io): the main Brazilian job portal for estágio.

The portal's search page calls a JSON route that we call directly:
  https://portal.gupy.io/api/job-search/jobs?type=...&limit=100&offset=N
`type` takes Gupy's job types, comma-separated (repeating `type=` is
ignored). We ask for internships, summer internships (estágio de férias)
and trainee programs, newest first, 100 per page, until a page comes back
short. That is about 2,700 roles in ~27 requests. (Jovem aprendiz, for
14–24-year-olds outside university, is left out; add
"vacancy_type_apprentice" to gupy_types in config/search.yaml to include it.)

Note: the response's pagination.total is unreliable for limit > 10, so we
stop on a short page instead of trusting it.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..labels import student_level
from ..models import NO_DEADLINE, Opportunity
from ..textutil import html_to_text, iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "gupy"
API_URL = "https://portal.gupy.io/api/job-search/jobs?"
PAGE_SIZE = 100  # the maximum Gupy accepts
MAX_PAGES = 60   # safety stop: 6,000 roles
DEFAULT_TYPES = ["vacancy_type_internship", "vacancy_type_summer", "vacancy_type_trainee"]

# Gupy's own job types. Internship-like ones are clearly for students;
# trainee might be (some are for recent graduates).
STUDENT_TYPES = {"vacancy_type_internship", "vacancy_type_apprentice", "vacancy_type_summer"}
MAYBE_TYPES = {"vacancy_type_trainee", "vacancy_type_talent_pool"}


def to_opportunity(job: dict[str, Any]) -> Opportunity | None:
    """One Gupy job -> Opportunity, or None when it isn't a student role at all."""
    title = str(job.get("name", "")).strip()
    job_type = str(job.get("type", ""))
    level = student_level(title)
    if job_type in STUDENT_TYPES or level == "yes":
        hints = ["student"]
    elif job_type in MAYBE_TYPES or level == "unsure":
        hints = ["unsure-student"]
    else:
        return None  # e.g. "Analista Pleno" that matched a search text only
    place = ", ".join(part for part in (job.get("city"), job.get("state")) if part)
    workplace = str(job.get("workplaceType") or "")
    location = f"{place}, Brazil" if place else "Brazil"
    return Opportunity(
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


def parse(payload: dict[str, Any]) -> list[Opportunity]:
    """One page of the JSON API."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("unexpected answer from the Gupy API (no 'data' list)")
    return [opp for job in payload["data"] if (opp := to_opportunity(job))]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    seen: set[str] = set()
    types = config.get("search", {}).get("gupy_types") or DEFAULT_TYPES
    for page in range(MAX_PAGES):
        result.checked += 1
        params = {"type": ",".join(types), "limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
        try:
            payload = get_json(API_URL + urlencode(params), headers={"Accept": "application/json"})
            items = parse(payload)
        except Exception as error:  # noqa: BLE001
            log.warning("Gupy page %d failed: %s", page, error)
            result.errors.append(f"offset {page * PAGE_SIZE}: {error}")
            break
        for opp in items:
            if opp.id not in seen:
                seen.add(opp.id)
                result.items.append(opp)
        if len(payload["data"]) < PAGE_SIZE:
            break  # the last page
    return result
