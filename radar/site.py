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


def item_record(opp: StoredOpportunity) -> dict[str, object]:
    """Only the fields the page shows, to keep data.json small."""
    return {
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
        "posted": opp.posted_date,
        "added": opp.first_seen,
        "source": opp.source,
        "note": opp.note if opp.source == "programs" else "",
        "status": opp.status,
    }


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
) -> Path:
    """Write docs/data.json with every open opportunity."""
    payload = {
        "updated": today,
        "labeledBy": labeled_by,
        "sources": [
            {"name": h.name, "status": h.status, "items": h.items, "problems": h.errors[:5]} for h in health
        ],
        "items": [item_record(o) for o in opportunities if o.is_open],
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
