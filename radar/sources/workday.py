"""Brazilian roles at multinationals that hire through Workday.

Many big employers in Brazil (Santander, P&G, Citi, Mondelēz, Accenture,
Hitachi...) run their career sites on Workday. Each site has the same public
JSON search endpoint (the one radar/sources/nvidia.py uses):

  POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

For each site in config/companies.yaml (section `workday_brazil`) we:
  1. ask for one job just to read the site's filters ("facets");
  2. pick the country filter that has Brazil (Workday uses the same id for
     Brazil on every site) and, when the site has one, the "job type"
     filter values for interns / apprentices / trainees;
  3. page through those jobs, 20 at a time.
Sites without a job-type filter are searched for Brazil only, and we keep the
titles that look like student roles.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Iterator

from ..http import post_json
from ..labels import is_student_candidate
from ..models import Opportunity
from . import SourceResult
from .nvidia import _posted

log = logging.getLogger(__name__)

NAME = "workday"
BRAZIL_ID = "1a29bb1357b240ab99a2fa755cc87c0e"  # Workday's id for Brazil, the same on every site
PAGE_SIZE = 20  # Workday refuses bigger pages
MAX_PAGES = 15
STUDENT_TYPE = re.compile(r"intern|estagi|apprentic|aprendiz|trainee|student|co-?op|praktik", re.I)


def base_url(site: dict[str, Any]) -> str:
    return f"https://{site['tenant']}.wd{site['wd']}.myworkdayjobs.com"


def api_url(site: dict[str, Any]) -> str:
    return f"{base_url(site)}/wday/cxs/{site['tenant']}/{site['site']}/jobs"


def _facet_values(facets: list[dict[str, Any]], parameter: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Every (facet parameter, value) pair, including values nested in groups."""
    for facet in facets or []:
        name = str(facet.get("facetParameter") or parameter)
        for value in facet.get("values") or []:
            if value.get("values"):  # a group such as "locationMainGroup"
                yield from _facet_values([value], name)
            else:
                yield name, value


def choose_facets(data: dict[str, Any]) -> tuple[dict[str, list[str]], bool]:
    """(filters to apply, whether they include a student job-type filter)."""
    applied: dict[str, list[str]] = {}
    student_ids: dict[str, list[str]] = {}
    for parameter, value in _facet_values(data.get("facets") or []):
        if value.get("id") == BRAZIL_ID and parameter not in applied:
            applied[parameter] = [BRAZIL_ID]
        if "subtype" in parameter.lower() and STUDENT_TYPE.search(str(value.get("descriptor") or "")):
            student_ids.setdefault(parameter, []).append(str(value["id"]))
    if not applied:
        raise ValueError("this site has no Brazil filter")
    applied.update(student_ids)
    return applied, bool(student_ids)


def parse(data: dict[str, Any], site: dict[str, Any], from_student_facet: bool, today: date | None = None) -> list[Opportunity]:
    today = today or date.today()
    items: list[Opportunity] = []
    for job in data.get("jobPostings") or []:
        title = str(job.get("title", "")).strip()
        if not (from_student_facet or is_student_candidate(title)):
            continue
        place = str(job.get("locationsText") or "")
        # The Brazil filter guarantees a Brazilian location; "2 Locations" doesn't say which.
        location = place if re.search(r"bra[sz]il", place, re.I) else f"{place}, Brazil" if place else "Brazil"
        items.append(
            Opportunity(
                title=title,
                org=str(site.get("name") or site["tenant"]),
                source=NAME,
                url=f"{base_url(site)}/en-US/{site['site']}{job['externalPath']}",
                location=location,
                remote="remote" in place.lower(),
                posted_date=_posted(str(job.get("postedOn") or ""), today),
                hints=["student"] if from_student_facet else [],
            )
        )
    return items


def fetch_site(site: dict[str, Any]) -> tuple[list[Opportunity], int]:
    """All Brazilian student roles of one Workday site, and how many requests it took."""
    url = api_url(site)
    first = post_json(url, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
    applied, student_facet = choose_facets(first)
    items: list[Opportunity] = []
    requests_made = 1
    for page in range(MAX_PAGES):
        data = post_json(url, {"appliedFacets": applied, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "searchText": ""})
        requests_made += 1
        items.extend(parse(data, site, student_facet))
        if (page + 1) * PAGE_SIZE >= int(data.get("total") or 0):
            break
    return items, requests_made


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for site in config.get("companies", {}).get("workday_brazil") or []:
        try:
            items, requests_made = fetch_site(site)
            result.items.extend(items)
            result.checked += requests_made
        except Exception as error:  # noqa: BLE001
            result.checked += 1
            log.warning("Workday %s failed: %s", site.get("tenant"), error)
            result.errors.append(f"{site.get('name') or site.get('tenant')}: {error}")
    return result
