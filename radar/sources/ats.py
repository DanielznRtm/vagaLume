"""Shared loop for job-board APIs that are organised per company
(Greenhouse, Lever, Ashby): read the company list, fetch each board,
and keep going when one board fails."""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..models import Opportunity
from . import SourceResult

log = logging.getLogger(__name__)


def fetch_boards(
    companies: list[dict[str, Any]],
    fetch_one: Callable[[str], Any],
    parse: Callable[[Any, str], list[Opportunity]],
    source_name: str,
) -> SourceResult:
    """Fetch every company's board; collect items and per-company errors."""
    result = SourceResult()
    for company in companies:
        slug = company["slug"]
        org = company.get("name", slug)
        result.checked += 1
        try:
            data = fetch_one(slug)
            result.items.extend(parse(data, org))
        except Exception as error:  # noqa: BLE001 - one board must not stop the others
            message = f"{org} ({slug}): {error}"
            log.warning("%s board failed: %s", source_name, message)
            result.errors.append(message)
    return result
