"""Central de Estágios do Paraná: the paid estágios of the Paraná state
government (secretarias, state universities UEL, UEM, Unicentro, Unioeste,
Celepar, Polícia Civil, Funsaúde...), about 200 open on any day, each with its
own registration window.

The public search page answers a plain GET (no login; the host has no
robots.txt), linked from https://www.centraldeestagio.pr.gov.br:

  GET https://www.ceestagios.pr.gov.br/cee/jsp/frm_busca_vagas.jsp?NivelEnsino=S&TipoOferta=1&Submit=Prosseguir
      -> one table row per vacancy: code, level, course, órgão, unit, city,
         first and last day of the offer. NivelEnsino S = graduação, P = pós.
  GET https://www.ceestagios.pr.gov.br/cee/jsp/frm_cons_detalhe_vaga.jsp?codoferta={code}
      -> semesters ("1-4"), bolsa ("R$ 10,00 por hora"), hours and activities.
         The page also names the HR staff and supervisor; we leave those out.

Applying needs a free student account on the Central de Estágio site.
"""

from __future__ import annotations

import html
import re
from typing import Any

from ..http import get_text
from ..models import NO_DEADLINE, Opportunity
from ..pay import from_range, parse_number
from . import SourceResult
from .brtext import br_place, title_pt

NAME = "parana"
BASE = "https://www.ceestagios.pr.gov.br/cee/jsp/"
LIST_URL = (BASE + "frm_busca_vagas.jsp?NivelEnsino={level}&CodCategoria=&CodCurso=&CodOrgao=&CodCidade=&Portador="
            "&TipoOferta=1&Submit=Prosseguir")
DETAIL_URL = BASE + "frm_cons_detalhe_vaga.jsp?codoferta={code}"
LEVELS = {"S": "", "P": " (pós-graduação)"}
ROW = re.compile(r"<tr>\s*<td width=\"4%\">(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
MAX_DETAILS = 300


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


def _date(text: str) -> str:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text or "")
    return f"{match[3]}-{match[2]}-{match[1]}" if match else ""


def parse_list(page: str) -> list[dict[str, str]]:
    """The vacancy rows of one search result page."""
    if "frm_busca_vagas" not in (page or ""):
        raise ValueError("unexpected page from the Central de Estágios (no search form)")
    rows = []
    for match in ROW.finditer(page):
        row = "<td width=\"4%\">" + match[1]
        code = (re.search(r"codoferta=(\d+)", row) or [None, ""])[1]
        cells = [_text(c) for c in CELL.findall(row)]
        if not code or len(cells) < 8:
            continue  # the header row
        rows.append({"code": code, "level": cells[1], "course": cells[2], "org": cells[3], "unit": cells[4],
                     "city": cells[5], "start": _date(cells[6]), "end": _date(cells[7])})
    return rows


def _detail_field(page: str, label: str) -> str:
    """The value after a bold label ("Bolsa Auxílio Valor:") on the detail page."""
    match = re.search(rf"<B>\s*{label}\s*:?\s*(?:<BR>)?\s*</B>\s*:?\s*(?:<BR>)?(.*?)</P>", page, re.S | re.I)
    return _text(match[1]) if match else ""


def _pay(text: str) -> str:
    """ "R$ 10,00 por hora" -> "R$10/hr"; "R$ 1.200,00" -> "R$1,200/mo"."""
    match = re.search(r"R\$\s*([\d.,]+)", text)
    value = parse_number(match[1]) if match else None
    if not value:
        return ""
    period = "hr" if re.search(r"hora", text, re.I) else "mo"
    return from_range(value, value, "BRL", period) if period == "hr" or value >= 100 else ""


def to_opportunity(row: dict[str, str], detail: str = "", level: str = "S") -> Opportunity:
    course = title_pt(row["course"])
    unit = title_pt(row["unit"])
    org = row["org"].strip()
    pay = _pay(_detail_field(detail, "Bolsa Aux(?:&iacute;|í)lio Valor")) if detail else ""
    semesters = _detail_field(detail, "Per(?:&iacute;|í)odo") if detail else ""
    hours = _detail_field(detail, "Hor(?:&aacute;|á)rio de est(?:&aacute;|á)gio") if detail else ""
    activities = _detail_field(detail, "Atividades a serem desenvolvidas") if detail else ""
    text = [f"Estágio remunerado no Governo do Paraná: {org}, {unit}.",
            f"Curso: {course}" + (f", períodos {semesters}." if semesters else "."),
            f"Inscrições de {row['start']} a {row['end']} pela Central de Estágios (cadastro do estudante)." if row["start"] else "",
            f"Horário: {hours}." if hours else "",
            f"Atividades: {activities}" if activities else "",
            f"Bolsa auxílio: {_detail_field(detail, 'Bolsa Aux(?:&iacute;|í)lio Valor')}" if pay else ""]
    return Opportunity(
        title=f"Estágio em {course}{LEVELS.get(level, '')} - {unit}" if unit else f"Estágio em {course}",
        org=f"{org} (Governo do Paraná)",
        source=NAME,
        url=DETAIL_URL.format(code=row["code"]),
        location=br_place(row["city"], "PR"),
        posted_date=row["start"],
        deadline=row["end"] or NO_DEADLINE,
        pay=pay,
        pay_from="field" if pay else "",
        description="\n".join(t for t in text if t),
        hints=["student"],
    )


def parse(page: str, details: dict[str, str] | None = None, level: str = "S") -> list[Opportunity]:
    """Every vacancy on a result page; `details` maps offer code -> its detail page."""
    details = details or {}
    return [to_opportunity(row, details.get(row["code"], ""), level) for row in parse_list(page)]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    read = 0
    for level in LEVELS:
        result.checked += 1
        try:
            rows = parse_list(get_text(LIST_URL.format(level=level)))
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"level {level}: {error}")
            continue
        for row in rows:
            detail = ""
            if read < MAX_DETAILS:
                read += 1
                result.checked += 1
                try:
                    detail = get_text(DETAIL_URL.format(code=row["code"]))
                except Exception as error:  # noqa: BLE001
                    result.errors.append(f"oferta {row['code']}: {error}")
            result.items.append(to_opportunity(row, detail, level))
    return result
