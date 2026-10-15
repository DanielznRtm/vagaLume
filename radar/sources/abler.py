"""Abler: the job-board system some Brazilian companies use for their estágio
programs (Vale's "Estágio na Vale" is the big one, with ~50 roles).

Each company's board has a public JSON route (robots.txt allows it):

  GET https://{subdomain}.abler.com.br/api_v/v1/vagas?page=N   (Accept: application/json)

15 roles per page, with title, description, bolsa ("R$ 1.500,00"), location
and contract type ("Estagiário"). The boards are in config/companies.yaml,
section `abler`.
"""

from __future__ import annotations

import re
from typing import Any

from ..http import get_json
from ..labels import student_level
from ..models import Opportunity
from ..pay import from_range, parse_number
from ..textutil import html_to_text
from . import SourceResult

NAME = "abler"
API_URL = "https://{subdomain}.abler.com.br/api_v/v1/vagas?page={page}"
MAX_PAGES = 20


def _date(text: str) -> str:
    """"01/10/2026" -> "2026-10-01"."""
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text.strip())
    return f"{match[3]}-{match[2]}-{match[1]}" if match else ""


def parse(payload: dict[str, Any], board: dict[str, Any]) -> list[Opportunity]:
    vacancies = (payload or {}).get("vacancies") or {}
    if not isinstance(vacancies.get("data"), list):
        raise ValueError("unexpected answer from Abler (no vacancies list)")
    items: list[Opportunity] = []
    for job in vacancies["data"]:
        info = job.get("attributes") or {}
        title = str(info.get("title") or "").strip()
        regime = str(info.get("contracting_regime") or "")
        if not re.search(r"estagi|trainee", regime, re.I) and student_level(title) != "yes":
            continue
        amount = parse_number(str(info.get("salary") or "").replace("R$", ""))
        place = str(info.get("location") or "").strip()
        items.append(
            Opportunity(
                title=title,
                org=str(board.get("name") or board["subdomain"]),
                source=NAME,
                url=str((job.get("links") or {}).get("vacancy_url") or info.get("short_url")),
                location=f"{place}, Brazil" if place else "Brazil",
                posted_date=_date(str(info.get("republished_at") or info.get("created_at") or "")),
                pay=from_range(amount, amount, "BRL", "mo") if amount else "",
                description=html_to_text(str(info.get("description") or "")),
                hints=["student"] if re.search(r"estagi", regime, re.I) else ["unsure-student"],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for board in config.get("companies", {}).get("abler") or []:
        for page in range(1, MAX_PAGES + 1):
            result.checked += 1
            try:
                payload = get_json(API_URL.format(subdomain=board["subdomain"], page=page), headers={"Accept": "application/json"})
                result.items.extend(parse(payload, board))
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{board.get('name')}: page {page}: {error}")
                break
            if not (payload.get("pagy") or {}).get("next"):
                break
    return result
