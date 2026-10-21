"""TAQE: the young-talent job app of Rede Cidadã. Its public board
vagas.taqe.com.br carries the estágios of CIEE Rio (Servier, Carl Zeiss, TBG,
FGV, cartórios...) and of Rede Cidadã's own estágio programme, ~140 on any day,
next to many jovem aprendiz roles we leave out.

The board is built in the browser from public requests (robots.txt allows
everything; TAQE also publishes these vacancies as a Google-for-Jobs feed):

  GET https://api.taqe.com.br/v2/public/vacancies?pagination={"skip":0,"limit":100}
      -> every public vacancy: title ("SERVIER - ESTÁGIO - ADMINISTRAÇÃO OU
         DIREITO"), company key, hiring regime (["Estágio"], ["Jovem Aprendiz"]),
         bolsa (exact or a range), unit cities
  GET https://api.taqe.com.br/v2/public/vacancies/{company key}/{vacancy key}
      -> description, activities, requirements, schedule, creation date

Estágios for high-school and technical students ("Estágio em Ensino Médio",
"Estágio Técnico em Administração") are left out, as are apprenticeships.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from ..http import get_json
from ..labels import student_level
from ..models import Opportunity
from ..pay import from_range
from ..textutil import html_to_text, iso_date
from . import SourceResult
from .brtext import SCHOOL_TITLE, br_place, join_places, title_pt

NAME = "taqe"
API = "https://api.taqe.com.br/v2/public/vacancies"
LIST_URL = API + "?pagination={pagination}"
DETAIL_URL = API + "/{company}/{key}"
JOB_URL = "https://vagas.taqe.com.br/{company}/{key}"
PAGE_SIZE = 100
MAX_PAGES = 10
MAX_DETAILS = 200
SCHOOL = SCHOOL_TITLE
APPRENTICE = re.compile(r"aprendiz", re.I)
CONFIDENTIAL = "company-confidential"  # what the board shows instead of a hidden company
WORK_MODELS = {"workbench": "on-site", "presential": "on-site", "homeoffice": "remote", "remote": "remote", "hybrid": "hybrid"}


def is_student(vacancy: dict[str, Any]) -> bool:
    title = str(vacancy.get("office") or "")
    regimes = " ".join(vacancy.get("hiringRegimes") or [])
    if APPRENTICE.search(f"{title} {regimes}") or SCHOOL.search(title):
        return False
    return bool(re.search(r"est[áa]gi", regimes, re.I)) or student_level(title) == "yes"


def company_key(vacancy: dict[str, Any]) -> str:
    """The company part of the board address; hidden companies are "company-confidential"."""
    if vacancy.get("visibilityCompany") is False:
        return CONFIDENTIAL
    return str((vacancy.get("company") or {}).get("key") or CONFIDENTIAL)


def students(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance((payload or {}).get("data"), list):
        raise ValueError("unexpected answer from TAQE (no data list)")
    return [v for v in payload["data"] if is_student(v)]


def _pay(vacancy: dict[str, Any]) -> str:
    if vacancy.get("visibilityWage") is False:
        return ""
    kind = vacancy.get("wageType")
    if kind == "range" and vacancy.get("wageRange"):
        low, high = vacancy["wageRange"].get("min"), vacancy["wageRange"].get("max")
    elif kind == "exact":
        low = high = vacancy.get("wage")
    else:
        return ""  # "toCombine"
    try:
        low, high = float(low or 0), float(high or 0)
    except (TypeError, ValueError):
        return ""
    return from_range(low, high, "BRL", "mo") if max(low, high) >= 100 else ""


def _title(office: str) -> str:
    """ "SERVIER - ESTÁGIO - ADMINISTRAÇÃO OU DIREITO" -> "Servier - Estágio - Administração ou Direito"."""
    return title_pt(" ".join(office.split()))


def to_opportunity(vacancy: dict[str, Any], detail: dict[str, Any] | None) -> Opportunity:
    detail = detail or {}
    company = vacancy.get("company") or {}
    units = detail.get("unit") or vacancy.get("unit") or []
    places = [br_place(str((u.get("address") or {}).get("city") or ""), str((u.get("address") or {}).get("state") or ""))
              for u in units if (u.get("address") or {}).get("city")] if vacancy.get("showUnit", True) else []
    model = WORK_MODELS.get(str(detail.get("workingType") or "").lower(), "")
    parts = [html_to_text(str(detail.get("description") or ""))]
    if detail.get("activities"):
        parts.append("Atividades: " + " ".join(str(a) for a in detail["activities"]))
    if detail.get("requirements"):
        parts.append("Requisitos: " + " ".join(str(r) for r in detail["requirements"]))
    if detail.get("workload"):
        parts.append(f"Horário: {detail['workload']}")
    benefits = [str(b.get("title")) for b in vacancy.get("benefits") or [] if b.get("title")]
    if benefits:
        parts.append("Benefícios: " + "; ".join(benefits))
    pay = _pay(detail or vacancy) or _pay(vacancy)
    return Opportunity(
        title=_title(str(detail.get("office") or vacancy.get("office") or "")),
        org="Empresa confidencial" if company_key(vacancy) == CONFIDENTIAL else title_pt(
            str(company.get("fantasyName") or company.get("key") or "TAQE")),
        source=NAME,
        url=JOB_URL.format(company=company_key(vacancy), key=vacancy.get("key")),
        location=join_places(places) + (f" ({model})" if model else ""),
        remote=model == "remote",
        posted_date=iso_date(detail.get("createdAt")),
        pay=pay,
        pay_from="field" if pay else "",
        description="\n".join(p for p in parts if p),
        hints=["student"],
    )


def parse(payload: dict[str, Any], details: dict[str, dict[str, Any]]) -> list[Opportunity]:
    """Student vacancies on one list page; `details` maps vacancy key -> its own page."""
    return [to_opportunity(v, details.get(str(v.get("key")))) for v in students(payload)]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    headers = {"Accept": "application/json"}
    read = 0
    for page in range(MAX_PAGES):
        result.checked += 1
        pagination = quote(json.dumps({"skip": page * PAGE_SIZE, "limit": PAGE_SIZE}, separators=(",", ":")))
        try:
            payload = get_json(LIST_URL.format(pagination=pagination), headers=headers)
            wanted = students(payload)
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"list page {page}: {error}")
            break
        details: dict[str, dict[str, Any]] = {}
        for vacancy in wanted:
            if read >= MAX_DETAILS:
                break
            read += 1
            result.checked += 1
            key, company = str(vacancy.get("key")), company_key(vacancy)
            try:
                details[key] = get_json(DETAIL_URL.format(company=company, key=key), headers=headers)
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{company}/{key}: {error}")
        result.items.extend(to_opportunity(v, details.get(str(v.get("key")))) for v in wanted)
        total = int((payload.get("pagination") or {}).get("total") or 0)
        if (page + 1) * PAGE_SIZE >= total or not payload.get("data"):
            break
    return result
