"""SmartRecruiters: public job lists of companies that hire through it.

Several big employers in Brazil (Bosch, Syngenta, Louis Dreyfus, Continental,
Aumovio...) use SmartRecruiters, which has a public, documented API:

  GET https://api.smartrecruiters.com/v1/companies/{id}/postings?country=br&limit=100&offset=N

Companies are listed in config/companies.yaml (section `smartrecruiters`);
each can set `country` (default "br", Brazil). We keep student-level titles
(estágio, intern, trainee, aprendiz...) and postings typed as internships.
Note: an unknown company id also answers 200 with zero jobs.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlencode

from ..http import get_json
from ..labels import is_student_candidate
from ..models import Opportunity
from ..textutil import iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "smartrecruiters"
API_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings?"
JOB_URL = "https://jobs.smartrecruiters.com/{company}/{job_id}"
PAGE_SIZE = 100  # the API's maximum
MAX_PAGES = 10


def parse(data: dict[str, Any], company: dict[str, Any]) -> list[Opportunity]:
    items: list[Opportunity] = []
    for job in data.get("content") or []:
        title = str(job.get("name", "")).strip()
        internship = (job.get("typeOfEmployment") or {}).get("id") == "intern"
        if not (internship or is_student_candidate(title)):
            continue
        place = job.get("location") or {}
        location = str(place.get("fullLocation") or ", ".join(p for p in (place.get("city"), place.get("region"), place.get("country")) if p))
        items.append(
            Opportunity(
                title=title,
                org=str(company.get("name") or (job.get("company") or {}).get("name") or company["id"]),
                source=NAME,
                url=JOB_URL.format(company=quote(str(company["id"])), job_id=job["id"]),
                location=location,
                remote=bool(place.get("remote")),
                posted_date=iso_date(job.get("releasedDate")),
                hints=["student"] if internship else [],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for company in config.get("companies", {}).get("smartrecruiters") or []:
        try:
            for page in range(MAX_PAGES):
                result.checked += 1
                params = {"limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
                if company.get("country", "br"):
                    params["country"] = company.get("country", "br")
                data = get_json(API_URL.format(company=quote(str(company["id"]))) + urlencode(params))
                result.items.extend(parse(data, company))
                if (page + 1) * PAGE_SIZE >= int(data.get("totalFound") or 0):
                    break
        except Exception as error:  # noqa: BLE001
            log.warning("SmartRecruiters %s failed: %s", company.get("id"), error)
            result.errors.append(f"{company.get('name') or company.get('id')}: {error}")
    return result
