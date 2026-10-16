"""Career sites of single companies with many student programs: BCG, Goldman
Sachs and IBM. Each has its own public search route, no login:

  BCG (careers.bcg.com, a Phenom site):
    POST https://careers.bcg.com/widgets   {"ddoKey": "refineSearch",
         "selected_fields": {"country": ["Brazil"], "jobType": ["Internship"]}, ...}
    -> 50 internships per request with title, cities, posting date and a short summary.
  Goldman Sachs (higher.gs.com):
    POST https://api-higher.gs.com/gateway/api/v1/graphql   (query GetCampusRoles, experience CAMPUS,
    location filter "Brazil") -> the internships, off-cycle and new analyst roles of a country.
  IBM (ibm.com/careers):
    POST https://www-api.ibm.com/search/api/v2   (appId "careers", filter country + level "Internship")
    -> title, city, work model, posting date and a short summary.

We keep student roles only (intern, estágio, summer, off-cycle...), so a GS
"New Analyst" (a full-time job after graduation) is left out. The countries to
search are in config/companies.yaml, section `company_sites` (default: Brazil).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from ..http import post_json
from ..labels import student_level
from ..models import Opportunity
from ..places import UFS, city_state
from ..textutil import html_to_text, iso_date
from . import SourceResult

BCG = "bcg"
GOLDMAN = "goldman"
IBM = "ibm"

BCG_URL = "https://careers.bcg.com/widgets"
BCG_JOB_URL = "https://careers.bcg.com/global/en/job/{id}"
BCG_PAGE = 50
GS_URL = "https://api-higher.gs.com/gateway/api/v1/graphql"
GS_JOB_URL = "https://higher.gs.com/roles/{id}"
GS_PAGE = 20
IBM_URL = "https://www-api.ibm.com/search/api/v2"
IBM_PAGE = 100
MAX_PAGES = 5

_STATE_UF = {name: uf for uf, name in UFS.items()}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


def _countries(config: dict[str, Any], company: str) -> list[str]:
    sites = config.get("companies", {}).get("company_sites") or {}
    return list((sites.get(company) or {}).get("countries") or ["Brazil"])


def _place(city: str, state: str, country: str) -> str:
    """("Rio de Janeiro", "", "Brazil") -> "Rio de Janeiro, RJ, Brazil"; ("Sao Paulo", "Sao Paulo", "Brazil") -> "Sao Paulo, SP, Brazil"."""
    city, state, country = city.strip(), state.strip(), country.strip()
    if country.lower() in ("brazil", "brasil", "br"):
        country = "Brazil"
        state = _STATE_UF.get(_plain(state), state) or city_state(city)
    return ", ".join(part for part in (city, state, country) if part)


# --- BCG ---------------------------------------------------------------------
def bcg_body(country: str, start: int) -> dict[str, Any]:
    return {
        "lang": "en_global", "deviceType": "desktop", "country": "global", "pageName": "search-results",
        "ddoKey": "refineSearch", "sortBy": "", "subsearch": "", "from": start, "jobs": True, "counts": True,
        "all_fields": ["country", "jobType"], "size": BCG_PAGE, "clearAll": False, "jdsource": "facets",
        "isSliderEnable": False, "pageId": "page20", "siteType": "external", "keywords": "", "global": True,
        "selected_fields": {"country": [country], "jobType": ["Internship"]}, "locationData": {},
    }


def parse_bcg(payload: dict[str, Any]) -> tuple[list[Opportunity], int]:
    """(roles in this answer, total in the search). The search asks for BCG's job type
    "Internship" only, so every role in the answer is kept."""
    block = (payload or {}).get("refineSearch") or {}
    jobs = (block.get("data") or {}).get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("unexpected answer from BCG (no refineSearch jobs)")
    items: list[Opportunity] = []
    for job in jobs:
        title = re.sub(r"[\u200b\s]+", " ", str(job.get("title") or "")).strip()
        places = []
        for place in job.get("multi_location") or [job.get("location") or ""]:
            parts = [p.strip() for p in str(place).split(",")]
            places.append(_place(parts[0], parts[1] if len(parts) > 2 else "", parts[-1]) if len(parts) > 1 else str(place))
        items.append(
            Opportunity(
                title=title,
                org="BCG",
                source=BCG,
                url=BCG_JOB_URL.format(id=job["jobId"]),
                location=" / ".join(dict.fromkeys(p for p in places if p)),
                posted_date=iso_date(job.get("postedDate") or job.get("dateCreated")),
                description=" ".join(str(job.get(k) or "") for k in ("category", "descriptionTeaser")).strip(),
                hints=["student"],
            )
        )
    return items, int(block.get("totalHits") or 0)


def fetch_bcg(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for country in _countries(config, "bcg"):
        for page in range(MAX_PAGES):
            result.checked += 1
            try:
                items, total = parse_bcg(post_json(BCG_URL, bcg_body(country, page * BCG_PAGE)))
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{country}: {error}")
                break
            result.items.extend(items)
            if (page + 1) * BCG_PAGE >= total:
                break
    return result


# --- Goldman Sachs -----------------------------------------------------------
GS_QUERY = """query GetCampusRoles($searchQueryInput: RoleSearchQueryInput!) {
  roleSearch(searchQueryInput: $searchQueryInput) {
    totalCount
    items { roleId corporateTitle jobTitle jobFunction locations { primary state country city } status division
            externalSource { sourceId } educationLevel startDate }
  }
}"""
# Corporate titles of GS campus roles that are for students (the others are "Analyst" / "Associate":
# full-time jobs after graduation).
GS_STUDENT_TITLES = re.compile(r"summer|seasonal|intern|off[- ]cycle|insight|apprentice", re.I)


def goldman_body(country: str, page: int) -> dict[str, Any]:
    return {
        "operationName": "GetCampusRoles",
        "query": GS_QUERY,
        "variables": {"searchQueryInput": {
            "page": {"pageSize": GS_PAGE, "pageNumber": page},
            "sort": {"sortStrategy": "RELEVANCE", "sortOrder": "DESC"},
            "filters": [{"filterCategoryType": "LOCATION", "filters": [{"filter": country, "subFilters": []}]}],
            "experiences": ["CAMPUS"],
            "searchTerm": "",
        }},
    }


def parse_goldman(payload: dict[str, Any]) -> tuple[list[Opportunity], int]:
    search = ((payload or {}).get("data") or {}).get("roleSearch")
    if not isinstance(search, dict) or not isinstance(search.get("items"), list):
        raise ValueError(f"unexpected answer from Goldman Sachs: {str(payload)[:120]}")
    items: list[Opportunity] = []
    for role in search["items"]:
        title = str(role.get("jobTitle") or "").strip()
        corporate = str(role.get("corporateTitle") or "")
        if not GS_STUDENT_TITLES.search(corporate) and student_level(title) != "yes":
            continue
        places = [_place(str(p.get("city") or ""), str(p.get("state") or ""), str(p.get("country") or ""))
                  for p in role.get("locations") or []]
        source_id = (role.get("externalSource") or {}).get("sourceId") or str(role.get("roleId") or "").split("_")[0]
        items.append(
            Opportunity(
                title=title,
                org="Goldman Sachs",
                source=GOLDMAN,
                url=GS_JOB_URL.format(id=source_id),
                location=" / ".join(dict.fromkeys(p for p in places if p)),
                posted_date=iso_date(role.get("startDate")),
                description=f"{corporate}. {role.get('division') or ''}. {role.get('jobFunction') or ''}".strip(" ."),
                hints=["student"],
            )
        )
    return items, int(search.get("totalCount") or 0)


def fetch_goldman(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for country in _countries(config, "goldman"):
        for page in range(MAX_PAGES):
            result.checked += 1
            try:
                items, total = parse_goldman(post_json(GS_URL, goldman_body(country, page),
                                                       headers={"x-higher-request-id": str(uuid.uuid4())}))
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{country}: {error}")
                break
            result.items.extend(items)
            if (page + 1) * GS_PAGE >= total:
                break
    return result


# --- IBM ---------------------------------------------------------------------
IBM_FIELDS = ["_id", "title", "url", "description", "field_keyword_05", "field_keyword_08", "field_keyword_17",
              "field_keyword_18", "field_keyword_19", "dcdate"]
WORK_MODELS = {"hybrid": "hybrid", "remote": "remote", "on-site": "on-site", "onsite": "on-site"}


def ibm_body(country: str, start: int) -> dict[str, Any]:
    """field_keyword_05 is the country, field_keyword_18 the level (Internship, Entry Level, Professional)."""
    return {
        "appId": "careers", "scopes": ["careers2"], "query": {"bool": {"must": []}},
        "post_filter": {"bool": {"must": [{"term": {"field_keyword_05": country}},
                                          {"terms": {"field_keyword_18": ["Internship"]}}]}},
        "size": IBM_PAGE, "from": start, "sort": [{"dcdate": "desc"}, {"_score": "desc"}], "lang": "zz",
        "localeSelector": {}, "p": 1, "sm": {"query": "", "lang": "zz"}, "_source": IBM_FIELDS,
    }


# "Ã" / "Â" / "â" followed by what the second byte of a UTF-8 letter looks like in Windows-1252.
_MANGLED = re.compile("[\u00c3\u00c2\u00e2][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013-\u203a\u20ac\u2122]")


def _unmangle(text: str) -> str:
    """IBM's index has UTF-8 read as Windows-1252 ("SÃO PAULO", "Youâ€™ll"): undo it."""
    if not _MANGLED.search(text):
        return text
    for codec in ("cp1252", "latin-1"):
        try:
            return text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def _ibm_place(text: str, searched: str = "Brazil") -> str:
    """ "SÃO PAULO, BR" -> "São Paulo, SP, Brazil"; "No City, BR" -> "Brazil".
    The two-letter code is replaced by the country we searched ("CA" is Canada, not California)."""
    city, _, country = _unmangle(text).rpartition(",")
    city, country = city.strip(), country.strip()
    if city.lower() in ("no city", "multiple cities", ""):
        city = ""
    city = city.title() if city.isupper() else city
    if len(country) <= 3 or country.lower() in ("no city", "multiple cities"):
        country = searched  # also "Multiple Cities" (no comma: all of it is the "country")
    return _place(city, "", country)


def parse_ibm(payload: dict[str, Any], country: str = "Brazil") -> tuple[list[Opportunity], int]:
    hits = (payload or {}).get("hits")
    if not isinstance(hits, dict) or not isinstance(hits.get("hits"), list):
        raise ValueError(f"unexpected answer from IBM: {str(payload)[:120]}")
    items: list[Opportunity] = []
    for hit in hits["hits"]:
        job = hit.get("_source") or {}
        title = _unmangle(str(job.get("title") or "")).strip()
        level = str(job.get("field_keyword_18") or "")
        # "Application Developer - STUDENT CONVERSION": full-time jobs for IBM's own interns.
        if level != "Internship" and (student_level(title) != "yes" or "conversion" in title.lower()):
            continue
        model = WORK_MODELS.get(str(job.get("field_keyword_17") or "").lower(), "")
        items.append(
            Opportunity(
                title=title,
                org="IBM",
                source=IBM,
                url=str(job.get("url") or ""),
                location=_ibm_place(str(job.get("field_keyword_19") or ""), country) + (f" ({model})" if model else ""),
                remote=model == "remote",
                posted_date=iso_date(job.get("dcdate")),
                description=html_to_text(_unmangle(f"{job.get('field_keyword_08') or ''}. {job.get('description') or ''}")),
                hints=["student"] if level == "Internship" else [],
            )
        )
    total = hits.get("total") or {}
    return items, int(total.get("value") if isinstance(total, dict) else total or 0)


def fetch_ibm(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for country in _countries(config, "ibm"):
        for page in range(MAX_PAGES):
            result.checked += 1
            try:
                items, total = parse_ibm(post_json(IBM_URL, ibm_body(country, page * IBM_PAGE)), country)
            except Exception as error:  # noqa: BLE001
                result.errors.append(f"{country}: {error}")
                break
            result.items.extend(items)
            if (page + 1) * IBM_PAGE >= total:
                break
    return result
