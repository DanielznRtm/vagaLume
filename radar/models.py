"""The single record shape that every source returns.

Each source module (greenhouse.py, gupy.py, ...) turns whatever its website
sends back into a list of `Opportunity` objects. Everything after that
(labelling, storage, reports) only ever deals with this one shape.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

# Used when we could not find a deadline anywhere.
NO_DEADLINE = "check page"


def make_id(url: str) -> str:
    """Return a short, stable id for a posting: a hash of its URL.

    The same URL always gives the same id, which is how we spot duplicates
    across runs. We strip tracking junk such as `?utm_source=...` first so
    that the same job linked from two places still gets one id.
    """
    clean = strip_tracking(url).strip().rstrip("/").lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]


def strip_tracking(url: str) -> str:
    """Remove utm_* / ref= style tracking parameters from a URL."""
    if "?" not in url:
        return url
    base, query = url.split("?", 1)
    kept = [
        part
        for part in query.split("&")
        if part
        and not part.lower().startswith(("utm_", "ref=", "source=", "jobboardsource=", "gh_src="))
    ]
    return base + ("?" + "&".join(kept) if kept else "")


@dataclass
class Opportunity:
    """One posting (or one watched program page)."""

    # --- filled in by the source module -----------------------------------
    title: str
    org: str
    source: str  # e.g. "greenhouse", "gupy", "programs"
    url: str
    location: str = ""
    remote: bool = False
    posted_date: str = ""  # ISO date "YYYY-MM-DD" when known
    deadline: str = NO_DEADLINE  # ISO date, or "check page"
    # Free text used only while labelling; it is NOT stored in the database
    # (that keeps data/radar.db small enough to commit every day).
    description: str = ""
    # Extra hints a source can pass to the labeller, e.g. the GitHub lists
    # mark roles that need US citizenship with an emoji.
    hints: list[str] = field(default_factory=list)
    # Optional manual labels (used by programs.yaml, where you set them).
    preset: dict[str, object] = field(default_factory=dict)
    # Whether the source still lists it as open (GitHub lists mark closed
    # roles with a lock emoji).
    is_open: bool = True
    # A short note shown in the report (e.g. "page changed on 2026-10-05").
    note: str = ""

    # --- filled in by radar.labels (or radar.llm) --------------------------
    area: str = "other"
    season: str = "unknown"
    regions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    calendar_note: str = ""
    labeled_by: str = "rules"

    # --- filled in by radar.db ---------------------------------------------
    first_seen: str = ""
    status: str = "new"

    @property
    def id(self) -> str:
        return make_id(self.url)
