"""Fundação Mudes: an estágio agency (agente de integração) in Rio de Janeiro,
Niterói, Maricá, the Baixada and Espírito Santo, with about 80 estágio vacancies
at small local employers on any day.

Its site lists every vacancy on one public page (robots.txt allows everything):

  GET https://mudes.org.br/resultado-vagas/
      -> cards: programme ("PROGRAMA ESTÁGIO", "PROGRAMA APRENDIZ", "VAGA
         PROFISSIONAL CLT"...), course ("ADMINISTRAÇÃO"), code, "BAIRRO - CIDADE",
         hours and bolsa ("Bolsa: R$1000.00")
  GET https://mudes.org.br/descricao-vaga?codigoOferta={code}
      -> semesters, activities, requirements, work model, benefits

The employer is not named publicly, so the org is "Fundação Mudes". We keep the
estágios for higher-education courses: the agency's technical-course and
high-school estágios, apprenticeships and CLT jobs are left out.
"""

from __future__ import annotations

import html
import re
from typing import Any

from ..http import get_text
from ..models import Opportunity
from ..pay import from_range
from ..textutil import html_to_text
from . import SourceResult
from .brtext import br_place, title_pt

NAME = "mudes"
LIST_URL = "https://mudes.org.br/resultado-vagas/"
JOB_URL = "https://mudes.org.br/descricao-vaga?codigoOferta={code}"
CARD = re.compile(r'<div class="vagas_destaque">(.*?)</div>', re.S)
SCHOOL_COURSE = re.compile(r"t[ée]cnic[oa]|\bt[ée]c\.|ensino m[ée]dio|n[íi]vel m[ée]dio|ensino fundamental|forma[çc][ãa]o de docentes", re.I)
WORK_MODELS = {"presencial": "on-site", "remoto": "remote", "híbrido": "hybrid", "hibrido": "hybrid"}
MAX_DETAILS = 100


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _field(pattern: str, fragment: str) -> str:
    match = re.search(pattern, fragment, re.S)
    return _text(match[1]) if match else ""


def parse_list(page: str) -> list[dict[str, str]]:
    """The estágio cards for higher-education courses: code, course, place, hours, bolsa."""
    cards = CARD.findall(page or "")
    if not cards and "vagas_destaque" not in (page or ""):
        raise ValueError("unexpected page from Mudes (no vacancy cards)")
    rows = []
    for card in cards:
        kind = _field(r'class="tiposup[^"]*">(.*?)</p>', card)
        course = _field(r'class="curso">(.*?)</p>', card)
        code = _field(r"codigoOferta=(\d+)", card) or _field(r"<strong>(\d+)</strong>", card)
        if "ESTÁGIO" not in kind.upper() or not code or SCHOOL_COURSE.search(course):
            continue
        place = _field(r'fa-map-marker-alt"></i>(.*?)</p>', card)
        hours = _field(r'fa-clock"></i>(.*?)</p>', card)
        bolsa = _field(r'class="bolsa">(.*?)</p>', card)
        rows.append({"code": code, "course": course, "place": place, "hours": hours, "bolsa": bolsa})
    return rows


def _bolsa(text: str) -> str:
    """ "Bolsa: R$1000.00" -> "R$1,000/mo" (Mudes writes the decimals with a point)."""
    match = re.search(r"R\$\s*([\d.,]+)", text)
    if not match:
        return ""
    raw = match[1]
    value = float(raw) if re.fullmatch(r"\d+(?:\.\d{1,2})?", raw) else float(raw.replace(".", "").replace(",", "."))
    return from_range(value, value, "BRL", "mo") if value >= 100 else ""


def _city(place: str) -> str:
    """ "JARDIM ATLÂNTICO - MARICÁ" or "JARDIM ATLÂNTICO, MARICÁ" -> "Maricá, RJ, Brazil"."""
    city = re.split(r"\s+-\s+|,\s*", place.strip())[-1] if place.strip() else ""
    return br_place(city)


def to_opportunity(row: dict[str, str], detail_page: str = "") -> Opportunity:
    """One estágio card plus (when we read it) its own page."""
    body = ""
    if detail_page:
        match = re.search(r'<div class="corpo_vaga">(.*?)<div class="linkvaga">', detail_page, re.S)
        body = match[1] if match else ""
    model_text = _field(r"Modelo de Trabalho:\s*</strong>(.*?)</p>", body).lower()
    model = WORK_MODELS.get(model_text, "")
    detail_place = _field(r'fa-map-marker-alt"></i>(.*?)</p>', body)
    course = title_pt(row["course"])
    pay = _bolsa(row["bolsa"])
    text = html_to_text(body) if body else f"Curso: {course}. Horário: {row['hours']}. {row['bolsa']}"
    return Opportunity(
        title=f"Estágio em {course}" if course else "Estágio",
        org="Fundação Mudes",
        source=NAME,
        url=JOB_URL.format(code=row["code"]),
        location=_city(detail_place or row["place"]) + (f" ({model})" if model else ""),
        remote=model == "remote",
        pay=pay,
        pay_from="field" if pay else "",
        description=text,
        hints=["student"],
    )


def parse(page: str, details: dict[str, str] | None = None) -> list[Opportunity]:
    """Every estágio on the list page; `details` maps vacancy code -> its own page."""
    details = details or {}
    return [to_opportunity(row, details.get(row["code"], "")) for row in parse_list(page)]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    result.checked += 1
    try:
        page = get_text(LIST_URL)
        rows = parse_list(page)
    except Exception as error:  # noqa: BLE001
        result.errors.append(f"list: {error}")
        return result
    details: dict[str, str] = {}
    for row in rows[:MAX_DETAILS]:
        result.checked += 1
        try:
            details[row["code"]] = get_text(JOB_URL.format(code=row["code"]))
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"vaga {row['code']}: {error}")
    result.items = [to_opportunity(row, details.get(row["code"], "")) for row in rows]
    return result
