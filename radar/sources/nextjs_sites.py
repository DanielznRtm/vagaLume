"""Career sites built with Next.js: D. E. Shaw and DRW.

Next.js sites send the page's data along with the HTML, inside
<script id="__NEXT_DATA__">. So a plain HTTP request is enough; we just
read that JSON instead of the visible page.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..http import get_text
from ..labels import is_student_candidate
from ..models import Opportunity
from ..textutil import html_to_text
from . import SourceResult

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def next_data(page_html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(page_html)
    if not match:
        raise ValueError("no __NEXT_DATA__ block - the site may have changed")
    return json.loads(match.group(1))["props"]["pageProps"]


# --- D. E. Shaw ---------------------------------------------------------------
DESHAW = "deshaw"
DESHAW_URL = "https://www.deshaw.com/careers/internships"


def parse_deshaw(page_html: str) -> list[Opportunity]:
    props = next_data(page_html)
    entries = [(entry, True) for entry in props.get("internships") or []]
    # Regular jobs too, in case a fellowship or program is listed there.
    entries += [(entry, False) for entry in props.get("regularJobs") or []]
    items: dict[str, Opportunity] = {}
    for entry, is_internship in entries:
        data = entry.get("data") or entry
        title = str(data.get("displayName") or entry.get("displayName") or "").strip()
        if not title or not (is_internship or is_student_candidate(title)):
            continue
        offices = entry.get("office") or []  # e.g. [{"abbreviation": "NYC", "name": "New York"}]
        if isinstance(offices, dict):
            offices = [offices]
        location = " / ".join(str(o.get("name", "")) for o in offices if isinstance(o, dict))
        match = re.search(r"\(([^)]+)\)", title)  # "Software Developer Intern (New York) – Summer 2027"
        location = location or (match.group(1) if match else "")
        description = html_to_text(str((data.get("jobDescription") or {}).get("websiteDescription") or ""))
        opp = Opportunity(
            title=title,
            org="D. E. Shaw",
            source=DESHAW,
            url=f"https://www.deshaw.com/careers/{str(data['jobUrl']).lower()}",
            location=location,
            description=description,
            hints=["student"] if is_internship else [],
        )
        items.setdefault(opp.id, opp)
    return list(items.values())


def fetch_deshaw(config: dict[str, Any]) -> SourceResult:
    return SourceResult(items=parse_deshaw(get_text(DESHAW_URL)), checked=1)


# --- DRW --------------------------------------------------------------------------
DRW = "drw"
DRW_URL = "https://www.drw.com/work-at-drw/listings"


def parse_drw(page_html: str) -> list[Opportunity]:
    job_data = next_data(page_html).get("jobData") or {}
    jobs = job_data.get("en", []) if isinstance(job_data, dict) else job_data
    items: list[Opportunity] = []
    for job in jobs:
        title = str(job.get("title") or job.get("job_title") or "").strip()
        campus = "Campus" in (job.get("career_categories") or [])
        if not (campus or is_student_candidate(title)):
            continue
        places = [*(job.get("locations") or []), *(job.get("career_countries") or [])]
        items.append(
            Opportunity(
                title=title,
                org="DRW",
                source=DRW,
                url=f"https://www.drw.com/work-at-drw/listings/{job['slug']}",
                location=", ".join(places),
                hints=["student"] if campus else [],
            )
        )
    return items


def fetch_drw(config: dict[str, Any]) -> SourceResult:
    return SourceResult(items=parse_drw(get_text(DRW_URL)), checked=1)
