"""Gupy (portal.gupy.io): the main Brazilian job portal for estágio.

The portal's search page calls a JSON route that we call directly:
  https://portal.gupy.io/api/job-search/jobs?type=...&limit=100&offset=N
`type` takes Gupy's job types, comma-separated (repeating `type=` is
ignored). We ask for internships, summer internships (estágio de férias)
and trainee programs, newest first, 100 per page, until a page comes back
short. That is about 2,700 roles in ~27 requests. (Jovem aprendiz, for
14–24-year-olds outside university, is left out; add
"vacancy_type_apprentice" to gupy_types in config/search.yaml to include it.)

Some companies file estágios under other job types: Itaú's "Programa de
Estágio Corporativo" is a talent pool, and hundreds of estágios are typed as
regular ("effective") jobs. So we also search those types for "estágio" and
"estagiário/a" in the title, keeping only titles that are clearly for
students (about 600 more roles).

Note: the response's pagination.total is unreliable for limit > 10, so we
stop on a short page instead of trusting it.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..labels import student_level
from ..places import ALSO_ABROAD, city_state
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
# Other job types, searched by title only (see the module docstring).
OTHER_TYPES = ["vacancy_type_talent_pool", "vacancy_type_effective", "vacancy_type_temporary"]
TITLE_SEARCHES = ["estágio", "estagiário", "estagiária"]  # the search ignores accents


def _location(city: str, state: str) -> str:
    """Gupy has no country field. Brazilian jobs always have a state; a city
    without one is abroad (Gupy also hosts companies in Peru and Chile), unless
    it is a Brazilian city whose state was left out ("Goiânia")."""
    if state:
        return f"{city}, {state}, Brazil" if city else f"{state}, Brazil"
    if not city:
        return "Brazil"
    if city_state(city) and city.lower() not in ALSO_ABROAD:
        return f"{city}, Brazil"
    return city


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
    city, state = str(job.get("city") or "").strip(), str(job.get("state") or "").strip()
    workplace = str(job.get("workplaceType") or "")
    location = _location(city, state)
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


def _search(result: SourceResult, seen: set[str], params: dict[str, Any], students_only: bool) -> None:
    """Every page of one search, newest first, until a short page."""
    for page in range(MAX_PAGES):
        result.checked += 1
        query = {**params, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
        try:
            payload = get_json(API_URL + urlencode(query), headers={"Accept": "application/json"})
            items = parse(payload)
        except Exception as error:  # noqa: BLE001
            log.warning("Gupy %s page %d failed: %s", params, page, error)
            result.errors.append(f"{params.get('jobName') or 'types'} offset {page * PAGE_SIZE}: {error}")
            return
        for opp in items:
            if students_only and "student" not in opp.hints:
                continue  # a talent pool or regular job without "estágio" in a student sense
            if opp.id not in seen:
                seen.add(opp.id)
                result.items.append(opp)
        if len(payload["data"]) < PAGE_SIZE:
            return  # the last page


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    seen: set[str] = set()
    types = config.get("search", {}).get("gupy_types") or DEFAULT_TYPES
    _search(result, seen, {"type": ",".join(types)}, students_only=False)
    for name in TITLE_SEARCHES:
        _search(result, seen, {"type": ",".join(OTHER_TYPES), "jobName": name}, students_only=True)
    return result
