"""SQLite storage (data/radar.db).

Two tables:
  opportunities  one row per posting, keyed by the URL hash (so no duplicates)
  page_hashes    for the program-page watcher: the last hash of each page

The `status` column is yours: new, seen, applied or ignored. The bot only
ever changes "new" -> "seen" (at the start of the next run). You can set it
by editing config/status.yaml (easiest, works from the GitHub website) or
with `python -m radar status <id> applied`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .models import Opportunity

STATUSES = ("new", "seen", "applied", "ignored")

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    org           TEXT NOT NULL,
    source        TEXT NOT NULL,
    location      TEXT,
    remote        INTEGER DEFAULT 0,
    url           TEXT NOT NULL,
    posted_date   TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    deadline      TEXT,
    area          TEXT,
    season        TEXT,
    regions       TEXT,           -- comma-separated, e.g. "Brazil,remote"
    warnings      TEXT,           -- comma-separated
    calendar_note TEXT,
    note          TEXT,
    labeled_by    TEXT,           -- "rules" or "claude"
    is_open       INTEGER DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS page_hashes (
    url          TEXT PRIMARY KEY,
    hash         TEXT NOT NULL,
    last_checked TEXT NOT NULL,
    last_changed TEXT NOT NULL
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _join(items: list[str]) -> str:
    return ",".join(items)


def _split(text: str | None) -> list[str]:
    return [part for part in (text or "").split(",") if part]


def existing_ids(conn: sqlite3.Connection) -> set[str]:
    return {row["id"] for row in conn.execute("SELECT id FROM opportunities")}


def mark_previous_new_as_seen(conn: sqlite3.Connection, today: str) -> None:
    """Items reported as "new" in an earlier run become "seen"."""
    conn.execute("UPDATE opportunities SET status='seen' WHERE status='new' AND first_seen < ?", (today,))


def upsert(conn: sqlite3.Connection, opp: Opportunity, today: str) -> bool:
    """Insert a new posting or refresh an existing one. Returns True if new.

    For existing rows we refresh the facts (title, deadline, labels...) but
    never touch first_seen or your status.
    """
    row = conn.execute("SELECT labeled_by FROM opportunities WHERE id=?", (opp.id,)).fetchone()
    values = {
        "id": opp.id, "title": opp.title, "org": opp.org, "source": opp.source,
        "location": opp.location, "remote": int(opp.remote), "url": opp.url,
        "posted_date": opp.posted_date, "deadline": opp.deadline, "area": opp.area,
        "season": opp.season, "regions": _join(opp.regions), "warnings": _join(opp.warnings),
        "calendar_note": opp.calendar_note, "note": opp.note, "labeled_by": opp.labeled_by,
        "is_open": int(opp.is_open), "last_seen": today,
    }
    if row is None:
        values["first_seen"] = today
        columns = ", ".join(values)
        marks = ", ".join(f":{name}" for name in values)
        conn.execute(f"INSERT INTO opportunities ({columns}) VALUES ({marks})", values)
        return True
    # Keep an earlier Claude label if this run only had keyword rules for it.
    if opp.labeled_by == "rules" and row["labeled_by"] == "claude":
        for name in ("area", "season", "regions", "warnings", "calendar_note", "labeled_by"):
            values.pop(name)
        if opp.deadline == "check page":
            values.pop("deadline")
    if not opp.note:
        values.pop("note")  # keep the old note (e.g. "page changed on ...")
    assignments = ", ".join(f"{name}=:{name}" for name in values if name != "id")
    conn.execute(f"UPDATE opportunities SET {assignments} WHERE id=:id", values)
    return False


def mark_missing_as_closed(conn: sqlite3.Connection, source: str, seen_ids: set[str]) -> None:
    """A healthy source that no longer lists a posting -> mark it closed."""
    rows = conn.execute("SELECT id FROM opportunities WHERE source=? AND is_open=1", (source,)).fetchall()
    gone = [row["id"] for row in rows if row["id"] not in seen_ids]
    conn.executemany("UPDATE opportunities SET is_open=0 WHERE id=?", [(i,) for i in gone])


def close_stale(conn: sqlite3.Connection, today: str, days: int = 30) -> None:
    """Anything not seen for `days` days is treated as closed.

    This covers sources that are often only partly healthy (so
    mark_missing_as_closed never runs for them).
    """
    cutoff = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    conn.execute("UPDATE opportunities SET is_open=0 WHERE last_seen < ?", (cutoff,))


def set_status(conn: sqlite3.Connection, opp_id: str, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    cursor = conn.execute("UPDATE opportunities SET status=? WHERE id=?", (status, opp_id))
    return cursor.rowcount > 0


@dataclass
class StoredOpportunity:
    """A row read back from the database, ready for the report."""

    id: str
    title: str
    org: str
    source: str
    location: str
    remote: bool
    url: str
    posted_date: str
    first_seen: str
    last_seen: str
    deadline: str
    area: str
    season: str
    regions: list[str]
    warnings: list[str]
    calendar_note: str
    note: str
    labeled_by: str
    is_open: bool
    status: str


def load_all(conn: sqlite3.Connection) -> list[StoredOpportunity]:
    rows = conn.execute("SELECT * FROM opportunities").fetchall()
    return [
        StoredOpportunity(
            id=r["id"], title=r["title"], org=r["org"], source=r["source"],
            location=r["location"] or "", remote=bool(r["remote"]), url=r["url"],
            posted_date=r["posted_date"] or "", first_seen=r["first_seen"],
            last_seen=r["last_seen"], deadline=r["deadline"] or "check page",
            area=r["area"] or "other", season=r["season"] or "unknown",
            regions=_split(r["regions"]), warnings=_split(r["warnings"]),
            calendar_note=r["calendar_note"] or "", note=r["note"] or "",
            labeled_by=r["labeled_by"] or "rules", is_open=bool(r["is_open"]), status=r["status"],
        )
        for r in rows
    ]


# --- page watcher -----------------------------------------------------------
def page_hash_changed(conn: sqlite3.Connection, url: str, new_hash: str, today: str) -> tuple[bool, str]:
    """Store the latest hash of a page.

    Returns (changed, last_changed_date). The very first time we see a page
    we just record it; that does not count as a change.
    """
    row = conn.execute("SELECT hash, last_changed FROM page_hashes WHERE url=?", (url,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO page_hashes (url, hash, last_checked, last_changed) VALUES (?, ?, ?, ?)",
            (url, new_hash, today, today),
        )
        return False, today
    if row["hash"] == new_hash:
        conn.execute("UPDATE page_hashes SET last_checked=? WHERE url=?", (today, url))
        return False, row["last_changed"]
    conn.execute(
        "UPDATE page_hashes SET hash=?, last_checked=?, last_changed=? WHERE url=?",
        (new_hash, today, today, url),
    )
    return True, today
