"""FAPESP Oportunidades: research grants (bolsas) inside FAPESP-funded
projects in São Paulo state, from undergraduate research (iniciação
científica) to doctorate.

https://fapesp.br/oportunidades/ lists every open posting on one static page
(each one twice, in Portuguese and English; we read the Portuguese copy).
The grant type is a CSS class "tipo_N" on each item.

We keep the types meant for students:
  * Iniciação Científica and TT-I / TT-II (training grants for undergrads and
    technical students),
  * Mestrado (for master's students),
  * Doutorado and Doutorado Direto (flagged "PhD-level?").
Postdoc and TT-III and above need a finished degree, so they are left out.
Undergrad postings are rare and close fast, which is why we read this page
every day.
"""

from __future__ import annotations

import html
import re
from typing import Any

from ..http import get_text
from ..models import NO_DEADLINE, Opportunity
from . import SourceResult

NAME = "fapesp"
LIST_URL = "https://fapesp.br/oportunidades/"
ITEM_URL = "https://fapesp.br/oportunidades/x/{id}/"  # redirects to the posting
# Grant types (from the form on fapesp.br/oportunidades/publique/) -> how we label them.
STUDENT_TYPES = {11: "Iniciação Científica", 4: "TT-I", 5: "TT-II"}
GRAD_TYPES = {3: "Mestrado", 2: "Doutorado", 12: "Doutorado Direto"}

_ITEM = re.compile(r'<li class="box_col aberta ([^"]*?) pt">(.*?)</li>', re.S)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _field(label: str, body: str) -> str:
    match = re.search(r"<strong>" + label + r"[^<]*</strong>(.*?)<br>", body, re.S)
    return _clean(match.group(1)) if match else ""


def parse(page: str) -> list[Opportunity]:
    if "box_col" not in page:
        raise ValueError("no postings found - FAPESP may have changed its page")
    items: list[Opportunity] = []
    for match in _ITEM.finditer(page):
        classes, body = match.group(1).split(), match.group(2)
        kind = next((int(c[5:]) for c in classes if c.startswith("tipo_") and c[5:].isdigit()), 0)
        if kind not in STUDENT_TYPES and kind not in GRAD_TYPES:
            continue
        link = re.search(r'<a href="([^"]+)"', body)
        title = re.search(r'<strong class="title">(.*?)</strong>', body, re.S)
        if not (link and title):
            continue
        posting_id = re.search(r"/(\d+)/?$", link.group(1))
        if not posting_id:
            continue
        deadline = re.search(r"<strong>Inscri\S* at\S*:</strong>\s*(\d{2})/(\d{2})/(\d{4})", body)
        summary = re.search(r'<span class="text-resumo">(.*?)</span>', body, re.S)
        kind_name = STUDENT_TYPES.get(kind) or GRAD_TYPES[kind]
        name = _clean(title.group(1))
        if kind_name.lower() not in name.lower():
            name += f" ({kind_name})"
        city = _field("Cidade", body)
        items.append(
            Opportunity(
                title=name,
                org=_field("Institui", body) or "FAPESP",
                source=NAME,
                url=ITEM_URL.format(id=posting_id.group(1)),
                location=f"{city}, SP, Brazil" if city else "São Paulo, Brazil",
                deadline=f"{deadline.group(3)}-{deadline.group(2)}-{deadline.group(1)}" if deadline else NO_DEADLINE,
                description=_clean(summary.group(1)) if summary else "",
                hints=["student"],
                preset={"area": "research", **({"warnings": ["PhD-level?"]} if kind in (2, 12) else {})},
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    return SourceResult(items=parse(get_text(LIST_URL)), checked=1)
