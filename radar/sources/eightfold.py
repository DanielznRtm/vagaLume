"""Eightfold career sites (the "PCSX" kind): Mercado Livre, Morgan Stanley...

The search page of every such site calls one public JSON route, 10 jobs per
request (the same one radar/sources/microsoft.py uses for Microsoft):

  GET https://{host}/api/pcsx/search?domain={domain}&query={query}&location={location}&start={N}

Each job has its title, locations ("São Paulo, São Paulo, Brazil"), work model,
department and posting time. We keep the student titles (estágio, intern,
trainee...). Sites that use the older Eightfold route (/api/apply/v2/jobs,
like Vale's) answer "Not authorized for PCSX" here. The sites are in
config/companies.yaml, section `eightfold`: `location` narrows the search to
a country and `queries` (default: one empty query) to some words.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..labels import student_level
from ..models import Opportunity
from ..textutil import iso_date
from . import SourceResult

NAME = "eightfold"
SEARCH_URL = "https://{host}/api/pcsx/search?"
PAGE_SIZE = 10  # fixed by Eightfold
MAX_PAGES = 30  # per query
WORK_MODELS = {"onsite": "on-site", "hybrid": "hybrid", "remote": "remote"}


def _place(text: str) -> str:
    """Eightfold writes "Sao Paulo, São Paulo, Brazil" or, on some sites, "Brasil,Brazil"."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    deduped = [p for i, p in enumerate(parts) if i == 0 or p.lower() != parts[i - 1].lower()]
    if len(deduped) >= 2 and deduped[0].lower() in ("brasil", "brazil"):
        deduped = deduped[1:]
    return ", ".join(deduped)


def parse(data: dict[str, Any], site: dict[str, Any]) -> tuple[list[Opportunity], int]:
    """(student roles on this page, total results of the search)."""
    block = (data or {}).get("data")
    if not isinstance(block, dict) or not isinstance(block.get("positions"), list):
        raise ValueError(f"unexpected answer from Eightfold: {str(data)[:120]}")
    items: list[Opportunity] = []
    for job in block["positions"]:
        title = str(job.get("name") or "").strip()
        if student_level(title) != "yes":
            continue
        model = WORK_MODELS.get(str(job.get("workLocationOption") or "").lower(), "")
        places = [_place(str(p)) for p in job.get("locations") or []]
        location = " / ".join(p for p in places if p) or ", ".join(job.get("standardizedLocations") or [])
        items.append(
            Opportunity(
                title=title,
                org=str(site.get("name") or site["host"]),
                source=NAME,
                url=f"https://{site['host']}{job.get('positionUrl') or '/careers/job/' + str(job['id'])}",
                location=location + (f" ({model})" if model else ""),
                remote=model == "remote",
                posted_date=iso_date(job.get("postedTs") or job.get("creationTs")),
                description=str(job.get("department") or ""),
            )
        )
    return items, int(block.get("count") or 0)


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for site in config.get("companies", {}).get("eightfold") or []:
        seen: set[str] = set()
        for query in site.get("queries") or [""]:
            for page in range(MAX_PAGES):
                result.checked += 1
                params = {"domain": site["domain"], "query": query, "location": site.get("location", ""), "start": page * PAGE_SIZE}
                try:
                    items, total = parse(get_json(SEARCH_URL.format(host=site["host"]) + urlencode(params),
                                                  headers={"Accept": "application/json"}), site)
                except Exception as error:  # noqa: BLE001
                    result.errors.append(f"{site.get('name')}: query {query!r} start {page * PAGE_SIZE}: {error}")
                    break
                for opp in items:
                    if opp.id not in seen:
                        seen.add(opp.id)
                        result.items.append(opp)
                if (page + 1) * PAGE_SIZE >= total:
                    break
    return result
