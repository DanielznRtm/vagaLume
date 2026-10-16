"""Shopee (and SPX Express, Monee): careers.shopee.com.br and the other Shopee
career sites share one public job API, no login:

  GET https://ats.workatsea.com/ats/api/v1/user/meta/slice/?flags=16
      -> the offices (flat_locations): city ids per country (São Paulo = 2)
  GET https://ats.workatsea.com/ats/api/v1/user/job/list/?city_ids=..&employment_ids=4&limit=100&offset=N
      -> jobs with title, city, level (employment_id 4 = Internship) and the
         full description and requirements (HTML)

We ask for the internships of the offices in the configured countries and also
search their titles for "estágio" / "trainee" (Shopee Brazil writes some
estágios as Entry Level). Jobs open at https://careers.shopee.com.br/job-detail/{job_id}/1.
The countries are in config/companies.yaml, section `shopee` (default: Brazil).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..labels import student_level
from ..models import Opportunity
from ..places import city_state
from ..textutil import html_to_text
from . import SourceResult

NAME = "shopee"
API = "https://ats.workatsea.com/ats/api/v1"
META_URL = API + "/user/meta/slice/?flags=16&from_career=true"
LIST_URL = API + "/user/job/list/?"
JOB_URL = "https://careers.shopee.com.br/job-detail/{id}/1"
INTERNSHIP = 4  # employment_id of "Internship"
PAGE_SIZE = 100
MAX_PAGES = 5
SEARCHES = ["estágio", "estagiário", "trainee"]


def parse_cities(meta: dict[str, Any], countries: list[str]) -> dict[int, tuple[str, str]]:
    """city id -> (city, country) for the offices in these countries."""
    places = ((meta or {}).get("data") or {}).get("flat_locations")
    if not isinstance(places, list):
        raise ValueError("unexpected answer from Shopee (no flat_locations)")
    wanted = {c.lower() for c in countries}
    return {int(p["city_id"]): (str(p.get("city_name") or ""), str(p.get("region_name") or ""))
            for p in places if str(p.get("region_name") or "").lower() in wanted}


def parse(payload: dict[str, Any], cities: dict[int, tuple[str, str]]) -> tuple[list[Opportunity], int]:
    """(student roles in this answer, total jobs in the search)."""
    data = (payload or {}).get("data")
    if not isinstance(data, dict):
        raise ValueError(f"unexpected answer from Shopee: {str(payload)[:120]}")
    items: list[Opportunity] = []
    for job in data.get("job_list") or []:
        title = str(job.get("job_name") or "").strip()
        intern = int(job.get("employment_id") or 0) == INTERNSHIP
        if not intern and student_level(title) != "yes":
            continue
        city, country = cities.get(int(job.get("city_id") or 0), ("", ""))
        if not country:
            continue  # an office outside the countries we asked for
        if country == "Brazil":
            state = city_state(city)
            location = f"{city}, {state}, Brazil" if state else f"{city}, Brazil"
        else:
            location = f"{city}, {country}" if city and city != country else country
        items.append(
            Opportunity(
                title=title,
                org="Shopee",
                source=NAME,
                url=JOB_URL.format(id=job["job_id"]),
                location=location,
                description=html_to_text(f"{job.get('job_description') or ''}\n{job.get('requirements') or ''}"),
                hints=["student"] if intern else [],
            )
        )
    return items, int(data.get("total_count") or 0)


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    countries = (config.get("companies", {}).get("shopee") or {}).get("countries") or ["Brazil"]
    result.checked += 1
    try:
        cities = parse_cities(get_json(META_URL, headers={"Accept": "application/json"}), countries)
    except Exception as error:  # noqa: BLE001
        result.errors.append(f"offices: {error}")
        return result
    if not cities:
        result.errors.append(f"no Shopee office in {countries}")
        return result
    seen: set[str] = set()
    searches: list[dict[str, Any]] = [{"employment_ids": INTERNSHIP}] + [{"search_content": word} for word in SEARCHES]
    for search in searches:
        for page in range(MAX_PAGES):
            result.checked += 1
            params = {"limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "city_ids": sorted(cities), **search}
            try:
                items, total = parse(get_json(LIST_URL + urlencode(params, doseq=True), headers={"Accept": "application/json"}), cities)
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{search}: {error}")
                break
            for opp in items:
                if opp.id not in seen:
                    seen.add(opp.id)
                    result.items.append(opp)
            if (page + 1) * PAGE_SIZE >= total:
                break
    return result
