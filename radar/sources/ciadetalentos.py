"""Cia de Talentos: the agency that runs the estágio and trainee programs of
many big companies in Brazil (Globo, Bayer, Unilever, PepsiCo, BASF...).

Its vacancy site (vagas.ciadetalentos.com.br) loads the list of open
programs with one public request, before any login:

  POST https://vagas.ciadetalentos.com.br/applicant/rest/applicant/authentication/filter
       {"locale": "pt"}

Each program has a type (Estágio Superior, Estágio Técnico, Trainee...) and
"countFinishDays": the days left to apply (negative = closed that many days
ago). We keep the open ones; the days left become the deadline.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..http import post_json
from ..models import Opportunity
from ..textutil import html_to_text
from . import SourceResult

NAME = "ciadetalentos"
API_URL = "https://vagas.ciadetalentos.com.br/applicant/rest/applicant/authentication/filter"


def _after_colon(text: Any) -> str:
    """"Localidade: São Paulo" -> "São Paulo"."""
    return str(text or "").split(":", 1)[-1].strip()


def parse(data: list[dict[str, Any]], today: date | None = None) -> list[Opportunity]:
    if not isinstance(data, list):
        raise ValueError("unexpected answer from Cia de Talentos (not a list)")
    today = today or date.today()
    items: list[Opportunity] = []
    for program in data:
        url = program.get("opportunityHotsiteUrl") or program.get("opportunityInscriptionUrl")
        if not url:
            continue
        days = program.get("countFinishDays")
        if not isinstance(days, int) or days < 0:
            continue  # applications closed
        name = str(program.get("opportunityName") or "").strip()
        if name.lower() == "quem indica":
            continue  # the agency's referral campaign, not a program
        kind = str(program.get("hiringType") or "")
        place = _after_colon(program.get("opportunityLocations"))
        items.append(
            Opportunity(
                title=name,
                org=str(program.get("companyName") or "?").strip(),
                source=NAME,
                url=str(url),
                location="Brazil" if not place or place.lower().startswith("diversa") else f"{place}, Brazil",
                deadline=(today + timedelta(days=days)).isoformat(),
                description=f"{kind}. Área: {_after_colon(program.get('opportunityAreas'))}. "
                + html_to_text(str(program.get("opportunityDescription") or "")),
                # Trainee programs are often for recent graduates, so "maybe"; estágio is for students.
                hints=["unsure-student"] if "trainee" in kind.lower() else ["student"],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    return SourceResult(items=parse(post_json(API_URL, {"locale": "pt"}, headers={"Accept": "application/json"})), checked=1)
