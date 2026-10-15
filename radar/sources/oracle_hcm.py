"""Oracle Recruiting Cloud (Oracle HCM) career sites: ArcelorMittal, PicPay...

Every Oracle career site answers the same public search route:

  GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
      ?onlyData=true&expand=requisitionList
      &finder=findReqs;siteNumber={site},limit=200[,keyword={keyword}]

We keep the student titles (estágio, intern, trainee). Big sites can be
narrowed with a keyword ("estágio"). The sites are in config/companies.yaml,
section `oracle_hcm`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import quote

from ..http import get_json
from ..labels import is_student_candidate
from ..models import Opportunity
from ..places import UFS
from . import SourceResult

NAME = "oracle_hcm"
API_URL = ("https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
           "?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber={site},limit={limit},offset={offset}{keyword}")
JOB_URL = "https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{id}"
PAGE_SIZE = 200
_STATE_NAMES = {name: uf for uf, name in UFS.items()}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def _location(job: dict[str, Any]) -> str:
    """ "Resende, RJ, Brazil" as is; a bare "Brazil" gets the state the title names
    ("Programa de Estágio ArcelorMittal | Ceará")."""
    place = str(job.get("PrimaryLocation") or "").strip()
    if place.lower() not in ("", "brazil", "brasil"):
        return place
    last = re.split(r"\s[|\-–]\s", str(job.get("Title") or ""))[-1]
    uf = _STATE_NAMES.get(_plain(last))
    return f"{last.strip()}, {uf}, Brazil" if uf else "Brazil"


def parse(payload: dict[str, Any], site: dict[str, Any]) -> tuple[list[Opportunity], int]:
    """(student roles on this page, total jobs in the search)."""
    found = (payload or {}).get("items") or []
    if not found or not isinstance(found[0].get("requisitionList"), list):
        raise ValueError("unexpected answer from Oracle (no requisitionList)")
    items: list[Opportunity] = []
    for job in found[0]["requisitionList"]:
        title = str(job.get("Title") or "").strip()
        if not is_student_candidate(title):
            continue
        items.append(
            Opportunity(
                title=title,
                org=str(site.get("name") or site["host"]),
                source=NAME,
                url=JOB_URL.format(host=site["host"], site=site["site"], id=job["Id"]),
                location=_location(job),
                posted_date=str(job.get("PostedDate") or "")[:10],
                description=" ".join(str(job.get(k) or "") for k in ("ShortDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")),
            )
        )
    return items, int(found[0].get("TotalJobsCount") or 0)


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for site in config.get("companies", {}).get("oracle_hcm") or []:
        keyword = f",keyword={quote(site['keyword'])}" if site.get("keyword") else ""
        for page in range(10):
            result.checked += 1
            url = API_URL.format(host=site["host"], site=site["site"], limit=PAGE_SIZE, offset=page * PAGE_SIZE, keyword=keyword)
            try:
                items, total = parse(get_json(url, headers={"Accept": "application/json"}), site)
                result.items.extend(items)
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{site.get('name')}: {error}")
                break
            if (page + 1) * PAGE_SIZE >= total:
                break
    return result
