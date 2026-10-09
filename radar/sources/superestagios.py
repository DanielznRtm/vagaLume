"""Super Estágios (superestagios.com.br): an estágio agency with thousands of
vacancies, strongest in the Federal District (Brasília), São Paulo and
Espírito Santo.

The site's vacancy list comes from one form POST that returns every active
vacancy at once (about 8 MB of JSON, preceded by an HTML comment):

  POST https://www.superestagios.com.br/index/comunicacaoAjax/vagas.php
       acao=listarAtivas&limite=0&geo=0&id_estado=&id_nivel_ensino=&...

Vacancies have no job title, so we write one from the accepted courses.
We keep the school levels listed in config/search.yaml (default: Superior).
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from ..http import post_form
from ..models import Opportunity
from ..pay import from_range
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "superestagios"
API_URL = "https://www.superestagios.com.br/index/comunicacaoAjax/vagas.php"
FORM = {"acao": "listarAtivas", "limite": "0", "geo": "0", "id_estado": "", "id_nivel_ensino": "",
        "id_curso": "", "id_vaga": "", "id_cidade": ""}
JOB_URL = "https://www.superestagios.com.br/index/vagasEstagioDestaque.php?i={key}"
WORKPLACE = {"PRESENCIAL": "on-site", "HIBRIDO": "hybrid", "HOME_OFFICE": "remote"}
SMALL_WORDS = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "ou"}


def _course_name(text: str) -> str:
    words = text.strip(" ,").lower().split()
    return " ".join(w if w in SMALL_WORDS and i else w.capitalize() for i, w in enumerate(words))


def parse(text: str, levels: list[str]) -> list[Opportunity]:
    start = text.find("[")
    if start < 0:
        raise ValueError("unexpected answer from Super Estágios (no JSON list)")
    items: list[Opportunity] = []
    for job in json.loads(text[start:]):
        level = str(job.get("nivel_ensino") or "")
        if levels and not any(level.startswith(wanted) for wanted in levels):
            continue
        courses = [_course_name(c) for c in (job.get("curso1"), job.get("curso2"), job.get("curso3")) if c and c.strip(" ,")]
        company = str(job.get("nome_fantasia") or "").strip()
        if not company or company.upper() == "CONFIDENCIAL":
            company = "Empresa confidencial"
        workplace = WORKPLACE.get(str(job.get("modalidade") or "").upper(), "")
        place = ", ".join(p for p in (job.get("cidade"), job.get("sgl_estado")) if p)
        key = base64.b64encode(f"{job['id_vaga']}@@{job.get('idEmp') or job.get('id_empresa')}".encode()).decode()
        try:
            bolsa = float(job.get("valor") or 0)
        except ValueError:
            bolsa = 0
        details = [str(job.get("atividades") or "").strip(), str(job.get("requisito") or "").strip(), str(job.get("beneficios") or "").strip()]
        items.append(
            Opportunity(
                title="Estágio em " + ", ".join(courses) if courses else "Estágio",
                org=company,
                source=NAME,
                url=JOB_URL.format(key=key),
                location=(f"{place}, Brazil" if place else "Brazil") + (f" ({workplace})" if workplace else ""),
                remote=workplace == "remote",
                pay=from_range(bolsa, bolsa, "BRL", "mo") if bolsa else "",
                description="\n".join(d for d in details if d),
                hints=["student"],  # the agency only lists estágio
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    levels = config.get("search", {}).get("superestagios_levels") or ["Superior"]
    items = parse(post_form(API_URL, FORM, timeout=60), levels)
    return SourceResult(items=items, checked=1)
