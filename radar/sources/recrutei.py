"""Recrutei: a Brazilian job-board system used by hundreds of small and
mid-size employers and recruitment agencies (Alpha Estágio, Meso, BM Vagas,
FUNCEF, Grupo Rotele, Lello...). Its public board "Recrutei Empregos" lists the
open estágios of every company on the platform, about 140 on any day:

  GET https://empregos.recrutei.com.br/vagas-de-estagio?page=N
      -> 12 cards per page: title, company, "City, UF", contract and work-model
         badges, pay ("R$ 1.000,00 p/ Mês", "De R$ 1.100,00 até R$ 1.300,00"),
         "Publicada há 2 dias". robots.txt allows these pages (it disallows
         /api/ and keyword searches there, which we don't use).
  GET https://api.recrutei.com.br/api/v1/vacancies/public/{id}
      -> the vacancy as the company's own board (jobs.recrutei.com.br) shows it:
         description, publication date, closing date (expired_at), regime,
         remote flag. api.recrutei.com.br's robots.txt allows everything.

We keep the cards with an estágio contract or a clear estágio / trainee title,
and leave out jovem aprendiz roles and roles outside Brazil.
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from typing import Any

from ..http import get_json, get_text
from ..labels import student_level
from ..models import NO_DEADLINE, Opportunity
from ..pay import from_range, parse_number
from ..textutil import html_to_text, iso_date
from . import SourceResult
from .brtext import SCHOOL_TITLE, br_place

NAME = "recrutei"
LIST_URL = "https://empregos.recrutei.com.br/vagas-de-estagio?page={page}"
DETAIL_URL = "https://api.recrutei.com.br/api/v1/vacancies/public/{id}"
ARTICLE = re.compile(r'<article class="d2-card d2-jobrow">(.*?)</article>', re.S)
APPRENTICE = re.compile(r"aprendiz|jovem auxiliar", re.I)
SCHOOL = SCHOOL_TITLE
MAX_PAGES = 30
MAX_DETAILS = 200
UNITS = {"hora": 1 / 24, "horas": 1 / 24, "dia": 1, "dias": 1, "semana": 7, "semanas": 7, "mês": 30, "mes": 30,
         "meses": 30, "ano": 365, "anos": 365}


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


def _field(pattern: str, fragment: str) -> str:
    match = re.search(pattern, fragment, re.S)
    return _text(match[1]) if match else ""


def _ago(text: str, today: date) -> str:
    """ "Publicada há 2 semanas" -> the date two weeks before today."""
    match = re.search(r"h[áa]\s+(\d+|um|uma)\s+(\w+)", text, re.I)
    if not match:
        return ""
    count = 1 if match[1].lower() in ("um", "uma") else int(match[1])
    days = UNITS.get(match[2].lower())
    return (today - timedelta(days=int(count * days))).isoformat() if days else ""


def _pay(text: str) -> str:
    """ "R$ 1.000,00 p/ Mês" / "De R$ 1.100,00 até R$ 1.300,00" -> a pay label; "A combinar" -> ""."""
    amounts = [parse_number(a) for a in re.findall(r"R\$\s*([\d.,]+)", text)]
    amounts = [a for a in amounts if a and a >= 100]
    if not amounts:
        return ""
    period = "hr" if re.search(r"hora", text, re.I) else "mo"
    return from_range(min(amounts), max(amounts), "BRL", period)


def parse_list(page: str, today: date) -> list[dict[str, Any]]:
    """The student cards on one list page."""
    articles = ARTICLE.findall(page or "")
    if not articles and "d2-jobrow" not in (page or "") and "vagas-de-estagio" not in (page or ""):
        raise ValueError("unexpected page from Recrutei (no job cards)")
    rows = []
    for card in articles:
        link = re.search(r'class="d2-jobrow__title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', card, re.S)
        if not link:
            continue
        title = _text(link[2])
        badges = [_text(b) for b in re.findall(r'd2-badge--default">(.*?)</span>', card, re.S)]
        is_estagio = any(re.search(r"est[áa]gio", b, re.I) for b in badges)
        if APPRENTICE.search(title) or SCHOOL.search(title) or not (is_estagio or student_level(title) == "yes" or re.search(r"\btrainee\b", title, re.I)):
            continue
        company, _, place = _field(r'd2-jobrow__meta">(.*?)</p>', card).partition(" · ")
        if place and not re.search(r",\s*[A-Z]{2}$", place) and "brasil" not in place.lower():
            continue  # "CDE, ALTO PARANA, Paraguai"
        url = html.unescape(link[1]).split("?")[0]
        rows.append({
            "id": (re.search(r"/(\d+)-", url) or [None, ""])[1],
            "url": url,
            "title": title,
            "company": company.strip(),
            "place": place.strip(),
            "badges": badges,
            "estagio": is_estagio,
            "pay": _field(r'd2-jobrow__salary[^"]*">(.*?)</span>', card),
            "posted": _ago(_field(r'd2-jobrow__time">(.*?)</span>', card), today),
        })
    return rows


def has_next(page: str, number: int) -> bool:
    return f"vagas-de-estagio?page={number + 1}\"" in (page or "")


def _location(place: str) -> str:
    city, _, uf = place.rpartition(",")
    return br_place(city.strip(), uf.strip()) if city else br_place(place)


def to_opportunity(row: dict[str, Any], detail: dict[str, Any] | None) -> Opportunity | None:
    detail = detail or {}
    if detail.get("expired") is True:
        return None
    title = " ".join(str(detail.get("title") or row["title"]).split())
    regime = str((detail.get("regime") or {}).get("description") or "")
    estagio = row["estagio"] or bool(re.search(r"est[áa]gio", regime, re.I))
    badges = " ".join(row["badges"]).lower()
    remote = bool(detail.get("remote")) or (badges.endswith("remoto") and "presencial" not in badges)
    model = "remote" if remote else "hybrid" if "presencial ou remoto" in badges else "on-site" if "presencial" in badges else ""
    if detail.get("city"):
        location = br_place(str(detail["city"]), str(detail.get("state") or ""))
    else:
        location = _location(row["place"]) if row["place"] else "Brazil"
    pay = _pay(row["pay"])
    if not pay and detail.get("show_remuneration") and (detail.get("remuneration") or detail.get("remuneration_from")):
        low = detail.get("remuneration_from") or detail.get("remuneration")
        high = detail.get("remuneration_to") or low
        pay = from_range(float(low), float(high), "BRL", "hr" if "hora" in str(detail.get("remuneration_type") or "").lower() else "mo")
    published = str(detail.get("published_at") or "")
    posted = f"{published[6:10]}-{published[3:5]}-{published[0:2]}" if re.match(r"\d{2}/\d{2}/\d{4}", published) else row["posted"]
    text = html_to_text(str(detail.get("description") or ""))
    if detail.get("workload"):
        text += f"\nCarga horária: {detail['workload']} horas semanais."
    return Opportunity(
        title=title,
        org=str(((detail.get("company") or {}).get("name")) or row["company"] or "?").strip(),
        source=NAME,
        url=row["url"],
        location=location + (f" ({model})" if model else ""),
        remote=model == "remote",
        posted_date=posted,
        deadline=iso_date(detail.get("expired_at")) or NO_DEADLINE,
        pay=pay,
        pay_from="field" if pay else "",
        description=text,
        hints=["student"] if estagio or student_level(title) == "yes" else ["unsure-student"],
    )


def parse(page: str, details: dict[str, dict[str, Any]], today: date) -> list[Opportunity]:
    """Student roles on one list page; `details` maps vacancy id -> its public JSON."""
    return [opp for row in parse_list(page, today) if (opp := to_opportunity(row, details.get(row["id"])))]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    today = date.today()
    read = 0
    for number in range(1, MAX_PAGES + 1):
        result.checked += 1
        try:
            page = get_text(LIST_URL.format(page=number))
            rows = parse_list(page, today)
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"page {number}: {error}")
            break
        details: dict[str, dict[str, Any]] = {}
        for row in rows:
            if read >= MAX_DETAILS or not row["id"]:
                continue
            read += 1
            result.checked += 1
            try:
                details[row["id"]] = get_json(DETAIL_URL.format(id=row["id"]), headers={"Accept": "application/json"})
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"vacancy {row['id']}: {error}")
        result.items.extend(opp for row in rows if (opp := to_opportunity(row, details.get(row["id"]))))
        if not has_next(page, number):
            break
    return result
