"""The estágio murals of USP units built on USP's open-source "estagios" system
(github.com/uspdev/estagios), starting with FFLCH's (estagios.fflch.usp.br):
~20 vacancies at a time for letras, história, geografia, relações
internacionais... posted by schools, courts, publishers and USP institutes.

Both pages are public (robots.txt allows everything):

  GET https://{host}/                 -> the "Mural de Vagas": title, weekly hours, bolsa, link
  GET https://{host}/vagas/{id}       -> description, benefits, schedule, "Divulgar até" date
                                        and how to apply (usually an e-mail)

Hosts come from config/companies.yaml, section `usp_estagios` (a list of
{host, name}); FFLCH's is the default. The murals don't say where the estágio
is; nearly all are in São Paulo, so that is the location.
"""

from __future__ import annotations

import html
import re
from typing import Any

from ..http import get_text
from ..labels import student_level
from ..models import NO_DEADLINE, Opportunity
from ..pay import from_range, parse_number
from ..textutil import html_to_text
from . import SourceResult

NAME = "usp_estagios"
DEFAULT_BOARDS = [{"host": "estagios.fflch.usp.br", "name": "FFLCH-USP"}]
ROW = re.compile(r"<td>\s*<h4>(.*?)</h4>(.*?)</td>\s*<td>\s*<a href=\"(/vagas/\d+)\"", re.S)
MAX_DETAILS = 60


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


def parse_list(page: str) -> list[dict[str, str]]:
    if "Mural de Vagas" not in (page or "") and "/vagas/" not in (page or ""):
        raise ValueError("unexpected page (no Mural de Vagas)")
    rows = []
    for title, rest, path in ROW.findall(page):
        bolsa = re.search(r"Valor da bolsa:\s*R\$\s*([\d.,]+)", rest)
        hours = re.search(r"Carga hor[áa]ria semanal:\s*(\d+)", rest, re.I)
        rows.append({"title": _text(title), "path": path, "bolsa": bolsa[1] if bolsa else "",
                     "hours": hours[1] if hours else ""})
    return rows


def _field(page: str, label: str) -> str:
    """The text after "<b>Label:</b>" up to the next line break tag on a vacancy page."""
    match = re.search(rf"<b>\s*{label}:?\s*</b>(.*?)(?:<br\s*/?>|</div>)", page, re.S | re.I)
    return html_to_text(match[1]).replace("\n", " ").strip() if match else ""


def _date(text: str) -> str:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    return f"{match[3]}-{match[2]}-{match[1]}" if match else ""


def to_opportunity(row: dict[str, str], detail: str, board: dict[str, Any]) -> Opportunity:
    title = _field(detail, "Título da Vaga") if detail else ""
    title = title or row["title"]
    amount = parse_number(row["bolsa"]) if row["bolsa"] else None
    hours = int(row["hours"]) if row["hours"] else 0
    # "R$ 35" for one weekly hour is an hourly rate; a mural amount for 6+ weekly hours is monthly.
    pay = ""
    if amount and amount >= 100:
        pay = from_range(amount, amount, "BRL", "mo")
    parts = [f"{label}: {value}" for label in ("Descrição da Vaga", "Benefícios", "Carga Horária Semanal", "Horário do Estágio",
                                               "Contato para vaga") if detail and (value := _field(detail, label))]
    if not parts:
        parts = [f"Carga horária semanal: {hours} horas." if hours else "", f"Bolsa: R$ {row['bolsa']}" if row["bolsa"] else ""]
    deadline = _date(_field(detail, "Divulgar até")) if detail else ""
    return Opportunity(
        title=title,
        org=str(board.get("name") or board["host"]),
        source=NAME,
        url=f"https://{board['host']}{row['path']}",
        location="São Paulo, SP, Brazil",
        deadline=deadline or NO_DEADLINE,
        pay=pay,
        pay_from="field" if pay else "",
        description="\n".join(p for p in parts if p),
        # A mural of the unit's estágio office: everything is meant for its students.
        hints=["student"] if student_level(title) == "yes" else ["unsure-student"],
    )


def parse(page: str, details: dict[str, str], board: dict[str, Any]) -> list[Opportunity]:
    """The vacancies on a mural; `details` maps "/vagas/{id}" -> that vacancy's page."""
    return [to_opportunity(row, details.get(row["path"], ""), board) for row in parse_list(page)]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for board in config.get("companies", {}).get("usp_estagios") or DEFAULT_BOARDS:
        result.checked += 1
        try:
            rows = parse_list(get_text(f"https://{board['host']}/"))
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"{board.get('name')}: {error}")
            continue
        details: dict[str, str] = {}
        for row in rows[:MAX_DETAILS]:
            result.checked += 1
            try:
                details[row["path"]] = get_text(f"https://{board['host']}{row['path']}")
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{board.get('name')}: {row['path']}: {error}")
        result.items.extend(to_opportunity(row, details.get(row["path"], ""), board) for row in rows)
    return result
