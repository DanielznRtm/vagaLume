"""Write reports/latest.md (the web interface lives in docs/, see site.py).

Order, as requested:
  1. deadlines in the next 14 days
  2. new items (found in this run)
  3. watched program pages
  4. everything else that is open
Each list is grouped by category (area). Nothing is filtered out, but long
lists are cut at MAX_LINES / MAX_PER_AREA and "everything else" is a table of
counts, so the file stays small enough to open on GitHub; the website (docs/)
has every role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .db import StoredOpportunity
from .models import strip_tracking

AREA_ORDER = ["ML", "research", "SWE", "data", "quant", "hardware", "other"]
CALENDAR_SHORT = {
    "Dec–Feb": "fits Dec–Feb break",
    "Jul": "fits July break",
    "May–Aug": "clashes with semester",
    "year-round": "during semester",
    "unknown": "dates unknown",
}
SOON_DAYS = 14
# The report lists at most this many roles per section (or per area inside a
# section) so it stays small enough to open on GitHub; the website has them all.
MAX_LINES = 150
MAX_PER_AREA = 60
SITE_URL = "https://pedrocamargolince.github.io/vagaLume/"
REGION_ORDER = ["Brazil", "LatAm", "US/Canada", "Europe", "Asia/ME", "remote", "unknown"]
# Short symbols for warnings in the Markdown report (it must stay small
# enough for GitHub to display; the HTML report spells them out).
WARNING_SYMBOLS = {
    "US work auth?": "🛂",
    "PhD-level?": "🎓",
    "grad-year limit?": "📆",
    "unsure if student role": "❔",
    "new-grad role (after graduation)": "🆕grad",
}


@dataclass
class SourceHealth:
    name: str
    status: str = "ok"  # ok | partial | failed
    items: int = 0
    checked: int = 0
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


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


def group_by_area(items: list[StoredOpportunity]) -> list[tuple[str, list[StoredOpportunity]]]:
    groups = []
    for area in AREA_ORDER + sorted({o.area for o in items} - set(AREA_ORDER)):
        members = [o for o in items if o.area == area]
        if members:
            groups.append((area, members))
    return groups


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def _md_escape(text: str) -> str:
    return text.replace("|", "/").replace("[", "(").replace("]", ")").replace("\n", " ")


def _md_line(opp: StoredOpportunity, detailed: bool = False) -> str:
    """One bullet per posting. `detailed` adds location and the calendar note."""
    warnings = " ".join(WARNING_SYMBOLS.get(w, w) for w in opp.warnings)
    parts = [f"- [{_md_escape(opp.title)}]({strip_tracking(opp.url)}) — **{_md_escape(opp.org)}**"]
    if detailed and opp.location:
        parts.append(f"📍 {_md_escape(opp.location[:80])}")
    parts.append(f"{opp.season} · {'/'.join(opp.regions)}")
    if opp.deadline != "check page":
        parts.append(f"⏳ {opp.deadline}")
    if opp.pay:
        parts.append(f"💰 {opp.pay}")
    if warnings:
        parts.append(warnings)
    if detailed:
        parts.append(f"📅 {CALENDAR_SHORT.get(opp.season, '')}")
    if opp.status not in ("new", "seen"):
        parts.append(f"**[{opp.status}]**")
    if detailed and opp.status == "new" and opp.source != "programs":
        parts.append("**NEW**")
    if detailed and opp.note:
        parts.append(f"_{_md_escape(opp.note)}_")
    parts.append(f"`{opp.id}`")
    return " · ".join(parts)


def _more(hidden: int) -> list[str]:
    return [f"- _… and {hidden} more on the [website]({SITE_URL})._"] if hidden > 0 else []


def _md_list(items: list[StoredOpportunity], detailed: bool = False, limit: int = MAX_LINES) -> list[str]:
    return [_md_line(o, detailed) for o in items[:limit]] + _more(len(items) - limit)


def _md_grouped(items: list[StoredOpportunity], detailed: bool = False) -> list[str]:
    lines: list[str] = []
    for area, members in group_by_area(items):
        lines.append(f"\n### {area} ({len(members)})\n")
        lines.extend(_md_list(members, detailed, MAX_PER_AREA))
    return lines


def _md_counts(items: list[StoredOpportunity]) -> list[str]:
    """A table of how many roles there are per area and region."""
    regions = [r for r in REGION_ORDER if any(r in (o.regions or ["unknown"]) for o in items)]
    lines = ["", "| Area | " + " | ".join(regions) + " | Total |", "|---|" + "---|" * (len(regions) + 1)]
    for area, members in group_by_area(items):
        counts = [sum(1 for o in members if r in (o.regions or ["unknown"])) for r in regions]
        lines.append(f"| {area} | " + " | ".join(str(c) for c in counts) + f" | {len(members)} |")
    return lines


def render_markdown(data: ReportData) -> str:
    lines = [
        f"# vagaLume — {data.today}",
        "",
        f"**{data.total_open}** open · **{data.new_total}** new this run · "
        f"**{len(data.soon)}** deadlines in the next {SOON_DAYS} days · labels by {data.labeled_by}",
        "",
        "Nothing is filtered out: labels and warnings are hints, you decide. "
        "UNESP semesters: Mar–Jul and Aug–Dec. "
        "Searchable web version: the GitHub Pages site (see the README). "
        "Set your status in `config/status.yaml` using the `id`.",
        "",
        "Warnings: 🛂 US work auth? · 🎓 PhD-level? · 📆 grad-year limit? · ❔ unsure if student role · "
        "🆕grad new-grad role (after graduation). Each line: season · region · ⏳ deadline (if known).",
        "",
        "## Source health",
        "",
        "| Source | Status | Items | Checked | Time | Problems |",
        "|---|---|---|---|---|---|",
    ]
    for h in data.health:
        icon = {"ok": "✅", "partial": "⚠️", "failed": "❌"}.get(h.status, h.status)
        problems = "; ".join(_md_escape(e)[:120] for e in h.errors[:3])
        if len(h.errors) > 3:
            problems += f" (+{len(h.errors) - 3} more)"
        lines.append(f"| {h.name} | {icon} {h.status} | {h.items} | {h.checked} | {h.seconds:.0f}s | {problems} |")

    lines += ["", f"## ⏰ Deadlines in the next {SOON_DAYS} days ({len(data.soon)})", ""]
    lines += _md_list(data.soon, detailed=True) or ["_None found. Many postings don't state a deadline (\"check page\")._"]
    lines += ["", f"## 🆕 New this run ({len(data.new)} more, besides any above)"]
    # On a normal day the new list is short, so show details; on the very
    # first run everything is new, so keep it compact.
    lines += _md_grouped(data.new, detailed=len(data.new) <= 300) or ["", "_Nothing new today._"]
    lines += ["", f"## 📄 Watched program pages ({len(data.programs)})", ""]
    lines += [_md_line(o, detailed=True) for o in data.programs]
    lines += ["", f"## 📋 Everything else that is open ({len(data.rest)})", "",
              f"Too many to list here: search and filter them on the [website]({SITE_URL}). By area and region:"]
    lines += _md_counts(data.rest)
    if data.ignored:
        lines += ["", f"## 🙈 Ignored by you ({len(data.ignored)})", ""]
        lines += _md_list(data.ignored)
    return "\n".join(lines) + "\n"


def write_reports(data: ReportData, out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.md").write_text(render_markdown(data), encoding="utf-8")
