"""Quickin: a Brazilian job-board system used by ~600 employers and recruitment
agencies (boards look like https://jobs.quickin.io/levelcinco/jobs). Most are
small: a law firm with one "Estagiário de Direito", an estágio agency in Porto
Alegre with twenty.

Each board is built from public requests (no login; neither jobs.quickin.io nor
api.quickin.io has a robots.txt):

  GET https://api.quickin.io/public/accounts/{slug}
      -> the company: its id and name
  GET https://api.quickin.io/public/{account id}/jobs?sort=-created_at&limit=30&page=N
      -> open jobs, 30 per page: title, description, requirements, city/region,
         workplace type, contract ("Estágio", "CLT"), pay and creation date

We keep jobs with an estágio / trainee contract or title, leaving out jovem
aprendiz roles and estágios for high-school or technical students. The boards are
in config/companies.yaml, section `quickin` ({slug, name}); the list there came
from a scan of Quickin's sitemap (jobs.quickin.io/sitemap.xml) for boards with
student roles.
"""

from __future__ import annotations

import re
from typing import Any

from ..http import get_json
from ..labels import student_level
from ..models import Opportunity
from ..pay import from_range
from ..textutil import html_to_text, iso_date
from . import SourceResult
from .brtext import SCHOOL_TITLE, br_place, title_pt

NAME = "quickin"
ACCOUNT_URL = "https://api.quickin.io/public/accounts/{slug}"
JOBS_URL = "https://api.quickin.io/public/{id}/jobs?sort=-created_at&limit=30&page={page}"
JOB_URL = "https://jobs.quickin.io/{slug}/jobs/{id}"
MAX_PAGES = 10
STUDENT_CONTRACT = re.compile(r"est[áa]gi|trainee", re.I)
APPRENTICE = re.compile(r"aprendiz", re.I)
WORK_MODELS = {"on-site": "on-site", "hybrid": "hybrid", "remote": "remote"}
PERIODS = {"month": "mo", "hour": "hr", "year": "yr", "week": "wk"}


def _pay(job: dict[str, Any]) -> str:
    try:
        amount = float(job.get("remuneration") or 0)
    except (TypeError, ValueError):
        return ""
    if amount < 100 and PERIODS.get(str(job.get("remuneration_period"))) != "hr":
        return ""
    return from_range(amount, amount, "BRL", PERIODS.get(str(job.get("remuneration_period") or "month"), "mo"))


def _location(job: dict[str, Any]) -> str:
    country = str(job.get("country") or "BR").upper()
    city, region = str(job.get("city") or "").strip(), str(job.get("region") or "").strip()
    if country not in ("BR", "BRA", "BRASIL", "BRAZIL"):
        return ", ".join(p for p in (title_pt(city), region, country) if p) or country
    return br_place(city, region)


def to_opportunity(job: dict[str, Any], board: dict[str, Any]) -> Opportunity | None:
    title = " ".join(str(job.get("title") or "").split())
    contract = str((job.get("contract_id") or {}).get("name") or "")
    if APPRENTICE.search(f"{title} {contract}") or SCHOOL_TITLE.search(title):
        return None
    level = student_level(title)
    if STUDENT_CONTRACT.search(contract) or level == "yes":
        hint = "student"
    elif level == "unsure" or re.search(r"\btrainee\b", title, re.I):
        hint = "unsure-student"
    else:
        return None
    model = WORK_MODELS.get(str(job.get("workplace_type") or "").lower(), "")
    text = "\n".join(html_to_text(str(job.get(k) or "")) for k in ("description", "requirements", "benefits") if job.get(k))
    pay = _pay(job)
    return Opportunity(
        title=title_pt(title),
        org=str(board.get("name") or board["slug"]),
        source=NAME,
        url=str(job.get("career_url") or JOB_URL.format(slug=board["slug"], id=job.get("_id"))),
        location=_location(job) + (f" ({model})" if model else ""),
        remote=model == "remote",
        posted_date=iso_date(job.get("created_at")),
        pay=pay,
        pay_from="field" if pay else "",
        description=text,
        hints=[hint],
    )


def parse(payload: dict[str, Any], board: dict[str, Any]) -> list[Opportunity]:
    """Student roles on one page of a board's jobs."""
    if not isinstance((payload or {}).get("docs"), list):
        raise ValueError("unexpected answer from Quickin (no docs list)")
    return [opp for job in payload["docs"] if job.get("publicate", "published") == "published"
            and (opp := to_opportunity(job, board))]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    headers = {"Accept": "application/json"}
    for board in config.get("companies", {}).get("quickin") or []:
        result.checked += 1
        try:
            account_id = board.get("id") or get_json(ACCOUNT_URL.format(slug=board["slug"]), headers=headers)["_id"]
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"{board.get('name')}: {error}")
            continue
        for page in range(1, MAX_PAGES + 1):
            result.checked += 1
            try:
                payload = get_json(JOBS_URL.format(id=account_id, page=page), headers=headers)
                result.items.extend(parse(payload, board))
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{board.get('name')}: page {page}: {error}")
                break
            if page >= int(payload.get("pages") or 1):
                break
    return result
