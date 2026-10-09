"""IEL (Instituto Euvaldo Lodi, from Brazil's industry federations): estágio
vacancies from IEL offices across the country, strongest in the North-East,
Centre-West and South, plus some IEL-PR research grants ("Bolsista").

The vacancy page reads a public API (Liferay "objects") that we call directly:
  https://liferay.sistemaindustria.com.br/o/c/ievagas/?sort=date:desc&page=N&pageSize=500
The list keeps old postings, so we stop at MAX_AGE_DAYS.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..models import Opportunity
from ..textutil import iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "iel"
API_URL = "https://liferay.sistemaindustria.com.br/o/c/ievagas/?"
FIELDS = "id,title,company,city,uF,area,modality,date,url,description"
PAGE_SIZE = 500
MAX_PAGES = 10
MAX_AGE_DAYS = 60
WORKPLACE = {"presencial": "on-site", "híbrido": "hybrid", "hibrido": "hybrid", "remoto": "remote"}


def parse(data: dict[str, Any]) -> list[Opportunity]:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("unexpected answer from IEL (no 'items' list)")
    items: list[Opportunity] = []
    for job in data["items"]:
        title = " ".join(str(job.get("title") or "").split())
        if not title or not job.get("url"):
            continue
        if title.isupper():  # "ESTÁGIO EM ADMINISTRAÇÃO" -> "Estágio em administração"
            title = title.capitalize()
        area = str(job.get("area") or "")
        place = ", ".join(p for p in (job.get("city"), job.get("uF")) if p)
        workplace = WORKPLACE.get(str(job.get("modality") or "").lower(), "")
        items.append(
            Opportunity(
                title=title,
                org=str(job.get("company") or "").strip() or "Empresa não informada (IEL)",
                source=NAME,
                url=str(job["url"]),
                location=(f"{place}, Brazil" if place else "Brazil") + (f" ({workplace})" if workplace else ""),
                remote=workplace == "remote",
                posted_date=iso_date(job.get("date")),
                description=str(job.get("description") or ""),
                # Estágio and Aprendiz are student roles; "Bolsista" grants may also be for graduates.
                hints=["student"] if area.lower() in {"estágio", "estagio", "aprendiz"} else ["unsure-student"],
            )
        )
    return items


def fetch(config: dict[str, Any], today: date | None = None) -> SourceResult:
    result = SourceResult()
    oldest = ((today or date.today()) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    for page in range(1, MAX_PAGES + 1):
        result.checked += 1
        params = {"sort": "date:desc", "page": page, "pageSize": PAGE_SIZE, "fields": FIELDS}
        try:
            data = get_json(API_URL + urlencode(params), headers={"Accept": "application/json"})
            items = parse(data)
        except Exception as error:  # noqa: BLE001
            log.warning("IEL page %d failed: %s", page, error)
            result.errors.append(f"page {page}: {error}")
            break
        recent = [o for o in items if not o.posted_date or o.posted_date >= oldest]
        result.items.extend(recent)
        if not recent or page >= int(data.get("lastPage") or 1):
            break
    return result
