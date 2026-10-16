"""Academia do Universitário: the estágio platform behind the programs of
Braskem, Volkswagen, Ipiranga, Techfin, TOTVS and others, and single estágio
roles at ONS, Vibra, RD Saúde...

Its job site (vagas.academiadouniversitario.com.br) is built in the browser
from public requests, no login:

  GET https://api.ats.academiadouniversitario.com.br/public/programs?page=N&pageSize=100
  GET https://api.ats.academiadouniversitario.com.br/public/jobs?page=N&pageSize=100
      -> company, title, main city, bolsa range, work models, graduation window
  GET .../public/programs/{slug}   and   .../public/jobs/{id}
      -> every city (with the state for jobs), application dates and description

Everything there is an estágio (it is an estágio-only platform); programs are
kept as one item each (Braskem's has 118 roles behind one application).
"""

from __future__ import annotations

from typing import Any

from ..http import get_json
from ..labels import student_level
from ..models import NO_DEADLINE, Opportunity
from ..pay import from_range
from ..places import city_state
from ..textutil import html_to_text, iso_date
from . import SourceResult

NAME = "academia"
API = "https://api.ats.academiadouniversitario.com.br/public"
LIST_URL = API + "/{kind}?page={page}&pageSize=100"
DETAIL_URL = API + "/{kind}/{key}"
SITE = "https://vagas.academiadouniversitario.com.br"
WORK_MODELS = {"HYBRID": "hybrid", "PRESENTIAL": "on-site", "REMOTE": "remote"}
MAX_PAGES = 5
MAX_DETAILS = 150


def _pay(salary: dict[str, Any] | None) -> str:
    salary = salary or {}
    low = float((salary.get("min") or {}).get("amount") or 0) or None
    high = float((salary.get("max") or {}).get("amount") or 0) or None
    currency = (salary.get("min") or salary.get("max") or {}).get("currency") or "BRL"
    if max(low or 0, high or 0) < 100:
        return ""  # "R$ 0,01": a placeholder for "a combinar"
    return from_range(low, high, currency, "mo")


def _city(city: str, state: str = "") -> str:
    city = city.strip()
    state = state.strip() or city_state(city)
    return f"{city}, {state}, Brazil" if state else f"{city}, Brazil"


def _cities(names: list[str]) -> str:
    parts = [_city(n) for n in names[:6]]
    return " / ".join(parts) + (f" / +{len(names) - 6} cities, Brazil" if len(names) > 6 else "")


def _models(models: list[str]) -> str:
    named = [WORK_MODELS[m] for m in models if m in WORK_MODELS]
    return f" ({' / '.join(named)})" if named else ""


def to_opportunity(item: dict[str, Any], detail: dict[str, Any] | None) -> Opportunity:
    """One program or job from the list, with what its own page adds (when we read it)."""
    detail = detail or {}
    program = item.get("type") == "PROGRAM"
    title = " ".join(str(detail.get("title") or item.get("name") or "").split())
    if program:
        places = [str(p) for p in detail.get("locations") or [] if p] or [str(item.get("mainLocation") or "")]
        location = _cities([p for p in places if p]) if any(places) else "Brazil"
        models = list(detail.get("workModels") or item.get("workModels") or [])
        posted, closes = detail.get("applicationStartDate"), detail.get("applicationEndDate")
    else:
        places = detail.get("locations") or []
        location = " / ".join(_city(str(p.get("city") or ""), str(p.get("state") or "")) for p in places if p.get("city"))
        if not location:
            main = str(item.get("mainLocation") or "")  # "Rio de Janeiro - RJ"
            city, _, state = main.rpartition(" - ") if " - " in main else (main, "", "")
            location = _city(city, state) if city and "localidades" not in city.lower() else "Brazil"
        models = [detail["workModel"]] if detail.get("workModel") else list(item.get("workModels") or [])
        posted, closes = detail.get("openingDate"), detail.get("closingDate")
    forecast = item.get("graduationForecast") or detail.get("graduationForecast") or {}
    when = f"Formatura entre {forecast.get('start')} e {forecast.get('end')}. " if forecast.get("start") else ""
    text = html_to_text(str(detail.get("description") or item.get("shortDescription") or ""))
    return Opportunity(
        title=title,
        org=str((item.get("company") or {}).get("name") or "?").strip(),
        source=NAME,
        url=str(item.get("shareUrl") or f"{SITE}/{'programas' if program else 'vagas'}/{item.get('slug') or item['id']}"),
        location=location + _models(models),
        remote=models == ["REMOTE"],
        posted_date=iso_date(posted),
        deadline=iso_date(closes) or NO_DEADLINE,
        pay=_pay(item.get("salary") or detail.get("salaryRange") or detail.get("salary")),
        description=when + text,
        # An estágio-only platform: unclear titles ("Ipiranga Talent 2.0", "Banco de Talentos") are estágios too.
        hints=["student"] if program or student_level(title) == "yes" else ["unsure-student"],
    )


def parse(payload: dict[str, Any], details: dict[str, dict[str, Any]]) -> tuple[list[Opportunity], int]:
    """(programs or jobs on this page, total pages). `details` maps slug or id -> its own page."""
    response = (payload or {}).get("response") or {}
    if not isinstance(response.get("data"), list):
        raise ValueError("unexpected answer from Academia do Universitário (no data list)")
    items = [to_opportunity(item, details.get(_key(item))) for item in response["data"]]
    return items, int((response.get("meta") or {}).get("totalPages") or 1)


def _key(item: dict[str, Any]) -> str:
    return str(item.get("slug") if item.get("type") == "PROGRAM" and item.get("slug") else item.get("id"))


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    read = 0
    for kind in ("programs", "jobs"):
        for page in range(1, MAX_PAGES + 1):
            result.checked += 1
            try:
                payload = get_json(LIST_URL.format(kind=kind, page=page), headers={"Accept": "application/json"})
                listed = (payload.get("response") or {}).get("data") or []
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{kind} page {page}: {error}")
                break
            details: dict[str, dict[str, Any]] = {}
            for item in listed:
                if read >= MAX_DETAILS:
                    break
                read += 1
                result.checked += 1
                try:
                    details[_key(item)] = (get_json(DETAIL_URL.format(kind=kind, key=_key(item)),
                                                    headers={"Accept": "application/json"}).get("response") or {})
                except Exception as error:  # noqa: BLE001
                    result.errors.append(f"{kind} {_key(item)}: {error}")
            try:
                items, pages = parse(payload, details)
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{kind} page {page}: {error}")
                break
            result.items.extend(items)
            if page >= pages:
                break
    return result
