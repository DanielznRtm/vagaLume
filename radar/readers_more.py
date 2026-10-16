"""More job-page readers for radar/details.py: the boards the GitHub lists link to most
after Workday/Greenhouse/Lever/Ashby.

Each reader takes a job's address and returns (plain description text, pay label or "").
The pay label is only filled from a structured pay field (Rippling's pay ranges, JSON-LD
baseSalary, Oracle's "Salary Range" field, Jibe's salary tags); a pay written in the
description is left to the label rules, which run find_pay on the text.

Boards (October 2026, open roles from the GitHub lists):
- Oracle Recruiting Cloud (*.fa.*.oraclecloud.com, ~290): the requisition-details REST route.
- Jibe / Google-hosted career sites (careers.amd.com, careers.garmin.com, jobs.keysight.com,
  careers.jhuapl.edu, careers.rivian.com... links end in "?icims=1", ~200): their /api/jobs search.
- TikTok / ByteDance (lifeattiktok.com, joinbytedance.com, jobs.bytedance.com, ~140): the job
  page is rendered on the server, with the pay sentence in it.
- iCIMS (*.icims.com, ~170): the job page with ?in_iframe=1 (just the posting).
- SAP SuccessFactors career sites (jobs.l3harris.com, careers.qorvo.com... links with
  "?ats=successfactors", ~150): the job page.
- Eightfold (*.eightfold.ai, jobs.infineon.com, ~50): /api/apply/v2/jobs/<id>.
- Rippling (ats.rippling.com), Workable (apply.workable.com), Avature (jobs.ea.com),
  Paylocity, Amazon (amazon.jobs) and Meta (metacareers.com: text only, the pay is drawn
  by the browser).
Tesla (www.tesla.com) answers 403 to plain requests (bot protection), so it has no reader.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .http import get_json, get_text
from .pay import find_pay, from_range
from .textutil import html_to_text

MAX_TEXT = 20000
_PERIODS = {"HOUR": "hr", "HOURLY": "hr", "DAY": "", "WEEK": "wk", "MONTH": "mo", "YEAR": "yr", "ANNUAL": "yr", "SALARY": "yr"}
_PAY_FIELD = re.compile(r"salary|pay\b|pay range|compensation|wage|hourly rate", re.I)
_MONEY = re.compile(r"[$€£]\s?\d|\b(?:USD|CAD|EUR|GBP)\s?\d", re.I)


# --- small helpers -------------------------------------------------------------
def _between(page: str, start: str, ends: tuple[str, ...] = ()) -> str:
    """The text of the page from the first `start` marker up to the first end marker after it."""
    i = page.find(start)
    if i < 0:
        return ""
    stops = []
    for end in ends:
        j = page.find(end, i + len(start))
        if j > 0 and not end.startswith("<"):
            j = page.rfind("<", i, j)  # a marker like 'class="footer' sits inside a tag: stop at that tag
        if j > i:
            stops.append(j)
    return html_to_text("<div " + page[i:min(stops) if stops else None])[:MAX_TEXT]


def _ld_job(page: str) -> dict[str, Any]:
    """The schema.org JobPosting the page declares in a JSON-LD script, or {}."""
    for block in re.findall(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return {}


def _ld_text(job: dict[str, Any]) -> str:
    parts = (job.get(k) for k in ("description", "responsibilities", "qualifications", "jobBenefits"))
    return "\n".join(html_to_text(str(p)) for p in parts if p and p != "UNAVAILABLE")[:MAX_TEXT]


def _ld_pay(job: dict[str, Any]) -> str:
    """JSON-LD baseSalary: {"currency": "USD", "value": {"minValue": 20, "maxValue": 25, "unitText": "HOUR"}}."""
    salary = job.get("baseSalary")
    if not isinstance(salary, dict):
        return ""
    value = salary.get("value")
    value = value if isinstance(value, dict) else {"value": value}
    try:
        low = float(value.get("minValue") or value.get("value") or 0)
        high = float(value.get("maxValue") or value.get("value") or 0)
    except (TypeError, ValueError):
        return ""
    period = _PERIODS.get(str(value.get("unitText") or salary.get("unitText") or "").upper(), "")
    currency = str(salary.get("currency") or job.get("salaryCurrency") or "USD")
    return from_range(low, high, currency, period)


def _plain_url(url: str) -> str:
    """The address without its tracking query (?utm_source=Simplify...)."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


# --- one reader per job board --------------------------------------------------
def _oracle_hcm(url: str) -> tuple[str, str]:
    """<x>.fa.<dc>.oraclecloud.com/hcmUI/CandidateExperience/en/sites/<site>/job/<id> -> requisition details."""
    parsed = urlparse(url)
    match = re.search(r"/sites/([^/]+)/(?:job|requisitions/preview)/(\d+)", parsed.path)
    if not match:
        return "", ""
    site, job_id = match.groups()
    data = get_json(f"https://{parsed.netloc}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                    f"?expand=all&onlyData=true&finder=ById;Id=%22{job_id}%22,siteNumber={site}")
    job = ((data or {}).get("items") or [{}])[0]
    # Short custom fields ("Salary Range: $24.05 - $63 hourly + sign-on bonus", "Career Area: Finance").
    fields = [f"{f.get('Prompt')}: {f.get('Value')}" for f in job.get("requisitionFlexFields") or []
              if f.get("Prompt") and f.get("Value") and len(str(f.get("Value"))) < 300]
    pay_lines = [line for line in fields if _PAY_FIELD.search(line.split(":")[0])]
    keys = ("ShortDescriptionStr", "ExternalDescriptionStr", "ExternalResponsibilitiesStr",
            "ExternalQualificationsStr", "OrganizationDescriptionStr", "CorporateDescriptionStr")
    text = "\n".join([*fields, *(html_to_text(str(job.get(k) or "")) for k in keys)]).strip()
    return text[:MAX_TEXT], find_pay("\n".join(pay_lines))


def _eightfold(url: str) -> tuple[str, str]:
    """<company>.eightfold.ai/careers/job/<id> (or ?pid=<id>; also jobs.infineon.com) -> the apply API."""
    parsed = urlparse(url)
    match = re.search(r"/job/(\d+)", parsed.path)
    job_id = match.group(1) if match else (parse_qs(parsed.query).get("pid") or [""])[0]
    if not job_id.isdigit():
        return "", ""
    job = get_json(f"https://{parsed.netloc}/api/apply/v2/jobs/{job_id}", headers={"Accept": "application/json"})
    return html_to_text(str(job.get("job_description") or ""))[:MAX_TEXT], ""


def _icims(url: str) -> tuple[str, str]:
    """<portal>.icims.com/jobs/<id>/job -> the posting alone (?in_iframe=1), header fields included."""
    parsed = urlparse(url)
    match = re.search(r"/jobs/(\d+)", parsed.path)
    if not match:
        return "", ""
    page = get_text(f"https://{parsed.netloc}/jobs/{match.group(1)}/job?in_iframe=1")
    text = _between(page, 'class="iCIMS_JobContent', ('class="iCIMS_JobOptions', 'class="iCIMS_Logo', "<footer"))
    job = _ld_job(page)
    return text or _ld_text(job), _ld_pay(job)


def _jibe(url: str) -> tuple[str, str]:
    """Jibe career sites (careers.amd.com/jobs/<id>?icims=1, <x>.jibeapply.com/jobs/<id>) -> their search API.

    Some sites keep the pay range in custom tags ("tags5": ["USD $83,200.00/Yr."])."""
    parsed = urlparse(url)
    match = re.search(r"/jobs/(\d+)", parsed.path)
    if not match:
        return "", ""
    job_id = match.group(1)
    data = get_json(f"https://{parsed.netloc}/api/jobs?keywords={job_id}&limit=10")
    jobs = [j.get("data") or {} for j in data.get("jobs") or []]
    job = next((j for j in jobs if job_id in (str(j.get("req_id")), str(j.get("slug")))), None)
    if job is None:
        return "", ""
    money = [str(v) for key, values in sorted(job.items()) if re.fullmatch(r"tags\d*", key)
             for v in (values if isinstance(values, list) else [values]) if _MONEY.search(str(v))]
    pay_lines = [f"Pay range: {v}" for v in money]
    parts = [str(job.get(k) or "") for k in ("description", "responsibilities", "qualifications")]
    text = "\n".join([*pay_lines, *(html_to_text(p) for p in parts)]).strip()
    return text[:MAX_TEXT], find_pay("\n".join(pay_lines))


def _successfactors(url: str) -> tuple[str, str]:
    """SAP SuccessFactors career sites (jobs.l3harris.com/job/<slug>/<id>/) -> the job page's posting."""
    page = get_text(_plain_url(url))
    text = _between(page, 'class="jobDisplay"', ('class="jobFooter', 'id="similar-jobs', "<footer", 'class="footer'))
    return text, ""


def _tiktok(url: str) -> tuple[str, str]:
    """lifeattiktok.com/search/<id>, joinbytedance.com/search/<id>, jobs.bytedance.com/en/position/<id>/detail.

    The page is rendered on the server and has "The hourly rate range for this position ... is $45 - $60"."""
    page = get_text(_plain_url(url))
    text = html_to_text(page)
    start = text.find("Share this listing:")
    if start < 0:
        return "", ""  # not a job page (an expired role lands on the search)
    text = text[start + len("Share this listing:"):]
    end = text.rfind("Apply to this job")  # the button under the posting; the site's footer follows
    return (text[:end] if end > 0 else text).strip()[:MAX_TEXT], ""


def _rippling(url: str) -> tuple[str, str]:
    """ats.rippling.com/<board>/jobs/<uuid> -> the board API, with pay ranges."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    if len(parts) < 3 or parts[1] != "jobs":
        return "", ""
    job = get_json(f"https://api.rippling.com/platform/api/ats/v1/board/{parts[0]}/jobs/{parts[2]}")
    description = job.get("description") or {}
    sections = description.values() if isinstance(description, dict) else [description]
    text = "\n".join(html_to_text(str(s or "")) for s in sections).strip()
    pay = ""
    for band in job.get("payRangeDetails") or []:
        low, high = band.get("rangeStart"), band.get("rangeEnd")
        if low or high:
            period = _PERIODS.get(str(band.get("frequency") or "").upper(), "")
            pay = from_range(low, high, str(band.get("currency") or "USD"), period)
            break
    return text[:MAX_TEXT], pay


def _workable(url: str) -> tuple[str, str]:
    """apply.workable.com/<account>/j/<shortcode>/ -> the job API."""
    match = re.search(r"workable\.com/([^/]+)/j/(\w+)", url)
    if not match:
        return "", ""
    job = get_json(f"https://apply.workable.com/api/v2/accounts/{match.group(1)}/jobs/{match.group(2)}")
    text = "\n".join(html_to_text(str(job.get(k) or "")) for k in ("description", "requirements", "benefits"))
    salary = job.get("salary") or {}
    pay = ""
    if isinstance(salary, dict):
        pay = from_range(salary.get("salary_from"), salary.get("salary_to"), str(salary.get("salary_currency") or "USD"), "")
    return text.strip()[:MAX_TEXT], pay


def _avature(url: str) -> tuple[str, str]:
    """Avature career sites (jobs.ea.com/en_US/careers/JobDetail/<slug>/<id>) -> the job page's fields."""
    page = get_text(_plain_url(url))
    return _between(page, 'class="article__content', ("<footer", 'class="footer')), ""


def _jsonld_page(url: str) -> tuple[str, str]:
    """Pages that declare a schema.org JobPosting (recruiting.paylocity.com/Recruiting/Jobs/Details/<id>)."""
    job = _ld_job(get_text(_plain_url(url)))
    return _ld_text(job), _ld_pay(job)


def _amazon(url: str) -> tuple[str, str]:
    """amazon.jobs/en/jobs/<id>/<slug> -> the search JSON the site uses, asked for that one id."""
    match = re.search(r"/jobs/(\d+)", urlparse(url).path)
    if not match:
        return "", ""
    data = get_json(f"https://www.amazon.jobs/en/search.json?base_query={match.group(1)}&result_limit=10")
    job = next((j for j in data.get("jobs") or [] if str(j.get("id_icims")) == match.group(1)), {})
    keys = ("description", "basic_qualifications", "preferred_qualifications")
    return "\n".join(html_to_text(str(job.get(k) or "")) for k in keys).strip()[:MAX_TEXT], ""


def _meta(url: str) -> tuple[str, str]:
    """www.metacareers.com/jobs/<id>/ -> the JSON-LD in the page (the text; Meta's pay is only drawn by the browser)."""
    match = re.search(r"/jobs/(\d+)", urlparse(url).path)
    if not match:
        return "", ""
    job = _ld_job(get_text(f"https://www.metacareers.com/jobs/{match.group(1)}/"))
    return _ld_text(job), _ld_pay(job)


MORE_READERS: list[tuple[re.Pattern[str], Callable[[str], tuple[str, str]]]] = [
    (re.compile(r"\.oraclecloud\.com/hcmUI/CandidateExperience/"), _oracle_hcm),
    (re.compile(r"\.eightfold\.ai/careers|jobs\.infineon\.com/careers/job/"), _eightfold),
    (re.compile(r"\.icims\.com/jobs/\d+"), _icims),
    (re.compile(r"/jobs/\d+/?\?(?:[^#]*&)?icims=1|\.jibeapply\.com/jobs/\d+"), _jibe),
    (re.compile(r"/job/[^/?#]+/\d+/?\?(?:[^#]*&)?ats=successfactors"), _successfactors),
    (re.compile(r"(?:lifeattiktok|joinbytedance)\.com/search/\d+|jobs\.bytedance\.com/(?:\w+/)?position/\d+"), _tiktok),
    (re.compile(r"ats\.rippling\.com/[^/]+/jobs/"), _rippling),
    (re.compile(r"apply\.workable\.com/[^/]+/j/"), _workable),
    (re.compile(r"/careers/JobDetail/"), _avature),
    (re.compile(r"recruiting\.paylocity\.com/Recruiting/Jobs/Details/"), _jsonld_page),
    (re.compile(r"(?:www\.)?amazon\.jobs/(?:\w+/)?jobs/\d+"), _amazon),
    (re.compile(r"metacareers\.com/jobs/\d+"), _meta),
]
