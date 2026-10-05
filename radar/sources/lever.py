"""Lever public postings API.

API docs: https://github.com/lever/postings-api
"""

from __future__ import annotations

from typing import Any

from ..http import get_json
from ..labels import is_student_candidate, student_level
from ..models import Opportunity
from ..textutil import html_to_text, iso_date
from . import SourceResult
from .ats import fetch_boards

NAME = "lever"
URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


def _description(job: dict[str, Any]) -> str:
    parts = [job.get("descriptionPlain", ""), job.get("additionalPlain", "")]
    for block in job.get("lists") or []:
        # list items come as HTML <li> snippets
        parts.append(f"{block.get('text', '')}: {html_to_text(block.get('content', ''))}")
    return "\n".join(part for part in parts if part)


def parse(data: list[dict[str, Any]], org: str) -> list[Opportunity]:
    items: list[Opportunity] = []
    for job in data:
        title = job.get("text", "").strip()
        categories = job.get("categories") or {}
        commitment = str(categories.get("commitment") or "")
        flagged_student = student_level(commitment) == "yes"  # commitment is e.g. "Intern"
        if not (flagged_student or is_student_candidate(title)):
            continue
        if flagged_student and student_level(title) != "yes":
            title = f"{title} ({commitment})"
        location = str(categories.get("location") or "")
        all_locations = categories.get("allLocations") or []
        if len(all_locations) > 1:
            location = " / ".join(all_locations)
        if job.get("country") and job["country"] not in location:
            location = f"{location}, {job['country']}" if location else job["country"]
        items.append(
            Opportunity(
                title=title,
                org=org,
                source=NAME,
                url=job["hostedUrl"],
                location=location,
                remote=job.get("workplaceType") == "remote" or "remote" in location.lower(),
                posted_date=iso_date(job.get("createdAt")),
                description=_description(job),
                hints=["student"] if flagged_student else [],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    companies = config.get("companies", {}).get("lever", []) or []
    return fetch_boards(companies, lambda slug: get_json(URL.format(slug=slug)), parse, NAME)
