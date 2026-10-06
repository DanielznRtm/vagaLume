"""Meta careers (metacareers.com), scraped with a headless browser.

Meta has no public jobs API and answers plain HTTP requests with an empty
page. So we open the internship search in a real browser (radar/browser.py)
and catch the JSON the page downloads for its job list: a GraphQL response
named "CareersJobSearchResultsV2DataQuery".
"""

from __future__ import annotations

from typing import Any

from ..browser import render
from ..models import Opportunity
from . import SourceResult

NAME = "meta"
SEARCH_URL = "https://www.metacareers.com/jobs?roles[0]=Internship"
JOB_URL = "https://www.metacareers.com/jobs/{job_id}/"
QUERY_NAME = "CareersJobSearchResultsV2DataQuery"


def is_job_list(url: str, post_data: str) -> bool:
    """The one network response we care about."""
    return "/graphql" in url and QUERY_NAME in post_data


def parse(payload: dict[str, Any]) -> list[Opportunity]:
    search = (payload.get("data") or {}).get("job_search_with_featured_jobs_v2") or {}
    jobs = list(search.get("all_jobs") or []) + list(search.get("featured_jobs") or [])
    items: dict[str, Opportunity] = {}
    for job in jobs:
        teams = [*(job.get("teams") or []), *(job.get("sub_teams") or [])]
        opp = Opportunity(
            title=str(job["title"]).strip(),
            org="Meta",
            source=NAME,
            url=JOB_URL.format(job_id=job["id"]),
            location=" / ".join(job.get("locations") or []),
            description="Teams: " + ", ".join(teams),
            hints=["student"],  # we searched with the "Internship" filter
        )
        items.setdefault(opp.id, opp)
    return list(items.values())


ATTEMPTS = 2  # the job list sometimes loads late; one retry fixes that


def fetch(config: dict[str, Any]) -> SourceResult:
    page = render(SEARCH_URL, keep=is_job_list)
    for _ in range(ATTEMPTS - 1):
        if page.captured:
            break
        page = render(SEARCH_URL, keep=is_job_list)
    if not page.captured:
        raise RuntimeError("the job list never loaded (Meta may have changed its page)")
    items: list[Opportunity] = []
    for payload in page.captured:
        items.extend(parse(payload))
    return SourceResult(items=items, checked=1)
