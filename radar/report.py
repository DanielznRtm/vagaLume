"""The run's summary: source health and the open roles sorted into sections
(deadlines soon, new, program pages, everything else). The private digest
(radar/notify.py) is built from it; the website (radar/site.py) has every role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .db import StoredOpportunity

SOON_DAYS = 14


@dataclass
class SourceHealth:
    name: str
    status: str = "ok"  # ok | partial | failed
    items: int = 0
    checked: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    failed_orgs: set[str] = field(default_factory=set)  # companies whose board failed (see SourceResult)


@dataclass
class ReportData:
    """Everything a report needs, already sorted into sections."""

    today: str
    labeled_by: str
    health: list[SourceHealth]
    soon: list[StoredOpportunity]
    new: list[StoredOpportunity]
    programs: list[StoredOpportunity]
    rest: list[StoredOpportunity]
    ignored: list[StoredOpportunity]
    total_open: int
    new_total: int  # all items first seen today, including those listed under "deadlines soon"


def _sort_key(opp: StoredOpportunity) -> tuple[str, str, str]:
    deadline = opp.deadline if opp.deadline[:1].isdigit() else "9999"
    # Newest first: invert the date string so a plain ascending sort works.
    posted = opp.posted_date or opp.first_seen
    inverted = "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in posted)
    return (deadline, inverted, opp.title.lower())


def deadline_is_soon(opp: StoredOpportunity, today: date) -> bool:
    if not opp.deadline[:1].isdigit():
        return False
    try:
        deadline = date.fromisoformat(opp.deadline)
    except ValueError:
        return False
    return today <= deadline <= today + timedelta(days=SOON_DAYS)


def build(opportunities: list[StoredOpportunity], health: list[SourceHealth], today: str, labeled_by: str) -> ReportData:
    """Split the open opportunities into the report sections."""
    day = date.fromisoformat(today)
    open_items = sorted((o for o in opportunities if o.is_open), key=_sort_key)
    ignored = [o for o in open_items if o.status == "ignored"]
    active = [o for o in open_items if o.status != "ignored"]
    soon = [o for o in active if deadline_is_soon(o, day)]
    programs = [o for o in active if o.source == "programs" and o not in soon]
    all_new = [o for o in active if o.first_seen == today and o.source != "programs"]
    # Each item appears in exactly one section, the first one that fits.
    new = [o for o in all_new if o not in soon]
    shown = {o.id for o in soon} | {o.id for o in new} | {o.id for o in programs}
    rest = [o for o in active if o.id not in shown]
    return ReportData(today, labeled_by, health, soon, new, programs, rest, ignored, len(open_items), len(all_new))
