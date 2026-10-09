"""Sólides Vagas (vagas.solides.com.br): estágio at thousands of Brazilian
companies, many of them small and mid-sized.

The site's search page calls a JSON route that we call directly:
  https://vagas.solides.com.br/api/vacancies?page=N&take=20&contractsType=estagio
Results come newest first, 20 per page (bigger pages fail). The list also
keeps postings from years ago that were never closed, so we stop once the
postings are older than MAX_AGE_DAYS.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..models import Opportunity
from ..pay import from_range
from ..textutil import html_to_text, iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "solides"
API_URL = "https://vagas.solides.com.br/api/vacancies?"
JOB_URL = "https://vagas.solides.com.br/vaga/{job_id}"
PAGE_SIZE = 20
MAX_PAGES = 60
MAX_AGE_DAYS = 60
WORKPLACE = {"presencial": "on-site", "hibrido": "hybrid", "remoto": "remote"}


def parse(data: dict[str, Any]) -> list[Opportunity]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("unexpected answer from Sólides (no 'data' list)")
    items: list[Opportunity] = []
    for job in data["data"]:
        if job.get("isHiddenJob"):
            continue
        place = ", ".join(p for p in ((job.get("city") or {}).get("name"), (job.get("state") or {}).get("name")) if p)
        workplace = WORKPLACE.get(str(job.get("jobType") or ""), "")
        salary = job.get("salary") or {}
        items.append(
            Opportunity(
                title=str(job.get("title", "")).strip(),
                org=str(job.get("companyName") or "?").strip(),
                source=NAME,
                url=JOB_URL.format(job_id=job["id"]),
                location=(f"{place}, Brazil" if place else "Brazil") + (f" ({workplace})" if workplace else ""),
                remote=workplace == "remote" or bool(job.get("homeOffice")),
                posted_date=iso_date(job.get("createdAt")),
                pay=from_range(salary.get("initialRange"), salary.get("finalRange"), "BRL", "mo"),
                description=html_to_text(str(job.get("description") or "")),
                hints=["student"],  # we only ask for contract type "estágio"
            )
        )
    return items


def fetch(config: dict[str, Any], today: date | None = None) -> SourceResult:
    result = SourceResult()
    oldest = ((today or date.today()) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        result.checked += 1
        params = {"page": page, "take": PAGE_SIZE, "contractsType": "estagio"}
        try:
            data = get_json(API_URL + urlencode(params), headers={"Accept": "application/json"})
            items = parse(data)
        except Exception as error:  # noqa: BLE001
            log.warning("Sólides page %d failed: %s", page, error)
            result.errors.append(f"page {page}: {error}")
            break
        recent = [o for o in items if not o.posted_date or o.posted_date >= oldest]
        for opp in recent:
            if opp.id not in seen:
                seen.add(opp.id)
                result.items.append(opp)
        if len(data["data"]) < PAGE_SIZE or not recent:
            break  # the last page, or a whole page of postings that are too old
    return result
