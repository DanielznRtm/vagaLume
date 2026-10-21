"""CIEE public-sector selection notices ("Processos Seletivos Públicos"): the
estágio programs of courts, ministries, prefeituras, câmaras, state companies
and federal agencies (TRF 1, TRT 2/3/15, TRE-MS, BNDES, FINEP, Fiocruz, SEFAZ-SP,
Prefeitura de São Paulo...) that CIEE runs as an edital with a deadline.

The page https://pp.ciee.org.br/vitrine/processos-seletivos/publico is built
in the browser from two public requests (no login; api-pp has no robots.txt):

  POST https://api-pp.ciee.org.br/api/editais/vitrine?page=N&size=100   body {}
      -> every edital: id, órgão, name ("EDITAL 02/2026 (NÍVEL SUPERIOR)"),
         status (ABERTO, EM_BREVE, EM_ANDAMENTO, FINALIZADO...). Open ones come first.
  GET  https://api-pp.ciee.org.br/api/editais/{id}
      -> courses with their school level (SU = graduação, PG = pós, TE, EM...),
         cities, registration dates (cronograma INSCRICAO), requirements, bolsas

Each edital becomes one item, linked to its page on pp.ciee.org.br. We keep the
ones open now or opening soon, with at least one higher-education course;
Jovem Aprendiz pre-registrations and editais only for high-school or technical
students are left out.
"""

from __future__ import annotations

import re
from typing import Any

from ..http import get_json, post_json
from ..models import NO_DEADLINE, Opportunity
from ..pay import from_range
from ..textutil import html_to_text, iso_date
from . import SourceResult
from .brtext import br_place, join_places, title_pt

NAME = "ciee_editais"
API = "https://api-pp.ciee.org.br/api/editais"
LIST_URL = API + "/vitrine?page={page}&size=100"
DETAIL_URL = API + "/{id}"
PAGE_URL = "https://pp.ciee.org.br/vitrine/{id}/detalhe"
OPEN = {"ABERTO": "", "EM_BREVE": "Inscrições em breve. "}
HIGHER = {"SU", "PG"}  # graduação, pós-graduação
APPRENTICE = re.compile(r"aprendiz", re.I)
PERIODS = {"MES": "mo", "HORA": "hr", "SEMANA": "wk"}
MAX_PAGES = 5
MAX_DETAILS = 120


def open_editais(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The editais in one list page that are open or opening soon (no Jovem Aprendiz)."""
    if not isinstance((payload or {}).get("content"), list):
        raise ValueError("unexpected answer from CIEE editais (no content list)")
    keep = []
    for edital in payload["content"]:
        name = f"{(edital.get('orgao') or {}).get('nome') or ''} {edital.get('identificacao') or ''}"
        if edital.get("status") in OPEN and edital.get("ativo") and not APPRENTICE.search(name):
            keep.append(edital)
    return keep


def _semester(text: str) -> str:
    """ "TERCEIRO_SEMESTRE" -> "3º semestre"."""
    words = {"PRIMEIRO": 1, "SEGUNDO": 2, "TERCEIRO": 3, "QUARTO": 4, "QUINTO": 5, "SEXTO": 6, "SETIMO": 7,
             "OITAVO": 8, "NONO": 9, "DECIMO": 10, "PRIMEIRA": 1, "SEGUNDA": 2, "TERCEIRA": 3}
    number, _, unit = str(text or "").partition("_")
    return f"{words[number]}º {unit.lower()}" if number in words and unit else ""


def _courses(detail: dict[str, Any]) -> list[dict[str, Any]]:
    seen: dict[int, dict[str, Any]] = {}
    for course in detail.get("editalCursos") or []:
        seen.setdefault((course.get("curso") or {}).get("id") or id(course), course)
    for link in detail.get("vinculoLocaisCursos") or []:
        for course in link.get("listCursos") or []:
            seen.setdefault((course.get("curso") or {}).get("id") or id(course), course)
    return list(seen.values())


def _course_text(course: dict[str, Any]) -> str:
    name = title_pt(" ".join(str((course.get("curso") or {}).get("descricao") or "").split()))
    low, high = _semester(course.get("periodoMinimo")), _semester(course.get("periodoMaximo"))
    return f"{name} ({low} ao {high})" if low and high else name


def _places(detail: dict[str, Any]) -> str:
    places = [br_place(str(place.get("cidade") or ""), str(place.get("uf") or ""))
              for link in detail.get("vinculoLocaisCursos") or [] for place in link.get("listLocais") or []
              if place.get("cidade")]
    if not places:
        places = [br_place("", uf) for uf in detail.get("ufs") or []]
    return join_places(places)


def _pay(detail: dict[str, Any]) -> str:
    """The bolsa table, when the edital fills it in (most say it only in the PDF)."""
    rows = []
    for bolsa in detail.get("bolsasAuxilio") or []:
        level = ((bolsa.get("editalCurso") or {}).get("curso") or {}).get("nivel") or (
            ((bolsa.get("editalNivel") or {}).get("nivel") or {}).get("sigla"))
        if level and level not in HIGHER:
            continue
        try:
            value = float(str(bolsa.get("valor")).replace(",", "."))
        except ValueError:
            continue
        rows.append((value, PERIODS.get(str(bolsa.get("periodo") or "MES"), "mo")))
    if not rows:
        return ""
    period = rows[0][1]
    values = [v for v, p in rows if p == period and v > 0]
    return from_range(min(values), max(values), "BRL", period) if values else ""


def to_opportunity(edital: dict[str, Any], detail: dict[str, Any] | None) -> Opportunity | None:
    """One open edital (from the list) with its own page; None when it is not for university students."""
    detail = detail or {}
    courses = _courses(detail)
    levels = {(c.get("curso") or {}).get("nivel") for c in courses}
    if courses and not levels & HIGHER:
        return None  # only high-school / technical courses
    org = title_pt(str((detail.get("orgao") or edital.get("orgao") or {}).get("nome") or "CIEE"), acronym_tail=True)
    org = org.replace(" | ", " - ")
    name = title_pt(str(detail.get("identificacao") or edital.get("identificacao") or "").strip())
    if APPRENTICE.search(f"{org} {name}"):
        return None
    title = f"Processo seletivo de estágio: {name}" if name else "Processo seletivo de estágio"
    registration = next((c for c in detail.get("cronogramas") or [] if c.get("tipoFase") == "INSCRICAO"), {})
    higher = [_course_text(c) for c in courses if (c.get("curso") or {}).get("nivel") in HIGHER]
    status = OPEN.get(str(detail.get("status") or edital.get("status")), "")
    opens = iso_date(registration.get("dataInicio"))
    text = [status + (f"Inscrições de {opens} a {iso_date(registration.get('dataFim'))}." if opens else ""),
            "Cursos (nível superior): " + "; ".join(higher[:40]) + (f"; +{len(higher) - 40}" if len(higher) > 40 else "") if higher else "",
            *(html_to_text(str(f.get("descricaoFase") or "")) for f in detail.get("fases") or []),
            html_to_text(str((detail.get("requisitos") or {}).get("descricaoRequisito") or ""))]
    pay = _pay(detail)
    location = _places(detail)
    if location == "Brazil" and (uf := re.search(r"\s-\s([A-Z]{2})$", org)):
        location = br_place("", uf[1])  # "Departamento Regional de Saúde de Campinas - DRS VII - SP"
    return Opportunity(
        title=title,
        org=org,
        source=NAME,
        url=PAGE_URL.format(id=edital["id"]),
        location=location,
        posted_date=opens,
        deadline=iso_date(registration.get("dataFim")) or NO_DEADLINE,
        pay=pay,
        pay_from="field" if pay else "",
        description="\n".join(t for t in text if t),
        hints=["student"],
    )


def parse(payload: dict[str, Any], details: dict[str, dict[str, Any]]) -> list[Opportunity]:
    """The open editais of one list page, with their own pages (id -> detail)."""
    return [opp for e in open_editais(payload) if (opp := to_opportunity(e, details.get(str(e["id"]))))]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    headers = {"Accept": "application/json"}
    read = 0
    for page in range(MAX_PAGES):
        result.checked += 1
        try:
            payload = post_json(LIST_URL.format(page=page), {}, headers=headers)
            wanted = open_editais(payload)
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"list page {page}: {error}")
            break
        details: dict[str, dict[str, Any]] = {}
        for edital in wanted:
            if read >= MAX_DETAILS:
                break
            read += 1
            result.checked += 1
            try:
                details[str(edital["id"])] = get_json(DETAIL_URL.format(id=edital["id"]), headers=headers)
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"edital {edital['id']}: {error}")
        result.items.extend(o for e in wanted if (o := to_opportunity(e, details.get(str(e["id"])))))
        # Open and upcoming editais come first; a page with none of them means the rest are closed.
        if not wanted or payload.get("last"):
            break
    return result
