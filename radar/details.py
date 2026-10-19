"""Read a role's own job page, once, for what the list didn't say.

Many sources only give a title and a place: Workday and SmartRecruiters
search results, Microsoft's search, NVIDIA, IEL, and the GitHub lists (whose
links go to Workday, Greenhouse, Ashby, Lever...). The pay, the skills, the
course a role is for and the study level are in the posting itself. In
October 2026 half the roles on the site had no pay, and almost all of those
came from these sources.

So for these roles we open the job's page through the job board's public
API (or the page itself for IEL), add its text to the description, and let
the keyword rules (radar/labels.py) read it. A role is read once, then again
after REREAD_DAYS; on the days in between, the database keeps what its page
gave (see db.upsert). A per-source budget keeps each daily run short: the
first run reads a few thousand pages, later runs only the new roles.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import requests

from .http import get_json, get_text
from .models import Opportunity
from .pay import from_range
from .readers_more import MORE_READERS
from .sources.ashby import _pay as ashby_pay
from .sources.lever import _description as lever_description, _pay as lever_pay
from .textutil import html_to_text

log = logging.getLogger(__name__)

# Sources whose list gives no description (or no pay) and how many of their pages to read per run.
# About 2,750 pages (~7 minutes) per run: the first runs clear the backlog over 2-3 days, then only new roles.
BUDGET = {"github_lists": 1000, "workday": 700, "smartrecruiters": 300, "iel": 500, "microsoft": 150, "nvidia": 100}
# Sites whose job pages only show the pay in a real browser (radar/browser.py), about 7 s a page:
# read one after the other, a few per run. Meta: "$7,313/month to $12,667/month + benefits".
BROWSER_BUDGET = {"meta": 20}
REREAD_DAYS = 30
# The GitHub lists keep a role for days after the company takes it down: their pages are read again
# every week, so a removed role (the page answers 404) leaves the site soon.
REREAD_DAYS_BY_SOURCE = {"github_lists": 7}
# A role whose page is gone is closed, unless that many pages of one source are "gone" in one run
# (then the site is more likely blocking us than closing them all).
GONE_LIMIT = 0.3
WORKERS = 8


# --- one reader per job board, chosen from the job's address -------------------
def _workday(url: str) -> tuple[str, str]:
    """https://<tenant>.wd<N>.myworkdayjobs.com/[en-US/]<site>/job/... -> its JSON."""
    parsed = urlparse(url)
    tenant = parsed.netloc.split(".")[0]
    parts = [p for p in parsed.path.split("/") if p]
    if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]  # the language
    if len(parts) < 3 or "job" not in parts:
        return "", ""
    site, rest = parts[0], "/".join(parts[1:])
    info = get_json(f"https://{parsed.netloc}/wday/cxs/{tenant}/{site}/{rest}").get("jobPostingInfo") or {}
    return html_to_text(str(info.get("jobDescription") or "")), ""


def _greenhouse(url: str) -> tuple[str, str]:
    """boards.greenhouse.io/<slug>/jobs/<id> (or job-boards..., or ?gh_jid=) -> the job API, with pay ranges."""
    parsed = urlparse(url)
    match = re.search(r"/([\w-]+)/jobs/(\d+)", parsed.path)
    slug, job_id = (match.group(1), match.group(2)) if match else ("", "")
    if not match:
        query = parse_qs(parsed.query)
        job_id = (query.get("gh_jid") or query.get("token") or [""])[0]
        slug = (query.get("for") or [""])[0]
    if not (slug and job_id):
        return "", ""
    job = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}?pay_transparency=true")
    pay = ""
    for band in job.get("pay_input_ranges") or []:
        low, high = band.get("min_cents"), band.get("max_cents")
        if low or high:
            pay = from_range((low or high) / 100, (high or low) / 100, str(band.get("currency_type") or "USD"), "")
            break
    return html_to_text(html_to_text(str(job.get("content") or ""))), pay


def _lever(url: str) -> tuple[str, str]:
    """jobs.lever.co/<slug>/<id> (or jobs.eu.lever.co) -> the postings API."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return "", ""
    host = "api.eu.lever.co" if ".eu." in parsed.netloc else "api.lever.co"
    job = get_json(f"https://{host}/v0/postings/{parts[0]}/{parts[1]}")
    return lever_description(job), lever_pay(job)


class JobGone(Exception):
    """The job board says this job no longer exists."""


_ASHBY_BOARDS: dict[str, dict[str, Any]] = {}


def _ashby(url: str) -> tuple[str, str]:
    """jobs.ashbyhq.com/<org>/<id>: the board API lists every job with its text and pay (read once per board)."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) < 2:
        return "", ""
    org, job_id = parts[0], parts[1]
    if org not in _ASHBY_BOARDS:
        board = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true")
        _ASHBY_BOARDS[org] = {str(job.get("id")): job for job in board.get("jobs") or []}
    job = _ASHBY_BOARDS[org].get(job_id)
    if job is None and _ASHBY_BOARDS[org]:
        raise JobGone(url)  # the board lists its jobs, and this one isn't there any more
    job = job or {}
    return str(job.get("descriptionPlain") or html_to_text(str(job.get("descriptionHtml") or ""))), ashby_pay(job)


def _smartrecruiters(url: str) -> tuple[str, str]:
    """jobs.smartrecruiters.com/<company>/<id>-<slug> -> the postings API."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) < 2:
        return "", ""
    job_id = parts[1].split("-")[0]
    job = get_json(f"https://api.smartrecruiters.com/v1/companies/{parts[0]}/postings/{job_id}")
    sections = (job.get("jobAd") or {}).get("sections") or {}
    text = "\n".join(html_to_text(str((sections.get(k) or {}).get("text") or ""))
                     for k in ("jobDescription", "qualifications", "additionalInformation"))
    return text, ""


def _microsoft(url: str) -> tuple[str, str]:
    """apply.careers.microsoft.com/careers/job/<id> -> Eightfold's position details."""
    job_id = urlparse(url).path.rstrip("/").split("/")[-1]
    data = get_json(f"https://apply.careers.microsoft.com/api/pcsx/position_details?position_id={job_id}&domain=microsoft.com&hl=en",
                    headers={"Accept": "application/json"})
    return html_to_text(str((data.get("data") or data).get("jobDescription") or "")), ""


def _page(url: str) -> tuple[str, str]:
    """The page's visible text (IEL: "Remuneração: R$ 1.200,00" is on the vacancy page)."""
    return html_to_text(get_text(url))[:20000], ""


READERS: list[tuple[re.Pattern[str], Callable[[str], tuple[str, str]]]] = [
    (re.compile(r"\.myworkdayjobs\.com/"), _workday),
    (re.compile(r"greenhouse\.io/|[?&]gh_jid="), _greenhouse),
    (re.compile(r"jobs(?:\.eu)?\.lever\.co/"), _lever),
    (re.compile(r"jobs\.ashbyhq\.com/"), _ashby),
    (re.compile(r"jobs\.smartrecruiters\.com/"), _smartrecruiters),
    (re.compile(r"apply\.careers\.microsoft\.com/careers/job/"), _microsoft),
    (re.compile(r"carreiras\.iel\.org\.br/|talento\.ielpr\.com\.br/|\.iel[a-z]*\.(?:org|com)\.br/"), _page),
    # Oracle HCM, Eightfold, iCIMS, Jibe, SuccessFactors, TikTok, Rippling, Avature... (radar/readers_more.py).
    # Workable is left out: it answered 429 with a day-long block, untested from GitHub's runners.
    *[(pattern, read) for pattern, read in MORE_READERS if read.__name__ != "_workable"],
]


def reader_for(url: str) -> Callable[[str], tuple[str, str]] | None:
    return next((read for pattern, read in READERS if pattern.search(url)), None)


def read(opp: Opportunity) -> bool:
    """Read one role's page into it. True when something was read."""
    reader = reader_for(opp.url)
    if reader is None:
        return False
    text, pay = reader(opp.url)
    if not text and not pay:
        return False
    opp.description = f"{opp.description}\n{text}".strip()
    if pay and not opp.pay:
        opp.pay, opp.pay_from = pay, "field"
    return True


def is_gone(url: str, error: Exception) -> bool:
    """Does this error mean the job was taken down? 404/410 anywhere; Workday answers 403 for a removed job."""
    if isinstance(error, JobGone):
        return True
    code = getattr(getattr(error, "response", None), "status_code", None)
    return isinstance(error, requests.HTTPError) and (code in (404, 410) or (code == 403 and "myworkdayjobs.com" in url))


def enrich(items: list[Opportunity], conn: sqlite3.Connection, today: str) -> dict[str, int]:
    """Read the pages of the roles that need it (new ones first). Returns pages read per source.
    A role whose page is gone is closed (opp.is_open = False, detail_checked = "gone <date>")."""
    checked = {row["id"]: row["detail_checked"] for row in conn.execute("SELECT id, detail_checked FROM opportunities")}

    def reread_before(source: str) -> str:
        return (date.fromisoformat(today) - timedelta(days=REREAD_DAYS_BY_SOURCE.get(source, REREAD_DAYS))).isoformat()

    queue: list[Opportunity] = []
    for source, budget in BUDGET.items():
        before = reread_before(source)
        due = [o for o in items if o.source == source and reader_for(o.url)
               and (not checked.get(o.id) or checked[o.id] < before)]
        due.sort(key=lambda o: o.id in checked)  # roles we have never seen first
        queue += due[:budget]

    def one(opp: Opportunity) -> tuple[Opportunity, str]:
        try:
            return opp, "read" if read(opp) else ""
        except Exception as error:  # noqa: BLE001 - a page that fails is tried again next run
            if is_gone(opp.url, error):
                return opp, "gone"
            log.debug("details %s: %s", opp.url, error)
            return opp, ""

    done: dict[str, int] = {}
    gone: dict[str, list[Opportunity]] = {}
    tried: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for opp, outcome in pool.map(one, queue):
            tried[opp.source] = tried.get(opp.source, 0) + 1
            if outcome == "read":
                opp.detail_checked = today
                done[opp.source] = done.get(opp.source, 0) + 1
            elif outcome == "gone":
                gone.setdefault(opp.source, []).append(opp)
    for source, roles in gone.items():
        if len(roles) > max(20, GONE_LIMIT * tried[source]):
            log.warning("%s: %d of %d job pages answered 'gone'; not closing them (blocked?)", source, len(roles), tried[source])
            continue
        for opp in roles:
            opp.is_open, opp.detail_checked = False, f"gone {today}"
        done[f"{source} closed"] = len(roles)
    for source, budget in BROWSER_BUDGET.items():
        before = reread_before(source)
        due = [o for o in items if o.source == source and (not checked.get(o.id) or checked[o.id] < before)]
        due.sort(key=lambda o: o.id in checked)
        by_url = {o.url: o for o in due[:budget]}
        try:
            from .browser import render_many

            for url, text in render_many(list(by_url)):
                if text:
                    opp = by_url[url]
                    opp.description = f"{opp.description}\n{text[:20000]}".strip()
                    opp.detail_checked = today
                    done[source] = done.get(source, 0) + 1
        except Exception as error:  # noqa: BLE001 - no browser here: the other pages still count
            log.warning("Job pages in the browser (%s) failed: %s", source, error)
    log.info("Job pages read: %s", done or "none")
    return done
