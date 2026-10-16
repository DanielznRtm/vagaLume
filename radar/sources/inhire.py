"""InHire: the job-board system of KPMG, Deloitte, Peers, Sympla, Riachuelo and
other Brazilian employers (boards look like https://kpmg.inhire.app/vagas).

The board page is built in the browser from two public requests, no login.
The company is chosen with the X-Tenant header:

  GET https://api.inhire.app/job-posts/public/pages/lean        (X-Tenant: kpmg)
      -> every open role on every career page of the company: title, job id,
         link and career page ("starters-advisory-estagio", "inicio-de-carreira")
  GET https://api.inhire.app/job-posts/public/pages/{jobId}     (X-Tenant: kpmg)
      -> one role: location ("São Paulo, SP, BR"), work model, contract type
         (["Estágio"], ["CLT"]), publication date and description

The list has no contract type, so we open only the roles whose title or
career page looks like a student one (a few dozen per company) and keep those
with an estágio / trainee title or contract. Jovem aprendiz roles are left out,
as in the Gupy source. InHire never shows the bolsa publicly. The boards are in
config/companies.yaml, section `inhire`.
"""

from __future__ import annotations

import re
from typing import Any

from ..http import get_json
from ..labels import student_level
from ..models import Opportunity
from ..textutil import html_to_text, iso_date
from . import SourceResult

NAME = "inhire"
LIST_URL = "https://api.inhire.app/job-posts/public/pages/lean"
JOB_URL = "https://api.inhire.app/job-posts/public/pages/{id}"
MAX_DETAILS = 80  # job pages read per company per run
# Career pages for students and recent graduates ("starters-advisory-estagio", "inicio-de-carreira").
STUDENT_PAGE = re.compile(r"estagi|trainee|inicio-de-carreira|novos-talentos|summer|universit", re.I)
STUDENT_CONTRACT = re.compile(r"est[áa]gi|trainee", re.I)
APPRENTICE = re.compile(r"aprendiz", re.I)
WORK_MODELS = {"on-site": "on-site", "hybrid": "hybrid", "remote": "remote"}


def candidates(lean: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The roles in the list worth opening: student-looking title or career page, no jovem aprendiz."""
    if not isinstance(lean, list):
        raise ValueError("unexpected answer from InHire (no job list)")
    keep = []
    for job in lean:
        title = str(job.get("displayName") or "")
        page = job.get("careerPage") or {}
        page_text = f"{page.get('careerPage') or ''} {page.get('name') or ''}"
        if APPRENTICE.search(title):
            continue
        if student_level(title) != "no" or STUDENT_PAGE.search(page_text):
            keep.append(job)
    return keep


def _location(place: str) -> str:
    """ "São Paulo, SP, BR" -> "São Paulo, SP, Brazil"; a bare "BR" -> "Brazil"."""
    parts = [p.strip() for p in place.split(",") if p.strip()]
    if parts and parts[-1].upper() in ("BR", "BRA", "BRASIL", "BRAZIL"):
        parts[-1] = "Brazil"
    return ", ".join(parts) or "Brazil"


def job_url(job: dict[str, Any], board: dict[str, Any]) -> str:
    """The board's own address (the list's "link" points to the older *.inhire.com.br domain).
    https://kpmg.inhire.app/vagas/{id}, or /{career page}/vagas/{id} for the other career pages."""
    page = str((job.get("careerPage") or {}).get("careerPage") or "default")
    prefix = "" if page == "default" else f"/{page}"
    return f"https://{board['tenant']}.inhire.app{prefix}/vagas/{job['jobId']}"


def to_opportunity(job: dict[str, Any], detail: dict[str, Any] | None, board: dict[str, Any]) -> Opportunity | None:
    """One role from the list plus (when we could read it) its own page."""
    detail = detail or {}
    title = re.sub(r"\s+", " ", str(detail.get("displayName") or job.get("displayName") or "")).strip()
    contracts = " ".join(str(c) for c in detail.get("contractType") or [])
    page = job.get("careerPage") or {}
    on_student_page = bool(STUDENT_PAGE.search(f"{page.get('careerPage') or ''} {page.get('name') or ''}"))
    level = student_level(title)
    if APPRENTICE.search(title):
        return None
    only_student_contract = bool(contracts) and all(STUDENT_CONTRACT.search(str(c)) for c in detail.get("contractType") or [])
    if level == "yes" or only_student_contract:
        hint = "student"
    elif level == "unsure" or on_student_page or STUDENT_CONTRACT.search(contracts):
        hint = "unsure-student"
    else:
        return None
    model = WORK_MODELS.get(str(detail.get("workplaceType") or "").lower(), "")
    location = _location(str(detail.get("location") or "BR"))
    return Opportunity(
        title=title,
        org=str(board.get("name") or board["tenant"]),
        source=NAME,
        url=job_url(job, board),
        location=location + (f" ({model})" if model else ""),
        remote=model == "remote",
        posted_date=iso_date(detail.get("lastPublishedAt") or detail.get("publishedAt") or detail.get("createdAt")),
        description=html_to_text(str(detail.get("description") or "")),
        hints=[hint],
    )


def parse(lean: list[dict[str, Any]], details: dict[str, dict[str, Any]], board: dict[str, Any]) -> list[Opportunity]:
    """Student roles of one company, from its job list and the job pages we read (by job id)."""
    return [opp for job in candidates(lean) if (opp := to_opportunity(job, details.get(str(job.get("jobId"))), board))]


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for board in config.get("companies", {}).get("inhire") or []:
        headers = {"Accept": "application/json", "X-Tenant": board["tenant"]}
        result.checked += 1
        try:
            lean = get_json(LIST_URL, headers=headers)
            wanted = candidates(lean)
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"{board.get('name')}: {error}")
            continue
        details: dict[str, dict[str, Any]] = {}
        for job in wanted[:MAX_DETAILS]:
            result.checked += 1
            try:
                details[str(job["jobId"])] = get_json(JOB_URL.format(id=job["jobId"]), headers=headers)
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{board.get('name')}: job {job.get('jobId')}: {error}")
        result.items.extend(parse(lean, details, board))
    return result
