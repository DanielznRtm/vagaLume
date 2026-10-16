"""TOTVS RH Atração de Talentos: the job-board system TOTVS sells (and uses for
its own roles, "Vem pra TOTVS").

Each company's board is one public HTML page with every open role in it:

  GET https://atracaodetalentos.totvs.app/{tenant}/extended

Every role is a <div class="index__job-opportunities__grid__item"> whose data-*
attributes hold the title, the position ("ESTAGIARIO"), the department, the
city and state and the job code. We keep the student ones (estágio / trainee
position or title). The page says nothing about the bolsa or dates. TOTVS's
yearly estágio program itself runs on Academia do Universitário
(radar/sources/academia.py). The boards are in config/companies.yaml, section
`totvs_rh`.
"""

from __future__ import annotations

import html
import re
from typing import Any

from ..http import get_text
from ..labels import student_level
from ..models import Opportunity
from . import SourceResult

NAME = "totvs_rh"
BASE = "https://atracaodetalentos.totvs.app"
LIST_URL = BASE + "/{tenant}/extended"
_ITEM = re.compile(r'<div class="index__job-opportunities__grid__item"(.*?)>', re.S)
_ATTR = re.compile(r'data-([a-z-]+)="([^"]*)"')
STUDENT_POSITION = re.compile(r"estagi|trainee", re.I)
APPRENTICE = re.compile(r"aprendiz", re.I)


def parse(page: str, board: dict[str, Any]) -> list[Opportunity]:
    if "index__job-opportunities" not in page:
        raise ValueError("unexpected answer from TOTVS RH (no job list in the page)")
    items: list[Opportunity] = []
    for match in _ITEM.finditer(page):
        data = {key: html.unescape(value).strip() for key, value in _ATTR.findall(match.group(1))}
        title = re.sub(r"\s+", " ", data.get("title", ""))
        position = data.get("position-name", "")
        if APPRENTICE.search(f"{title} {position}"):
            continue
        if not STUDENT_POSITION.search(position) and student_level(title) != "yes":
            continue
        department = data.get("department-name", "")
        if title.upper() == title and department:
            # Many titles are just the position ("ESTAGIÁRIO"): say where.
            area = re.split(r"\s+-\s+", department)[-2:] if " - " in department else [department]
            title = f"{title.capitalize()} – {' - '.join(area).title()}"
        city, state = data.get("city-name", ""), data.get("state-small-name", "")
        remote = data.get("hide-location") == "True" or not city
        location = "Remote, Brazil" if remote else f"{city}, {state}, Brazil" if state else f"{city}, Brazil"
        items.append(
            Opportunity(
                title=title,
                org=str(board.get("name") or board["tenant"]),
                source=NAME,
                url=f"{BASE}{data['page-url']}" if data.get("page-url") else LIST_URL.format(tenant=board["tenant"]),
                location=location,
                remote=remote,
                description=f"{position}. {department}".strip(". "),
                hints=["student"] if STUDENT_POSITION.search(position) else [],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for board in config.get("companies", {}).get("totvs_rh") or []:
        result.checked += 1
        try:
            result.items.extend(parse(get_text(LIST_URL.format(tenant=board["tenant"])), board))
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"{board.get('name')}: {error}")
    return result
