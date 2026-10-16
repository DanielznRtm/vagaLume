"""SAP SuccessFactors career sites, every country: SAP, Volvo Group, Volvo Cars...

Every SuccessFactors career site publishes any search as an RSS feed, and the
feed takes a `rows` parameter (the plain feed stops at 20 jobs):

  GET https://{host}/services/rss/job/?locale=en_US&keywords=(intern OR student ...)&rows=1000

One request returns every matching job in every language of the site (the
HTML search only shows one language at a time). The keywords are a full-text
search, so we keep only the student titles. The place is at the end of each
title, in several shapes:

  "SAP iXp Intern (w/m/d) - Industrie Marketing (Walldorf, DE, 69190)"
  "Customer Success Manager - ... (Hybrid) (Middlesex, GB, TW14 8HD)"
  "... - PHILIPPINES (Hybrid) (Taguig City, National Capital Region (NCR), PH, 1632)"
  "Examensarbete ... (Göteborg, SE)"

radar/sources/rss_jobs.py reads the short Brazilian feeds (Klabin, Nestlé);
this module is for the big worldwide ones: it understands every shape above
and writes the country in full ("SE" is Sweden here, not Sergipe).
Sites are in config/companies.yaml, section `successfactors`:
{host, name, keywords (optional)}.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

from ..http import get_text
from ..labels import is_student_candidate
from ..models import Opportunity
from ..textutil import html_to_text
from . import SourceResult
from .rss_jobs import _date
from .workday import VOCATIONAL

NAME = "successfactors"
FEED_URL = "https://{host}/services/rss/job/?locale=en_US&keywords={keywords}&rows={rows}"
ROWS = 1000  # SAP: ~420 matches for the default keywords (~6 MB)
DEFAULT_KEYWORDS = ("(intern OR internship OR student OR werkstudent OR praktikum OR praktikant OR thesis OR trainee"
                    " OR examensarbete OR stage OR stagiaire)")
# Student titles the shared labeller doesn't know yet (Swedish theses, German industry internships):
# kept with a "student" hint so the labeller trusts them.
EXTRA_STUDENT = re.compile(r"examensarbete|exjobb|industriepraktikum|\bpraktik\b|sommarjobb|summer job", re.I)

COUNTRIES = {
    "AE": "United Arab Emirates", "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BE": "Belgium",
    "BG": "Bulgaria", "BR": "Brazil", "CA": "Canada", "CH": "Switzerland", "CL": "Chile", "CN": "China",
    "CO": "Colombia", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EG": "Egypt", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GB": "United Kingdom", "GR": "Greece", "HK": "Hong Kong", "HU": "Hungary",
    "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India", "IT": "Italy", "JP": "Japan",
    "KR": "South Korea", "LU": "Luxembourg", "MA": "Morocco", "MX": "Mexico", "MY": "Malaysia", "NL": "Netherlands",
    "NO": "Norway", "NZ": "New Zealand", "PE": "Peru", "PH": "Philippines", "PL": "Poland", "PT": "Portugal",
    "RO": "Romania", "RS": "Serbia", "SA": "Saudi Arabia", "SE": "Sweden", "SG": "Singapore", "SK": "Slovakia",
    "TH": "Thailand", "TR": "Türkiye", "TW": "Taiwan", "UA": "Ukraine", "US": "United States", "VN": "Vietnam",
    "ZA": "South Africa",
}
# States are kept only where the labeller reads them (US, Brazil); elsewhere the region
# name or code adds nothing ("Tokyo, Tokyo, JP", "Madrid, M, ES").
_KEEP_STATE = {"US", "BR", "CA", "AU"}


def _trailing_parens(title: str) -> tuple[str, str]:
    """(title without its last "( ... )" group, the text inside), parentheses balanced."""
    text = title.rstrip()
    if not text.endswith(")"):
        return title.strip(), ""
    depth = 0
    for i in range(len(text) - 1, -1, -1):
        if text[i] == ")":
            depth += 1
        elif text[i] == "(":
            depth -= 1
            if depth == 0:
                return text[:i].strip(), text[i + 1:-1]
    return title.strip(), ""


def split_place(title: str) -> tuple[str, str]:
    """ "Intern (Walldorf, DE, 69190)" -> ("Intern", "Walldorf, Germany")."""
    rest, inside = _trailing_parens(title)
    parts = [p.strip() for p in inside.split(",") if p.strip()]
    if len(parts) < 2:
        return title.strip(), ""  # "(w/m/d)", "(Hybrid)": not a place
    if re.search(r"\d", parts[-1]):
        parts = parts[:-1]  # the postcode: "69190", "TW14 8HD", "100-0004"
    code = parts[-1] if len(parts) >= 2 else ""
    if not re.fullmatch(r"[A-Z]{2}", code):
        return title.strip(), ""
    city, middle = parts[0], parts[1:-1]
    state = [m for m in middle if code in _KEEP_STATE and re.fullmatch(r"[A-Z]{2,3}", m)]
    return rest, ", ".join([city, *state, COUNTRIES.get(code, code)])


def _clean_link(link: str) -> str:
    """Drop "?feedId=null&utm_source=J2WRSS..." from feed links."""
    return link.split("?", 1)[0].strip()


def parse(feed_xml: str | bytes, site: dict[str, Any]) -> list[Opportunity]:
    root = ET.fromstring(feed_xml.encode("utf-8") if isinstance(feed_xml, str) else feed_xml)
    items: list[Opportunity] = []
    seen: set[str] = set()
    for item in root.iter("item"):
        title, location = split_place((item.findtext("title") or "").strip())
        url = _clean_link(item.findtext("link") or "")
        extra = bool(EXTRA_STUDENT.search(title))
        if not url or url in seen or not (extra or is_student_candidate(title)) or VOCATIONAL.search(title):
            continue
        seen.add(url)
        items.append(
            Opportunity(
                title=title,
                org=str(site.get("name") or site["host"]),
                source=NAME,
                url=url,
                location=location,
                remote=bool(re.search(r"\bremote\b", title, re.I)),
                posted_date=_date(item.findtext("pubDate") or ""),
                description=html_to_text(item.findtext("description") or ""),
                hints=["student"] if extra else [],
            )
        )
    return items


def feed_url(site: dict[str, Any]) -> str:
    keywords = quote(str(site.get("keywords") or DEFAULT_KEYWORDS), safe="()")
    return FEED_URL.format(host=site["host"], keywords=keywords, rows=int(site.get("rows") or ROWS))


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for site in config.get("companies", {}).get("successfactors") or []:
        result.checked += 1
        try:
            result.items.extend(parse(get_text(feed_url(site), timeout=90), site))
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"{site.get('name') or site.get('host')}: {error}")
    return result
