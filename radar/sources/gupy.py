"""Gupy (portal.gupy.io): the main Brazilian job portal for estágio.

The portal's search page calls a JSON route that we call directly:
  https://portal.gupy.io/api/job-search/jobs?type=...&limit=100&offset=N
`type` takes Gupy's job types, comma-separated (repeating `type=` is
ignored). We ask for internships, summer internships (estágio de férias)
and trainee programs, newest first, 100 per page, until a page comes back
short. That is about 2,700 roles in ~27 requests. (Jovem aprendiz, for
14–24-year-olds outside university, is left out; add
"vacancy_type_apprentice" to gupy_types in config/search.yaml to include it.)

Some companies file estágios under other job types: Itaú's "Programa de
Estágio Corporativo" is a talent pool, and hundreds of estágios are typed as
regular ("effective") jobs. So we also search those types for "estágio" and
"estagiário/a" in the title, keeping only titles that are clearly for
students (about 600 more roles).

Note: the response's pagination.total is unreliable for limit > 10, so we
stop on a short page instead of trusting it.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from ..http import get_json
from ..labels import student_level
from ..places import ALSO_ABROAD, city_state
from ..models import NO_DEADLINE, Opportunity
from ..textutil import html_to_text, iso_date
from . import SourceResult

log = logging.getLogger(__name__)

NAME = "gupy"
API_URL = "https://portal.gupy.io/api/job-search/jobs?"
PAGE_SIZE = 100  # the maximum Gupy accepts
MAX_PAGES = 60   # safety stop: 6,000 roles
DEFAULT_TYPES = ["vacancy_type_internship", "vacancy_type_summer", "vacancy_type_trainee"]

# Gupy's own job types. Internship-like ones are clearly for students;
# trainee might be (some are for recent graduates).
STUDENT_TYPES = {"vacancy_type_internship", "vacancy_type_apprentice", "vacancy_type_summer"}
MAYBE_TYPES = {"vacancy_type_trainee", "vacancy_type_talent_pool"}
# Other job types, searched by title only (see the module docstring).
OTHER_TYPES = ["vacancy_type_talent_pool", "vacancy_type_effective", "vacancy_type_temporary"]
TITLE_SEARCHES = ["estágio", "estagiário", "estagiária", "summer", "férias"]  # the search ignores accents; "Summer Job" = estágio de férias


def _location(city: str, state: str) -> str:
    """Gupy has no country field. Brazilian jobs always have a state; a city
    without one is abroad (Gupy also hosts companies in Peru and Chile), unless
    it is a Brazilian city whose state was left out ("Goiânia")."""
    if state:
        return f"{city}, {state}, Brazil" if city else f"{state}, Brazil"
    if not city:
        return "Brazil"
    if city_state(city) and city.lower() not in ALSO_ABROAD:
        return f"{city}, Brazil"
    return city


_TAGLINE = re.compile(r"^fa[çc]a parte d[oa] (?:nosso |nossa )?(?:time|equipe|família)\s*(?:d[oa]s?\s+)?", re.I)
_HASHTAG = re.compile(r"^#(?:quero ?ser|seja|vem ?pra|vem ?para|venha ?ser|bora ?ser|faca ?parte|somos)?", re.I)
# "Programa de Estágio Santa Casa BH", "Vagas Grupo Sabin", "Trabalhe na Mills", "Carreiras Pilar Hospital"...
_PAGE_PREFIX = re.compile(
    r"^(?:programas? de (?:est[áa]gio|entrada|pr[áa]cticas|trainee)(?: e trainee)?|oportunidades de est[áa]gio|est[áa]gios? e (?:jovem )?aprendiz"
    r"|est[áa]gios?|vagas(?: abertas)?|carreiras?|portal de vagas|trabalhe conosco(?: n[ao])?|trabalhe (?:na|no|em)"
    r"|venha (?:ser|trabalhar (?:conosco )?(?:na|no)?|fazer parte d[ao])|p[áa]gina de carreiras?)(?:\s*[•|]\s*|\s+|$)"
    # "... em Marketing do Instituto Infnet", "... em Pesquisa Campinas – CNPEM", "... da PUCPR", "... 2027 - Fast"
    r"(?:em [^–-]+?(?:\s+d[oa]s?|\s*[–-])\s+)?(?:(?:d[aoe]s?|na|no)\s+)?(?:20\d\d\s*[-–]\s*)?", re.I)
# "Votorantim Cimentos - Jovens Talentos", "GrupoVillela | Gestão de Carreiras", "Energisa Estágio", "Anbima 2026"...
_PAGE_SUFFIX = re.compile(
    r"\s*(?:[-|–]\s*(?:vagas\b.*|jovens talentos|gest[ãa]o de carreiras|venha .*|programas? de .*|p[áa]gina de .*|carreiras?|trabalhe .*|talentos)"
    r"|\s+(?:est[áa]gios?|carreiras|vagas|programa de est[áa]gio)|\s+20\d\d)$", re.I)
# A whole sentence instead of a name: "Venha construir o futuro com a gente", "Página de Carreira".
_SENTENCE = re.compile(r"^(?:venha|p[áa]gina de carreira|20\d\d$)|com a gente|conosco|nossos clientes", re.I)
_SUBDOMAIN_WORDS = re.compile(r"^(?:programa(?:s)?(?:de)?(?:estagio|entrada)|estagios?|vagas|carreiras?)-?|-?(?:vagas|carreiras|estagio)$", re.I)


def company_name(name: str, job_url: str) -> str:
    """The company behind a career page's name: "#QueroSerMercantil" -> "Mercantil",
    "Faça parte do time Vieira Rezende Advogados!" -> "Vieira Rezende Advogados",
    "Confidencial" -> "Empresa confidencial"; a bare tagline -> the career page's address."""
    name = name.strip()
    if name.lower() == "confidencial":
        return "Empresa confidencial"
    cleaned = name
    if cleaned.startswith("#"):
        cleaned = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", _HASHTAG.sub("", cleaned)).strip()  # "SejaSBT" -> "SBT"
    cleaned = _TAGLINE.sub("", cleaned).strip(" !.")
    for _ in range(2):  # "Programa de Estágio Anbima 2026"
        cleaned = _PAGE_SUFFIX.sub("", _PAGE_PREFIX.sub("", cleaned)).strip(" !.-|")
    if cleaned and not _SENTENCE.search(cleaned) and cleaned.lower() not in ("time", "nosso time", "equipe"):
        if cleaned.islower():  # "#vempraot" -> "OT", "#queroseraurora" -> "Aurora"
            cleaned = cleaned.upper() if len(cleaned) <= 4 else cleaned.title()
        return cleaned
    subdomain = (re.match(r"https?://([\w-]+)\.gupy\.io", job_url) or [None, ""])[1]
    subdomain = _SUBDOMAIN_WORDS.sub("", subdomain) or subdomain  # "vagas-mrveco" -> "mrveco"
    return subdomain.replace("-", " ").title() if subdomain else name


# A company whose Gupy page was switched off still has jobs in the portal's search, with a broken
# address ("https://terras&15719&inactive.gupy.io/job/..."): the job is closed (issue #24).
INACTIVE_PAGE = re.compile(r"^https?://[^/]*(?:&|\binactive\b)", re.I)


# The portal's search also returns jobs published years ago, nearly all closed (a sample of
# pre-2025 estágios: 12 of 14 closed or gone). Talent pools ("Banco de talentos") stay open for long.
MAX_AGE_DAYS = 365
TALENT_POOL = re.compile(r"banco de (?:talentos|curr[íi]culos)|talent pool", re.I)


def to_opportunity(job: dict[str, Any], today: date | None = None) -> Opportunity | None:
    """One Gupy job -> Opportunity, or None when it isn't a student role at all or is closed."""
    if INACTIVE_PAGE.search(str(job.get("jobUrl") or "")):
        return None
    published = iso_date(job.get("publishedDate"))
    cutoff = ((today or date.today()) - timedelta(days=MAX_AGE_DAYS)).isoformat()
    if published and published < cutoff and job.get("type") != "vacancy_type_talent_pool" \
            and not TALENT_POOL.search(str(job.get("name") or "")):
        return None
    title = str(job.get("name", "")).strip()
    job_type = str(job.get("type", ""))
    level = student_level(title)
    if job_type in STUDENT_TYPES or level == "yes":
        hints = ["student"]
    elif job_type in MAYBE_TYPES or level == "unsure":
        hints = ["unsure-student"]
    else:
        return None  # e.g. "Analista Pleno" that matched a search text only
    city, state = str(job.get("city") or "").strip(), str(job.get("state") or "").strip()
    workplace = str(job.get("workplaceType") or "")
    location = _location(city, state)
    return Opportunity(
        title=title,
        org=company_name(str(job.get("careerPageName") or "?"), str(job.get("jobUrl") or "")),
        source=NAME,
        url=str(job["jobUrl"]),
        location=location + (f" ({workplace})" if workplace else ""),
        remote=workplace == "remote",
        posted_date=iso_date(job.get("publishedDate")),
        deadline=iso_date(job.get("applicationDeadline")) or NO_DEADLINE,
        description=html_to_text(str(job.get("description") or "")),
        hints=hints,
    )


def parse(payload: dict[str, Any], today: date | None = None) -> list[Opportunity]:
    """One page of the JSON API."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("unexpected answer from the Gupy API (no 'data' list)")
    return [opp for job in payload["data"] if (opp := to_opportunity(job, today))]


def _search(result: SourceResult, seen: set[str], params: dict[str, Any], students_only: bool) -> None:
    """Every page of one search, newest first, until a short page."""
    for page in range(MAX_PAGES):
        result.checked += 1
        query = {**params, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
        try:
            payload = get_json(API_URL + urlencode(query), headers={"Accept": "application/json"})
            items = parse(payload)
        except Exception as error:  # noqa: BLE001
            log.warning("Gupy %s page %d failed: %s", params, page, error)
            result.errors.append(f"{params.get('jobName') or 'types'} offset {page * PAGE_SIZE}: {error}")
            return
        for opp in items:
            if students_only and "student" not in opp.hints:
                continue  # a talent pool or regular job without "estágio" in a student sense
            if opp.id not in seen:
                seen.add(opp.id)
                result.items.append(opp)
        if len(payload["data"]) < PAGE_SIZE:
            return  # the last page


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    seen: set[str] = set()
    types = config.get("search", {}).get("gupy_types") or DEFAULT_TYPES
    _search(result, seen, {"type": ",".join(types)}, students_only=False)
    for name in TITLE_SEARCHES:
        _search(result, seen, {"type": ",".join(OTHER_TYPES), "jobName": name}, students_only=True)
    return result
