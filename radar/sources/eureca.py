"""Eureca: the agency behind the estágio programs of Aché, Serasa Experian,
AkzoNobel, Motiva, Ardagh, Stellantis and others.

Its job site (app.eureca.me) is built in the browser, but it loads every open
role with one public request, no login:

  GET https://candidate-api.eureca.me/opportunities

Each role has its program ("Programa de Estágio Aché 2027"), contract type
(internship, trainee, young-apprentice), cities and states, work model, the
last day to apply and, sometimes, the bolsa in cents. Jovem aprendiz roles
(for 14–24-year-olds outside university) are left out, as in the Gupy source.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from ..http import get_json
from ..models import NO_DEADLINE, Opportunity
from ..pay import from_range
from ..places import city_state
from ..textutil import html_to_text, iso_date
from . import SourceResult

NAME = "eureca"
API_URL = "https://candidate-api.eureca.me/opportunities"
JOB_URL = "https://app.eureca.me/vagas/{id}"
KEEP = {"internship": "student", "trainee": "unsure-student"}
WORK_MODELS = {"presencial": "on-site", "hibrido": "hybrid", "remoto": "remote"}
_STUDENT_TITLE = re.compile(r"est[áa]gi|intern|trainee", re.I)


def _deadline(end: str) -> str:
    """"2026-11-07T02:59:00.000Z" is 23:59 on Nov 6 in Brasília (UTC-3)."""
    try:
        moment = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return iso_date(end) or NO_DEADLINE
    return (moment - timedelta(hours=3)).date().isoformat()


def _location(job: dict[str, Any]) -> str:
    places = job.get("locations") or {}
    states = [str(s) for s in places.get("states") or []]
    cities = [str(c) for c in places.get("cities") or []]
    if not cities:
        return f"{', '.join(states)}, Brazil" if states else "Brazil"
    parts = []
    for city in cities[:6]:
        state = states[0] if len(states) == 1 else city_state(city)
        parts.append(f"{city}, {state}, Brazil" if state else f"{city}, Brazil")
    return " / ".join(parts) + (f" / +{len(cities) - 6} cities, Brazil" if len(cities) > 6 else "")


def to_opportunity(job: dict[str, Any]) -> Opportunity | None:
    hint = KEEP.get(str(job.get("contractTypeKey") or ""))
    if not hint:
        return None
    name = str(job.get("name") or "").strip()
    program = str(job.get("programName") or "").strip()
    # Serasa's roles are just "Finanças", "Analytics": say which program they belong to.
    title = name if _STUDENT_TITLE.search(name) or not program else f"{program}: {name}"
    salary = job.get("salary") or {}
    low, high = salary.get("minCents"), salary.get("maxCents")
    pay = from_range(low / 100 if low else None, high / 100 if high else None, "BRL", "mo") if low or high else ""
    model = WORK_MODELS.get(str(job.get("workModel") or ""), "")
    location = _location(job)
    return Opportunity(
        title=title,
        org=str(job.get("companyName") or "?").strip(),
        source=NAME,
        url=JOB_URL.format(id=job["id"]),
        location=location + (f" ({model})" if model else ""),
        remote=model == "remote",
        posted_date=iso_date(job.get("publishedAt") or job.get("createdAt")),
        deadline=_deadline(str(job.get("endApplying") or "")) if job.get("endApplying") else NO_DEADLINE,
        pay=pay,
        description=f"{program}. " + html_to_text(str(job.get("description") or "")),
        hints=[hint],
    )


def parse(payload: dict[str, Any]) -> list[Opportunity]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("unexpected answer from Eureca (no 'items' list)")
    return [opp for job in payload["items"] if (opp := to_opportunity(job))]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    page = 1
    while page <= 10:  # 200 per page; there are about 80 today
        result.checked += 1
        try:
            payload = get_json(f"{API_URL}?page={page}", headers={"Accept": "application/json"})
            result.items.extend(parse(payload))
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"page {page}: {error}")
            break
        if page * int(payload.get("pageSize") or 200) >= int(payload.get("total") or 0):
            break
        page += 1
    return result
