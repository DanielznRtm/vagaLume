"""NVIDIA careers (Workday).

NVIDIA's career site runs on Workday, whose search page calls a public JSON
endpoint. We filter on Workday's "worker sub type" facet = Intern, so we
get every internship (not just ones with "intern" in the title).
The facet id lives in config/search.yaml in case Workday changes it.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from ..http import post_json
from ..labels import is_student_candidate
from ..models import Opportunity
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "nvidia"
API_URL = "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"
JOB_URL = "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite{path}"
PAGE_SIZE = 20  # Workday refuses bigger pages
MAX_PAGES = 25


def _posted(text: str, today: date) -> str:
    """Workday says 'Posted Today', 'Posted Yesterday', 'Posted 7 Days Ago', 'Posted 30+ Days Ago'."""
    lowered = text.lower()
    if "today" in lowered:
        return today.isoformat()
    if "yesterday" in lowered:
        return (today - timedelta(days=1)).isoformat()
    match = re.search(r"(\d+)\+? days", lowered)
    return (today - timedelta(days=int(match.group(1)))).isoformat() if match else ""


def parse(data: dict[str, Any], from_intern_facet: bool, today: date | None = None) -> list[Opportunity]:
    today = today or date.today()
    items: list[Opportunity] = []
    for job in data.get("jobPostings", []):
        title = str(job.get("title", "")).strip()
        if not (from_intern_facet or is_student_candidate(title)):
            continue
        location = str(job.get("locationsText") or "")
        items.append(
            Opportunity(
                title=title,
                org="NVIDIA",
                source=NAME,
                url=JOB_URL.format(path=job["externalPath"]),
                location=location,
                remote="remote" in location.lower(),
                posted_date=_posted(str(job.get("postedOn") or ""), today),
                hints=["student"] if from_intern_facet else [],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    settings = config.get("search", {}).get("nvidia", {}) or {}
    facets = settings.get("applied_facets") or {}
    search_text = settings.get("search_text", "")
    for page in range(MAX_PAGES):
        result.checked += 1
        payload = {"appliedFacets": facets, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "searchText": search_text}
        try:
            data = post_json(API_URL, payload)
        except Exception as error:  # noqa: BLE001
            log.warning("NVIDIA page %d failed: %s", page, error)
            result.errors.append(f"offset {page * PAGE_SIZE}: {error}")
            break
        result.items.extend(parse(data, from_intern_facet=bool(facets)))
        if (page + 1) * PAGE_SIZE >= int(data.get("total", 0)):
            break
    return result
