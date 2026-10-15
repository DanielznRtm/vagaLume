"""Job feeds in plain RSS: SAP SuccessFactors career sites (Klabin, Nestlé)
and Avature ones (Siemens, TotalEnergies).

SuccessFactors sites publish any search as a feed:
  {base}/services/rss/job/?locale=pt_BR&keywords=(estágio)
with the place in the title: "Estagiário ... | Itajaí/SC (Itajaí, SC, BR, 88311-480)".
Avature sites have a feed per search: .../SearchJobs/Brazil/feed/

We keep the student titles. The feeds are in config/companies.yaml, section
`rss_feeds`: {url, name, country} (country: where the feed's roles are when
the title doesn't say, e.g. Brazil).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

from ..http import get_text
from ..labels import is_student_candidate
from ..models import Opportunity
from ..textutil import html_to_text
from . import SourceResult

NAME = "rss_jobs"
# "(Itajaí, SC, BR, 88311-480)" or "(Araras, BR, 13690-000)" at the end of a SuccessFactors title.
_PLACE = re.compile(r"\s*\(([^(),]+?),\s*(?:([A-Z]{2}),\s*)?([A-Z]{2})(?:,\s*[\w-]+)?\)\s*$")
COUNTRIES = {"BR": "Brazil", "US": "United States", "DE": "Germany", "FR": "France", "MX": "Mexico"}


def _date(text: str) -> str:
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse(feed_xml: str, feed: dict[str, Any]) -> list[Opportunity]:
    root = ET.fromstring(feed_xml.encode("utf-8") if isinstance(feed_xml, str) else feed_xml)
    items: list[Opportunity] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        place = _PLACE.search(title)
        if place:
            city, state, country = place.groups()
            location = ", ".join(p for p in (city.strip(), state, COUNTRIES.get(country, country)) if p)
            title = title[: place.start()].strip()
        else:
            location = str(feed.get("country") or "")
        if not is_student_candidate(title):
            continue
        items.append(
            Opportunity(
                title=title,
                org=str(feed.get("name") or ""),
                source=NAME,
                url=(item.findtext("link") or "").strip(),
                location=location,
                posted_date=_date(item.findtext("pubDate") or ""),
                description=html_to_text(item.findtext("description") or ""),
            )
        )
    return items


def fetch(config: dict[str, Any]) -> SourceResult:
    result = SourceResult()
    for feed in config.get("companies", {}).get("rss_feeds") or []:
        result.checked += 1
        try:
            result.items.extend(parse(get_text(feed["url"]), feed))
        except Exception as error:  # noqa: BLE001
            result.errors.append(f"{feed.get('name')}: {error}")
    return result
