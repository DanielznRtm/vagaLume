"""CIEE (Centro de Integração Empresa-Escola): Brazil's biggest estágio agency.

The vacancy search on portal.ciee.org.br calls a public JSON API that we call
directly (Spring-style pages, 0-based):

  https://api.ciee.org.br/vagas/vitrine-vaga/publicadas?page=N&size=1000
      &sort=codigoVaga,desc&tipoVaga=ESTAGIO&nivelEnsino=SU

`nivelEnsino` is the school level: SU = higher education (graduação),
TE = technical, EM = high school. config/search.yaml picks the levels.
CIEE vacancies have no job title, so we write one from the professional
area ("Estágio em Informática"); the activities become the description.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..models import Opportunity
from ..pay import from_range
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "ciee"
API_URL = "https://api.ciee.org.br/vagas/vitrine-vaga/publicadas?"
JOB_URL = "https://portal.ciee.org.br/quero-uma-vaga/?codigoVaga={code}"
PAGE_SIZE = 1000
MAX_PAGES = 10
LEVEL_NAMES = {"SU": "", "TE": " (técnico)", "EM": " (ensino médio)"}
PERIODS = {"mensal": "mo", "hora": "hr", "semanal": "wk"}


def _pay(job: dict[str, Any]) -> str:
    period = PERIODS.get(str(job.get("tipoAuxilioBolsa") or "mensal").lower(), "mo")
    if job.get("bolsaAuxilio"):
        return from_range(job["bolsaAuxilio"], job["bolsaAuxilio"], "BRL", period)
    return from_range(job.get("bolsaAuxilioDe"), job.get("bolsaAuxilioAte"), "BRL", period)


def parse(data: dict[str, Any]) -> list[Opportunity]:
    if not isinstance(data, dict) or not isinstance(data.get("content"), list):
        raise ValueError("unexpected answer from CIEE (no 'content' list)")
    items: list[Opportunity] = []
    for job in data["content"]:
        area = str(job.get("areaProfissional") or job.get("areaAtuacao") or "").strip()
        level = LEVEL_NAMES.get(str(job.get("nivelEscolar") or ""), "")
        place = job.get("local") or {}
        city = ", ".join(p for p in (place.get("cidade"), place.get("uf")) if p)
        semesters = job.get("requisitos") or {}
        activities = "; ".join(str(a) for a in job.get("atividades") or [])
        description = f"Área: {area}. Atividades: {activities}. Empresa: {job.get('descricao') or ''}."
        if semesters.get("semestreInicio"):
            description += f" Do {semesters['semestreInicio']}º ao {semesters.get('semestreFinal') or '?'}º semestre."
        items.append(
            Opportunity(
                title=(f"Estágio em {area}" if area else "Estágio") + level,
                org=str(job.get("nomeEmpresa") or "Empresa não informada").strip(),
                source=NAME,
                url=JOB_URL.format(code=job["codigoVaga"]),
                location=f"{city}, Brazil" if city else "Brazil",
                pay=_pay(job),
                description=description,
                hints=["student"],
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for level in config.get("search", {}).get("ciee_levels") or ["SU"]:
        for page in range(MAX_PAGES):
            result.checked += 1
            params = {"page": page, "size": PAGE_SIZE, "sort": "codigoVaga,desc", "tipoVaga": "ESTAGIO", "nivelEnsino": level}
            try:
                data = get_json(API_URL + urlencode(params), headers={"Accept": "application/json"})
                result.items.extend(parse(data))
            except Exception as error:  # noqa: BLE001
                log.warning("CIEE %s page %d failed: %s", level, page, error)
                result.errors.append(f"{level} page {page}: {error}")
                break
            if data.get("last", True) or not data["content"]:
                break
    return result
