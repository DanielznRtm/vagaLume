"""Brazilian roles at multinationals that hire through Workday.

Many big employers in Brazil (Santander, P&G, Citi, Mondelēz, Accenture,
Hitachi...) run their career sites on Workday. Each site has the same public
JSON search endpoint (the one radar/sources/nvidia.py uses):

  POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

For each site in config/companies.yaml (section `workday_brazil`) we:
  1. ask for one job just to read the site's filters ("facets");
  2. pick the country filter that has Brazil (Workday uses the same id for
     Brazil on every site) and, when the site has one, the "job type"
     filter values for interns / apprentices / trainees. Some sites (GE
     Vernova, Toyota, J&J) have no country filter, only cities: then we pick
     the cities that are Brazilian (radar/places.py);
  3. page through those jobs, 20 at a time.
Sites without a job-type filter are searched for Brazil only, and we keep the
titles that look like student roles.

Section `workday_global` lists employers with many internships abroad
(Airbus, Thales, ZEISS, NXP...): there we skip the country filter and use
only the job-type filter (named workerSubType, Worker_Type, Contract_Type...
depending on the site), or, when a site has none, title searches.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Iterator

from ..http import get_json, post_json
from ..labels import classify_regions, is_student_candidate
from ..models import Opportunity
from ..places import ALSO_ABROAD, city_state
from . import SourceResult
from .nvidia import _posted

log = logging.getLogger(__name__)

NAME = "workday"
BRAZIL_ID = "1a29bb1357b240ab99a2fa755cc87c0e"  # Workday's id for Brazil, the same on every site
PAGE_SIZE = 20  # Workday refuses bigger pages
MAX_PAGES = 15
MAX_PAGES_GLOBAL = 40  # Airbus has ~600 student jobs
STUDENT_TYPE = re.compile(r"intern|estagi|apprenti|aprendiz|trainee|student|co-?op|praktik|stagi|\bstage\b|alternan"
                          r"|thesis|placement|becari|practicante|pasant", re.I)
# The job-type filter's name differs between sites.
TYPE_FACET = re.compile(r"subtype|worker_?type|employee_?type|contract_?type|job_?type|time_?type_?student", re.I)
# Title searches for global sites without a job-type filter.
GLOBAL_SEARCHES = ["intern", "student", "stage", "praktikum", "thesis", "trainee"]


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
        if TYPE_FACET.search(parameter) and STUDENT_TYPE.search(str(value.get("descriptor") or "")):
            student_ids.setdefault(parameter, []).append(str(value["id"]))
    if not applied:
        cities = brazilian_cities(data)
        if not cities:
            raise ValueError("this site has no Brazil filter")
        applied["locations"] = cities
    applied.update(student_ids)
    return applied, bool(student_ids)


def _is_brazilian(place: str) -> bool:
    """ "São José dos Campos, São Paulo, Brazil", "Sao Paulo", "Taubate" yes; "Buenos Aires", "Abidjan" no."""
    if re.search(r"bra[sz]il", place, re.I):
        return True
    if "," in place:
        return False  # "Irvine, California, United States": full names say their country ("PA", "SC" are US states too)
    return bool(city_state(place)) and place.strip().lower() not in ALSO_ABROAD


def brazilian_cities(data: dict[str, Any]) -> list[str]:
    """Ids of the Brazilian cities in a site's "locations" filter (for sites without a country filter)."""
    return [str(value["id"]) for parameter, value in _facet_values(data.get("facets") or [])
            if parameter == "locations" and _is_brazilian(str(value.get("descriptor") or ""))]


def student_facets(data: dict[str, Any]) -> dict[str, list[str]]:
    """The job-type filter values for students (global sites)."""
    found: dict[str, list[str]] = {}
    for parameter, value in _facet_values(data.get("facets") or []):
        if TYPE_FACET.search(parameter) and STUDENT_TYPE.search(str(value.get("descriptor") or "")):
            found.setdefault(parameter, []).append(str(value["id"]))
    return found


# Vocational training for school leavers, not university students (like jovem aprendiz): left out
# even when the site files it under its apprentice job type.
VOCATIONAL = re.compile(r"\bausbildung|\bazubi\b|jovem aprendiz", re.I)


def parse(data: dict[str, Any], site: dict[str, Any], from_student_facet: bool, today: date | None = None,
          brazil: bool = True) -> list[Opportunity]:
    today = today or date.today()
    items: list[Opportunity] = []
    for job in data.get("jobPostings") or []:
        title = str(job.get("title", "")).strip()
        if not (from_student_facet or is_student_candidate(title)) or VOCATIONAL.search(title):
            continue
        place = str(job.get("locationsText") or "")
        if brazil:
            # The Brazil filter guarantees a Brazilian location; "2 Locations" doesn't say which.
            location = place if re.search(r"bra[sz]il", place, re.I) else f"{place}, Brazil" if place else "Brazil"
        else:
            location = place
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
    total = 0
    for page in range(MAX_PAGES):
        data = post_json(url, {"appliedFacets": applied, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "searchText": ""})
        requests_made += 1
        items.extend(parse(data, site, student_facet))
        total = total or int(data.get("total") or 0)  # Workday sends the total on the first page only
        if (page + 1) * PAGE_SIZE >= total or not data.get("jobPostings"):
            break
    return items, requests_made


def _pages(url: str, applied: dict[str, list[str]], search: str, site: dict[str, Any], student_facet: bool,
           country: str = "") -> tuple[list[Opportunity], int]:
    items: list[Opportunity] = []
    total = 0
    for page in range(MAX_PAGES_GLOBAL):
        data = post_json(url, {"appliedFacets": applied, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "searchText": search})
        for opp in parse(data, site, student_facet, brazil=False):
            # "Toulouse Area" alone doesn't say the country; the country filter we used does.
            if country and country.lower() not in opp.location.lower():
                opp.location = f"{opp.location}, {country}" if opp.location else country
            items.append(opp)
        total = total or int(data.get("total") or 0)  # Workday sends the total on the first page only
        if (page + 1) * PAGE_SIZE >= total or not data.get("jobPostings"):
            return items, page + 1
    return items, MAX_PAGES_GLOBAL


def _countries(data: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
    """The site's country filter: (its name, [(id, country)]) for countries with jobs."""
    for parameter, value in _facet_values(data.get("facets") or []):
        if "country" in parameter.lower():
            values = [(str(v["id"]), str(v.get("descriptor") or "")) for p, v in _facet_values(data.get("facets") or [])
                      if p == parameter and v.get("count", 1)]
            return parameter, values
    return "", []


MAX_DETAILS = 150  # job pages read per site to learn where a role is


def _fill_places(items: list[Opportunity], site: dict[str, Any]) -> int:
    """ "2 Locations" or a bare "Belfort" doesn't say the country: read the job's own page,
    which does ("Massy", country France). Returns how many pages were read."""
    unknown = [o for o in items if classify_regions(o.location, o.remote) == ["unknown"]][:MAX_DETAILS]
    for opp in unknown:
        path = opp.url.split(f"/{site['site']}", 1)[-1]
        try:
            info = get_json(f"{base_url(site)}/wday/cxs/{site['tenant']}/{site['site']}{path}").get("jobPostingInfo") or {}
        except Exception:  # noqa: BLE001 - keep the role with what we have
            continue
        country = str((info.get("country") or {}).get("descriptor") or "")
        places = [str(p) for p in [info.get("location"), *(info.get("additionalLocations") or [])] if p]
        if places or country:
            first = ", ".join(p for p in (places[0] if places else "", country) if p)
            opp.location = " / ".join([first, *places[1:]])
    return len(unknown)


def fetch_site_global(site: dict[str, Any]) -> tuple[list[Opportunity], int]:
    """Student roles of one Workday site in every country, and how many requests it took."""
    items, made = _fetch_site_global(site)
    return items, made + _fill_places(items, site)


def _fetch_site_global(site: dict[str, Any]) -> tuple[list[Opportunity], int]:
    url = api_url(site)
    first = post_json(url, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
    facets = student_facets(first)
    if facets:
        # Ask for the student roles once, to learn in which countries they are, then country by country.
        probe = post_json(url, {"appliedFacets": facets, "limit": 1, "offset": 0, "searchText": ""})
        parameter, countries = _countries(probe)
        if not parameter:
            items, made = _pages(url, facets, "", site, True)
            return items, made + 2
        items, made = [], 2
        for country_id, country in countries:
            found, pages = _pages(url, {**facets, parameter: [country_id]}, "", site, True, country)
            items += found
            made += pages
        return items, made
    items, made, seen = [], 1, set()
    for search in GLOBAL_SEARCHES:
        found, pages = _pages(url, {}, search, site, False)
        made += pages
        items += [o for o in found if o.url not in seen and not seen.add(o.url)]
    return items, made


def fetch(config: dict[str, Any]) -> SourceResult:
    """Every site, 8 at a time (each site is a different company's server, asked one request at a time)."""
    result = SourceResult()
    sites = [(s, fetch_site) for s in config.get("companies", {}).get("workday_brazil") or []]
    sites += [(s, fetch_site_global) for s in config.get("companies", {}).get("workday_global") or []]

    def run(job: tuple[dict[str, Any], Any]) -> tuple[dict[str, Any], Any]:
        site, fetch_one = job
        try:
            return site, fetch_one(site)
        except Exception as error:  # noqa: BLE001
            return site, error

    with ThreadPoolExecutor(max_workers=8) as pool:
        for site, outcome in pool.map(run, sites):  # map keeps the config order
            if isinstance(outcome, Exception):
                result.checked += 1
                log.warning("Workday %s failed: %s", site.get("tenant"), outcome)
                result.errors.append(f"{site.get('name') or site.get('tenant')}: {outcome}")
            else:
                items, requests_made = outcome
                result.items.extend(items)
                result.checked += requests_made
    return result
