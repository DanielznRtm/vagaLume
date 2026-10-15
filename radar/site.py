"""Data for the web interface (docs/).

docs/index.html is a fixed page that you can read and edit by hand. Each
run only rewrites docs/data.json, which the page downloads and shows.
GitHub Pages serves the docs/ folder as a website.
"""

from __future__ import annotations

import json
from pathlib import Path

from .db import StoredOpportunity
from .models import strip_tracking
from .report import SourceHealth
from .skills import NAMES as SKILL_NAMES
from .sources.programs import application_months


def item_record(opp: StoredOpportunity, apply_months: list[int] | None = None) -> dict[str, object]:
    """Only the fields the page shows, to keep data.json small."""
    record = {
        "id": opp.id,
        "title": opp.title,
        "org": opp.org,
        "url": strip_tracking(opp.url),
        "location": opp.location,
        "area": opp.area,
        "season": opp.season,
        "regions": opp.regions,
        "warnings": opp.warnings,
        "deadline": opp.deadline if opp.deadline[:1].isdigit() else "",
        "pay": opp.pay,
        "skills": opp.skills,
        "fields": opp.fields,
        "levels": opp.levels,
        "states": opp.states,
        "workplaces": opp.workplaces,
        "posted": opp.posted_date,
        "added": opp.first_seen,
        "source": opp.source,
        "note": opp.note if opp.source == "programs" else "",
        "status": opp.status,
    }
    if apply_months:
        record["apply"] = apply_months  # programs: the months applications are usually open
    if opp.pay and opp.pay_from in ("text", "claude"):
        record["pay_text"] = 1  # read from the description, not a salary field: the page asks you to check it
    return record


def stats(opportunities: list[StoredOpportunity], health: list[SourceHealth], today: str) -> dict[str, object]:
    """Small summary used by the live badges in the README (shields.io reads it)."""
    open_items = [o for o in opportunities if o.is_open]
    healthy = sum(1 for h in health if h.status == "ok")
    return {
        "updated": today,
        "open": f"{len(open_items):,}",
        "new": str(sum(1 for o in open_items if o.first_seen == today and o.source != "programs")),
        "with_pay": f"{sum(1 for o in open_items if o.pay):,}",
        "sources": f"{healthy}/{len(health)} healthy",
        "sources_ok": healthy == len(health),
    }


def write_data(
    opportunities: list[StoredOpportunity],
    health: list[SourceHealth],
    today: str,
    labeled_by: str,
    out_dir: str | Path,
    subscribe: dict[str, str] | None = None,
    programs: list[dict[str, object]] | None = None,
) -> Path:
    """Write docs/data.json with every open opportunity.

    `programs` is config/programs.yaml: its `applications` field (when applications
    usually open) goes to the page as month numbers.
    """
    windows = {str(p["url"]): application_months(str(p.get("applications") or "")) for p in programs or []}
    payload = {
        "updated": today,
        "labeledBy": labeled_by,
        "skillNames": SKILL_NAMES,  # the résumé prompt on the site lists these
        "subscribe": subscribe or {},  # the "daily updates" panel (radar/digest.py)
        "sources": [
            {"name": h.name, "status": h.status, "items": h.items, "problems": h.errors[:5]} for h in health
        ],
        "items": [item_record(o, windows.get(o.url) if o.source == "programs" else None) for o in opportunities if o.is_open],
    }
    path = Path(out_dir) / "data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # One item per line: easier to read in git diffs than one giant line.
    lines = ",\n".join(json.dumps(item, ensure_ascii=False) for item in payload.pop("items"))
    head = json.dumps(payload, ensure_ascii=False)[:-1]
    path.write_text(f'{head}, "items": [\n{lines}\n]}}\n', encoding="utf-8")
    summary = stats(opportunities, health, today)
    (Path(out_dir) / "stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return path
