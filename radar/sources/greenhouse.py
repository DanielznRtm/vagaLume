"""Greenhouse public job boards.

API docs: https://developers.greenhouse.io/job-board.html
One request per company returns all its open jobs (with descriptions
when we add ?content=true).
"""

from __future__ import annotations

from typing import Any

from ..http import get_json
from ..labels import is_student_candidate, student_level
from ..models import NO_DEADLINE, Opportunity
from ..textutil import html_to_text, iso_date
from . import SourceResult
from .ats import fetch_boards

NAME = "greenhouse"
URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def _metadata(job: dict[str, Any], name: str) -> str:
    """Some companies add custom fields such as 'Employment Type' or 'Duration'."""
    for meta in job.get("metadata") or []:
        if isinstance(meta, dict) and str(meta.get("name", "")).lower() == name.lower():
            return str(meta.get("value") or "")
    return ""


def parse(data: dict[str, Any], org: str) -> list[Opportunity]:
    """Turn one Greenhouse board response into Opportunity objects."""
    items: list[Opportunity] = []
    for job in data.get("jobs", []):
        title = job.get("title", "").strip()
        employment = _metadata(job, "Employment Type")  # e.g. "Summer Internship"
        flagged_student = student_level(employment) == "yes"
        if not (flagged_student or is_student_candidate(title)):
            continue  # a regular (non-student) job: not what this radar is for
        if flagged_student and student_level(title) != "yes":
            # Jane Street calls its interns just "Software Engineer"; make that visible.
            title = f"{title} ({employment})"
        duration = _metadata(job, "Duration")  # e.g. "May-August"
        location = (job.get("location") or {}).get("name", "")
        items.append(
            Opportunity(
                title=title,
                org=org,
                source=NAME,
                url=job["absolute_url"],
                location=location,
                remote="remote" in location.lower(),
                posted_date=iso_date(job.get("first_published") or job.get("updated_at")),
                deadline=iso_date(job.get("application_deadline")) or NO_DEADLINE,
                description=html_to_text(html_to_text(job.get("content", ""))),  # content is HTML-escaped HTML
                hints=(["student"] if flagged_student else []) + ([duration] if duration else []),
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    companies = config.get("companies", {}).get("greenhouse", []) or []
    return fetch_boards(companies, lambda slug: get_json(URL.format(slug=slug)), parse, NAME)
