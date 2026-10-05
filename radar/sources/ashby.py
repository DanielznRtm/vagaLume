"""Ashby public job-board API.

API docs: https://developers.ashbyhq.com/docs/public-job-posting-api
"""

from __future__ import annotations

from typing import Any

from ..http import get_json
from ..labels import is_student_candidate, student_level
from ..models import Opportunity
from ..textutil import iso_date
from . import SourceResult
from .ats import fetch_boards

NAME = "ashby"
URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _location(job: dict[str, Any]) -> str:
    names = [str(job.get("location") or "")]
    names += [str(extra.get("location", "")) for extra in job.get("secondaryLocations") or []]
    country = (((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry")) or ""
    text = " / ".join(name for name in names if name)
    if country and country not in text:
        text = f"{text}, {country}" if text else country
    return text


def parse(data: dict[str, Any], org: str) -> list[Opportunity]:
    items: list[Opportunity] = []
    for job in data.get("jobs", []):
        if job.get("isListed") is False:
            continue
        title = job.get("title", "").strip()
        flagged_student = str(job.get("employmentType", "")).lower() == "intern"
        if not (flagged_student or is_student_candidate(title)):
            continue
        if flagged_student and student_level(title) != "yes":
            title = f"{title} (Intern)"
        location = _location(job)
        items.append(
            Opportunity(
                title=title,
                org=org,
                source=NAME,
                url=job["jobUrl"],
                location=location,
                remote=bool(job.get("isRemote")) or job.get("workplaceType") == "Remote",
                posted_date=iso_date(job.get("publishedAt")),
                description=job.get("descriptionPlain", "") or "",
                hints=["student"] if flagged_student else [],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    companies = config.get("companies", {}).get("ashby", []) or []
    return fetch_boards(companies, lambda slug: get_json(URL.format(slug=slug)), parse, NAME)
