"""Remote job boards with public APIs or feeds: internships you can do from Brazil.

Each board has a public JSON API (or RSS feed) and its own terms, checked on 2026-10-21:

  himalayas  GET https://himalayas.app/jobs/api/search?employment_type=Intern&country=BR&page=N
             Free, no key. Terms: the Apply link must be the job's `applicationLink`, unchanged,
             with a visible link to Himalayas; don't pass the jobs on to other job boards, Google
             Jobs or LinkedIn (no JobPosting markup); drop jobs once they expire (a role missing from
             the board is closed the next day). Up to 5 pages.
             `country=BR` returns jobs open to Brazil, worldwide jobs included.
  remotive   GET https://remotive.com/api/remote-jobs
             Terms: link back to the job's Remotive URL and name Remotive as the source; at most
             4 calls a day. One call. (Its robots.txt has "Disallow: /api/" for crawlers, but the
             API is documented for developers.) The public feed has only ~10 jobs now.
  jobicy     GET https://jobicy.com/api/jobs?count=200&geo=latam  (and geo=brazil, tag=internship)
             No key. Terms: credit Jobicy, keep the Jobicy job URL. Jobs from the last 7 days.
  remoteok   GET https://remoteok.com/api
             Terms: link back to the job's Remote OK URL (a followed link) and name Remote OK as
             the source; don't use its logo. One call (robots.txt: crawl-delay 1).
  workingnomads  GET https://www.workingnomads.com/api/exposed_jobs/
             Public, robots.txt allows everything. One call.
  weworkremotely GET https://weworkremotely.com/remote-jobs.rss
             Public RSS, robots.txt allows it. The terms page is behind Cloudflare (403), so it is
             not in DEFAULT_BOARDS; add it to the config to read it.
  arbeitnow  GET https://www.arbeitnow.com/api/job-board-api?page=N
             Free ("please link back"). Its remote student roles are German Werkstudent jobs for
             students living in Germany, so it is not in DEFAULT_BOARDS either.

Not used: Remotar (remotar.com.br). Its terms of use ban copying by "Robot/Crawler", and most of
its estágios come from Gupy, which radar/sources/gupy.py already reads.

Only student roles are kept (student_level "yes", or "unsure" when the board itself says it's
an internship). Each role must be open to people in Brazil: worldwide, Latin America, the
Americas, or a list of countries with Brazil in it. The board's own restriction goes in `location`
("Worldwide (remote)", "Brazil (remote)", "LATAM (remote)"), and remote=True.
`source` is the board's name, so the site shows where each role came from (the boards' terms
ask for that).

Which boards to read: config/search.yaml, section `remote_boards` (a list of board names, or
of {name: ...}). With no section, DEFAULT_BOARDS are read.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from ..http import get_json, get_text
from ..labels import student_level
from ..models import Opportunity
from ..pay import from_range
from ..textutil import html_to_text, iso_date
from . import SourceResult
from .gupy import company_name

NAME = "remote_boards"
DEFAULT_BOARDS = ["himalayas", "remotive", "jobicy", "remoteok", "workingnomads"]
HEADERS = {"Accept": "application/json"}

HIMALAYAS_URL = "https://himalayas.app/jobs/api/search?employment_type=Intern&country=BR&page={page}"
HIMALAYAS_PAGES = 5
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
JOBICY_URLS = [
    "https://jobicy.com/api/jobs?count=200&geo=latam",
    "https://jobicy.com/api/jobs?count=200&geo=brazil",
    "https://jobicy.com/api/jobs?count=200&tag=internship",
]
REMOTEOK_URL = "https://remoteok.com/api"
WORKINGNOMADS_URL = "https://www.workingnomads.com/api/exposed_jobs/"
WWR_URL = "https://weworkremotely.com/remote-jobs.rss"
ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api?page={page}"
ARBEITNOW_PAGES = 3

# Board words that say "this is an internship" (a title that is only "unsure" then still counts).
_INTERN_TYPE = re.compile(r"intern|werkstudent|working student|praktik|student", re.I)
_WORLDWIDE = re.compile(r"\b(?:worldwide|anywhere|global(?:ly)?|world|international|no restrictions?)\b", re.I)
_BRAZIL = re.compile(r"\bbra[sz]il\b|\bBR\b|\bBRA\b", re.I)
_LATAM = re.compile(r"\blatam\b|latin america|south america|\bamericas\b|am[ée]rica latina|\bsouth & central america\b", re.I)
# UTC offsets used in Brazil (Fernando de Noronha -2, Brasília -3, Manaus -4, Acre -5).
_BRAZIL_OFFSETS = {-2, -3, -4, -5}


def open_to_brazil(restriction: str) -> str:
    """The board's location restriction, if someone in Brazil can apply; else "".

    "" or "Worldwide" -> "Worldwide"; "Brazil" / "USA, Brazil" -> as written; "LATAM", "Americas"
    -> as written; "USA Only", "Europe", "Mexico" -> "".
    """
    text = " ".join(restriction.split()).strip(" ,;")
    if not text or _WORLDWIDE.search(text):
        return text if text and len(text) < 60 else "Worldwide"
    if _BRAZIL.search(text) or _LATAM.search(text):
        return text if len(text) <= 80 else text[:77].rsplit(",", 1)[0] + ", ..."
    return ""


def _student(title: str, board_says_intern: bool) -> list[str] | None:
    """Hints for a kept role, or None to drop it."""
    level = student_level(title)
    if level == "yes":
        return ["student"]
    if level == "unsure" and board_says_intern:
        return ["unsure-student"]
    return None


def _role(board: str, title: str, org: str, url: str, where: str, posted: str = "", pay: str = "",
          description: str = "", hints: list[str] | None = None, deadline: str = "") -> Opportunity:
    opp = Opportunity(
        title=title,
        org=company_name(org, "") if org.startswith("#") else (org or "?"),  # "#VEMPRAIT4US", a Gupy page's name
        source=board,
        url=url,
        location=f"{where} (remote)",
        remote=True,
        posted_date=posted,
        pay=pay,
        pay_from="field" if pay else "",
        description=description,
        hints=list(hints or []),
    )
    if deadline:
        opp.deadline = deadline
    return opp


def _list_field(value: Any) -> list[Any]:
    """Himalayas sends arrays; older answers sent them as strings like "['Brazil']"."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        return [p.strip(" '\"") for p in value.strip("[]").split(",") if p.strip(" '\"")]
    return []


# --- Himalayas ---------------------------------------------------------------
_PERIODS = {"hourly": "hr", "weekly": "wk", "fortnightly": "", "monthly": "mo", "annual": "yr"}


def parse_himalayas(payload: dict[str, Any]) -> list[Opportunity]:
    if not isinstance((payload or {}).get("jobs"), list):
        raise ValueError("unexpected answer from Himalayas (no jobs list)")
    items: list[Opportunity] = []
    for job in payload["jobs"]:
        title = str(job.get("title") or "").strip()
        hints = _student(title, _INTERN_TYPE.search(str(job.get("employmentType") or "")) is not None)
        if hints is None or {"Director", "Executive"} & set(map(str, _list_field(job.get("seniority")))):
            continue  # "Co-Founder / CMO" filed as "Intern"
        countries = [str(c) for c in _list_field(job.get("locationRestrictions"))]
        where = open_to_brazil(", ".join(countries))
        offsets = {float(o) for o in _list_field(job.get("timezoneRestrictions")) if re.fullmatch(r"-?\d+(?:\.\d+)?", str(o))}
        if not where or (offsets and not offsets & _BRAZIL_OFFSETS):
            continue
        low, high = (float(job.get(k) or 0) or None for k in ("minSalary", "maxSalary"))
        period = _PERIODS.get(str(job.get("salaryPeriod") or "annual"), "")
        pay = from_range(low, high, str(job.get("currency") or "USD"), period) if (low or high) and period else ""
        items.append(_role(
            "himalayas", title, str(job.get("companyName") or ""),
            str(job.get("applicationLink") or job.get("guid") or ""), where,
            posted=iso_date(job.get("pubDate") and int(job["pubDate"])), pay=pay,
            description=html_to_text(str(job.get("description") or job.get("excerpt") or "")), hints=hints,
        ))  # expiryDate is always pubDate + 60 days, the board's listing time, not an application deadline
    return items


# --- Remotive ----------------------------------------------------------------
def parse_remotive(payload: dict[str, Any]) -> list[Opportunity]:
    if not isinstance((payload or {}).get("jobs"), list):
        raise ValueError("unexpected answer from Remotive (no jobs list)")
    items: list[Opportunity] = []
    for job in payload["jobs"]:
        title = str(job.get("title") or "").strip()
        hints = _student(title, str(job.get("job_type") or "") == "internship")
        where = open_to_brazil(str(job.get("candidate_required_location") or ""))
        if hints is None or not where:
            continue
        items.append(_role(
            "remotive", title, str(job.get("company_name") or ""), str(job.get("url") or ""), where,
            posted=iso_date(job.get("publication_date")),
            description=html_to_text(str(job.get("description") or "")), hints=hints,
        ))
    return items


# --- Jobicy ------------------------------------------------------------------
def parse_jobicy(payload: dict[str, Any]) -> list[Opportunity]:
    if not isinstance((payload or {}).get("jobs"), list):
        raise ValueError("unexpected answer from Jobicy (no jobs list)")
    items: list[Opportunity] = []
    for job in payload["jobs"]:
        title = str(job.get("jobTitle") or "").strip()
        types = " ".join(map(str, _list_field(job.get("jobType")) or [job.get("jobType") or ""]))
        hints = _student(title, _INTERN_TYPE.search(types) is not None)
        where = open_to_brazil(str(job.get("jobGeo") or ""))
        if hints is None or not where:
            continue
        low, high = job.get("salaryMin"), job.get("salaryMax")
        period = {"hourly": "hr", "weekly": "wk", "monthly": "mo", "yearly": "yr"}.get(str(job.get("salaryPeriod") or "yearly"), "")
        pay = from_range(float(low or 0) or None, float(high or 0) or None, str(job.get("salaryCurrency") or "USD"), period) if (low or high) and period else ""
        items.append(_role(
            "jobicy", title, str(job.get("companyName") or ""), str(job.get("url") or ""), where,
            posted=iso_date(job.get("pubDate")), pay=pay,
            description=html_to_text(str(job.get("jobDescription") or job.get("jobExcerpt") or "")), hints=hints,
        ))
    return items


# --- Remote OK -----------------------------------------------------------------
def parse_remoteok(payload: list[dict[str, Any]]) -> list[Opportunity]:
    if not isinstance(payload, list):
        raise ValueError("unexpected answer from Remote OK (not a list)")
    items: list[Opportunity] = []
    for job in payload:
        if not isinstance(job, dict) or "position" not in job:
            continue  # the first element is the legal notice
        title = str(job.get("position") or "").strip()
        tags = " ".join(map(str, job.get("tags") or []))
        hints = _student(title, _INTERN_TYPE.search(tags) is not None)
        where = open_to_brazil(str(job.get("location") or ""))
        if hints is None or not where:
            continue
        low, high = float(job.get("salary_min") or 0) or None, float(job.get("salary_max") or 0) or None
        items.append(_role(
            "remoteok", title, str(job.get("company") or ""), str(job.get("url") or ""), where,
            posted=iso_date(job.get("date")), pay=from_range(low, high, "USD", "yr") if (low or high) else "",
            description=html_to_text(str(job.get("description") or "")), hints=hints,
        ))
    return items


# --- Working Nomads ------------------------------------------------------------
def parse_workingnomads(payload: list[dict[str, Any]]) -> list[Opportunity]:
    if not isinstance(payload, list):
        raise ValueError("unexpected answer from Working Nomads (not a list)")
    items: list[Opportunity] = []
    for job in payload:
        title = str(job.get("title") or "").strip()
        hints = _student(title, False)
        where = open_to_brazil(str(job.get("location") or ""))
        if hints is None or not where:
            continue
        items.append(_role(
            "workingnomads", title, str(job.get("company_name") or ""), str(job.get("url") or ""), where,
            posted=iso_date(job.get("pub_date")),
            description=html_to_text(str(job.get("description") or "")), hints=hints,
        ))
    return items


# --- We Work Remotely (RSS) ----------------------------------------------------
def parse_weworkremotely(feed_xml: str) -> list[Opportunity]:
    root = ET.fromstring(feed_xml.encode("utf-8") if isinstance(feed_xml, str) else feed_xml)
    items: list[Opportunity] = []
    for item in root.iter("item"):
        company, _, title = (item.findtext("title") or "").partition(": ")  # "DuckDuckGo: Senior Backend Engineer"
        title = title.strip() or company.strip()
        hints = _student(title, _INTERN_TYPE.search(item.findtext("type") or "") is not None)
        region = (item.findtext("region") or "").replace("Anywhere in the World", "Worldwide")
        where = open_to_brazil(", ".join(p for p in (region, item.findtext("country") or "") if p.strip()))
        if hints is None or not where:
            continue
        try:
            posted = parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            posted = ""
        items.append(_role(
            "weworkremotely", title, company.strip(), (item.findtext("link") or "").strip(), where,
            posted=posted, description=html_to_text(item.findtext("description") or ""), hints=hints,
        ))
    return items


# --- Arbeitnow -------------------------------------------------------------------
def parse_arbeitnow(payload: dict[str, Any]) -> list[Opportunity]:
    """Remote student roles only. Arbeitnow has no location restriction field: its roles are
    for people in Germany ("Berlin", remote=true), so the location says Germany."""
    if not isinstance((payload or {}).get("data"), list):
        raise ValueError("unexpected answer from Arbeitnow (no data list)")
    items: list[Opportunity] = []
    for job in payload["data"]:
        if not job.get("remote"):
            continue
        title = str(job.get("title") or "").strip()
        hints = _student(title, _INTERN_TYPE.search(" ".join(map(str, job.get("job_types") or []))) is not None)
        if hints is None:
            continue
        place = str(job.get("location") or "").strip()
        where = place if re.search(r"germany|deutschland", place, re.I) else f"{place}, Germany" if place else "Germany"
        items.append(_role(
            "arbeitnow", title, str(job.get("company_name") or ""), str(job.get("url") or ""), where,
            posted=iso_date(job.get("created_at")),
            description=html_to_text(str(job.get("description") or "")), hints=hints,
        ))
    return items


# --- Fetching ------------------------------------------------------------------
def _fetch_himalayas(result: SourceResult) -> None:
    for page in range(1, HIMALAYAS_PAGES + 1):
        result.checked += 1
        payload = get_json(HIMALAYAS_URL.format(page=page), headers=HEADERS)
        result.items.extend(parse_himalayas(payload))
        if not payload.get("jobs"):
            break  # the docs: "keep requesting the next page until one returns no jobs"


def _fetch_one(url: str, parser: Callable[[Any], list[Opportunity]], text: bool = False) -> Callable[[SourceResult], None]:
    def run(result: SourceResult) -> None:
        result.checked += 1
        result.items.extend(parser(get_text(url) if text else get_json(url, headers=HEADERS)))
    return run


def _fetch_jobicy(result: SourceResult) -> None:
    for url in JOBICY_URLS:
        result.checked += 1
        result.items.extend(parse_jobicy(get_json(url, headers=HEADERS)))


def _fetch_arbeitnow(result: SourceResult) -> None:
    for page in range(1, ARBEITNOW_PAGES + 1):
        result.checked += 1
        payload = get_json(ARBEITNOW_URL.format(page=page), headers=HEADERS)
        result.items.extend(parse_arbeitnow(payload))
        if not (payload.get("links") or {}).get("next"):
            break


BOARDS: dict[str, Callable[[SourceResult], None]] = {
    "himalayas": _fetch_himalayas,
    "remotive": _fetch_one(REMOTIVE_URL, parse_remotive),
    "jobicy": _fetch_jobicy,
    "remoteok": _fetch_one(REMOTEOK_URL, parse_remoteok),
    "workingnomads": _fetch_one(WORKINGNOMADS_URL, parse_workingnomads),
    "weworkremotely": _fetch_one(WWR_URL, parse_weworkremotely, text=True),
    "arbeitnow": _fetch_arbeitnow,
}


def configured_boards(config: dict[str, Any]) -> list[str]:
    listed = (config.get("search") or {}).get("remote_boards") or (config.get("companies") or {}).get("remote_boards")
    if not listed:
        return list(DEFAULT_BOARDS)
    names = [str(b.get("name") if isinstance(b, dict) else b).strip().lower() for b in listed]
    return list(dict.fromkeys(n for n in names if n))


def fetch(config: dict[str, Any], boards: list[str] | None = None) -> SourceResult:
    """Read the configured boards, or only `boards` (e.g. ["himalayas"] for one SOURCES entry).
    A board named in `boards` but missing from a `remote_boards` config section is skipped, so the
    config section switches boards on and off either way."""
    result = SourceResult()
    seen: set[str] = set()
    wanted = configured_boards(config)
    for board in [b for b in boards if b in wanted] if boards else wanted:
        if board not in BOARDS:
            result.errors.append(f"unknown remote board {board!r}; choose from {', '.join(BOARDS)}")
            continue
        part = SourceResult()
        try:
            BOARDS[board](part)
        except Exception as error:  # noqa: BLE001 - one board must not stop the others
            result.errors.append(f"{board}: {error}")
        result.checked += part.checked
        for opp in part.items:  # Jobicy's three searches overlap; Himalayas pages can shift
            if opp.id not in seen:
                seen.add(opp.id)
                result.items.append(opp)
    return result
