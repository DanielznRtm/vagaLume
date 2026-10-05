"""Write reports/latest.md and reports/index.html.

Order, as requested:
  1. deadlines in the next 14 days
  2. new items (found in this run)
  3. watched program pages
  4. everything else that is open
Each list is grouped by category (area). Nothing is filtered out; the
HTML page has filters, but every box starts ticked.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
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


def _md_grouped(items: list[StoredOpportunity], detailed: bool = False) -> list[str]:
    lines: list[str] = []
    for area, members in group_by_area(items):
        lines.append(f"\n### {area} ({len(members)})\n")
        lines.extend(_md_line(o, detailed) for o in members)
    return lines


def render_markdown(data: ReportData) -> str:
    lines = [
        f"# Opportunity Radar — {data.today}",
        "",
        f"**{data.total_open}** open · **{data.new_total}** new this run · "
        f"**{len(data.soon)}** deadlines in the next {SOON_DAYS} days · labels by {data.labeled_by}",
        "",
        "Nothing is filtered out: labels and warnings are hints, you decide. "
        "UNESP semesters: Mar–Jul and Aug–Dec. "
        "Filterable version with full details: [`index.html`](index.html). "
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
    lines += [_md_line(o, detailed=True) for o in data.soon] or ["_None found. Many postings don't state a deadline (\"check page\")._"]
    lines += ["", f"## 🆕 New this run ({len(data.new)} more, besides any above)"]
    # On a normal day the new list is short, so show details; on the very
    # first run everything is new, so keep it compact.
    lines += _md_grouped(data.new, detailed=len(data.new) <= 300) or ["", "_Nothing new today._"]
    lines += ["", f"## 📄 Watched program pages ({len(data.programs)})", ""]
    lines += [_md_line(o, detailed=True) for o in data.programs]
    lines += ["", f"## 📋 Everything else that is open ({len(data.rest)})"]
    lines += _md_grouped(data.rest)
    if data.ignored:
        lines += ["", f"## 🙈 Ignored by you ({len(data.ignored)})", ""]
        lines += [_md_line(o) for o in data.ignored]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# HTML (one self-contained file; the filtering happens in the browser)
# ---------------------------------------------------------------------------
def _item_json(opp: StoredOpportunity, section: str) -> dict[str, object]:
    record = asdict(opp)
    record["section"] = section
    record["calendar_short"] = CALENDAR_SHORT.get(opp.season, "")
    return record


def render_html(data: ReportData) -> str:
    items: list[dict[str, object]] = []
    for section, members in (
        ("soon", data.soon), ("new", data.new), ("programs", data.programs),
        ("rest", data.rest), ("ignored", data.ignored),
    ):
        items.extend(_item_json(o, section) for o in members)
    payload = {
        "today": data.today,
        "labeledBy": data.labeled_by,
        "areaOrder": AREA_ORDER,
        "health": [asdict(h) for h in data.health],
        "items": items,
    }
    # "</" inside JSON would end the <script> tag early, so escape it.
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__DATA__", blob).replace("__TITLE__", html.escape(f"Opportunity Radar — {data.today}"))


def write_reports(data: ReportData, out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.md").write_text(render_markdown(data), encoding="utf-8")
    (out / "index.html").write_text(render_html(data), encoding="utf-8")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --bg:#fafafa; --fg:#1d1d1f; --muted:#6b6b70; --card:#fff; --line:#e3e3e6; --accent:#2f5bd3;
        --warn-bg:#fff4e0; --warn-fg:#8a4b00; --chip:#eef1f8; --new:#e6f6ea; --new-fg:#1c6b33; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141416; --fg:#ececf0; --muted:#9a9aa3; --card:#1d1d21; --line:#2e2e34; --accent:#8fb0ff;
          --warn-bg:#3a2a10; --warn-fg:#ffcf8a; --chip:#272b36; --new:#173523; --new-fg:#8fe0a8; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
main { max-width:1100px; margin:0 auto; padding:16px; }
h1 { font-size:1.5rem; margin:.2em 0; } h2 { font-size:1.2rem; margin:1.6em 0 .4em; } h3 { font-size:1rem; margin:1.2em 0 .4em; color:var(--muted); }
.summary { color:var(--muted); }
details.filters { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin:12px 0; }
details.filters summary { cursor:pointer; font-weight:600; }
.fgroup { margin:8px 0; } .fgroup b { display:block; font-size:.85rem; color:var(--muted); margin-bottom:2px; }
.fgroup label { display:inline-block; margin:2px 10px 2px 0; font-size:.9rem; white-space:nowrap; }
.fgroup .hint { font-size:.8rem; color:var(--muted); }
input[type=search] { width:100%; padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--fg); font-size:1rem; }
button { font:inherit; padding:4px 10px; border-radius:6px; border:1px solid var(--line); background:var(--chip); color:var(--fg); cursor:pointer; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin:8px 0; }
.card a.title { color:var(--accent); font-weight:600; text-decoration:none; } .card a.title:hover { text-decoration:underline; }
.meta { color:var(--muted); font-size:.88rem; margin-top:2px; overflow-wrap:anywhere; }
.chips { margin-top:6px; display:flex; flex-wrap:wrap; gap:4px; }
.chip { background:var(--chip); border-radius:999px; padding:1px 9px; font-size:.8rem; }
.chip.warn { background:var(--warn-bg); color:var(--warn-fg); }
.chip.new { background:var(--new); color:var(--new-fg); font-weight:600; }
.id { font-family:ui-monospace,monospace; font-size:.75rem; color:var(--muted); user-select:all; }
table.health { border-collapse:collapse; width:100%; font-size:.88rem; }
table.health td, table.health th { border-bottom:1px solid var(--line); padding:4px 6px; text-align:left; vertical-align:top; }
.health-wrap { overflow-x:auto; }
.empty { color:var(--muted); font-style:italic; }
</style>
</head>
<body>
<main>
<h1>Opportunity Radar</h1>
<div class="summary" id="summary"></div>
<p class="summary">Nothing is hidden by default. Labels and warnings are hints from keyword rules (or Claude), not decisions. UNESP semesters: Mar–Jul and Aug–Dec.</p>

<details class="filters" open>
  <summary>Filters</summary>
  <div class="fgroup"><input type="search" id="q" placeholder="Search title, org, location…"></div>
  <div id="filter-groups"></div>
  <div class="fgroup"><button id="reset">Tick everything again</button> <span class="hint" id="count"></span></div>
</details>

<div id="sections"></div>

<h2>Source health</h2>
<div class="health-wrap"><table class="health" id="health"></table></div>
</main>

<script id="radar-data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('radar-data').textContent);
const ITEMS = DATA.items;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// Each filter: which field, and how multi-valued fields match.
//   any  = show if ANY of the item's values is ticked (regions)
//   all  = show only if ALL of the item's values are ticked (warnings:
//          untick "PhD-level?" to hide items carrying that warning)
const FILTERS = [
  {key:'area', label:'Area'},
  {key:'season', label:'Season'},
  {key:'regions', label:'Region', multi:'any', hint:'shown if any of its regions is ticked'},
  {key:'warnings', label:'Warnings', multi:'all', none:'(no warnings)', hint:'untick a warning to hide items that have it'},
  {key:'source', label:'Source'},
  {key:'status', label:'Status'},
];
const state = {};
function valuesOf(item, f) {
  const v = item[f.key];
  if (Array.isArray(v)) return v.length ? v : (f.none ? [f.none] : []);
  return [v];
}
function buildFilters() {
  const box = document.getElementById('filter-groups');
  box.innerHTML = '';
  for (const f of FILTERS) {
    const counts = {};
    ITEMS.forEach(it => valuesOf(it, f).forEach(v => counts[v] = (counts[v] || 0) + 1));
    const order = f.key === 'area' ? DATA.areaOrder : [];
    const vals = Object.keys(counts).sort((a, b) => {
      const ia = order.indexOf(a), ib = order.indexOf(b);
      if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
      return a.localeCompare(b);
    });
    state[f.key] = new Set(vals);
    const div = document.createElement('div');
    div.className = 'fgroup';
    div.innerHTML = `<b>${f.label}${f.hint ? ` <span class="hint">(${f.hint})</span>` : ''}</b>` +
      vals.map(v => `<label><input type="checkbox" data-k="${esc(f.key)}" value="${esc(v)}" checked> ${esc(v)} <span class="hint">${counts[v]}</span></label>`).join('');
    box.appendChild(div);
  }
  box.querySelectorAll('input[type=checkbox]').forEach(cb => cb.addEventListener('change', e => {
    const set = state[e.target.dataset.k];
    e.target.checked ? set.add(e.target.value) : set.delete(e.target.value);
    render();
  }));
}
function visible(it) {
  const q = document.getElementById('q').value.trim().toLowerCase();
  if (q && !`${it.title} ${it.org} ${it.location} ${it.note} ${it.id}`.toLowerCase().includes(q)) return false;
  for (const f of FILTERS) {
    const vals = valuesOf(it, f), set = state[f.key];
    if (f.multi === 'all') { if (!vals.every(v => set.has(v))) return false; }
    else if (!vals.some(v => set.has(v))) return false;
  }
  return true;
}
function card(it) {
  const warn = it.warnings.map(w => `<span class="chip warn">⚠️ ${esc(w)}</span>`).join('');
  const isNew = it.first_seen === DATA.today && it.source !== 'programs';
  const deadline = it.deadline === 'check page' ? 'deadline: check page' : `deadline: <b>${esc(it.deadline)}</b>`;
  return `<div class="card">
    <a class="title" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}</a>
    <div class="meta"><b>${esc(it.org)}</b>${it.location ? ' · 📍 ' + esc(it.location) : ''}${it.remote ? ' · remote' : ''}</div>
    <div class="meta">${deadline} · posted ${esc(it.posted_date || '?')} · first seen ${esc(it.first_seen)} · via ${esc(it.source)}${it.labeled_by === 'claude' ? ' · labels by Claude' : ''}</div>
    <div class="meta">📅 ${esc(it.calendar_note)}</div>
    ${it.note ? `<div class="meta">📝 ${esc(it.note)}</div>` : ''}
    <div class="chips">${isNew ? '<span class="chip new">NEW</span>' : ''}<span class="chip">${esc(it.area)}</span><span class="chip">🗓 ${esc(it.season)}</span>${it.regions.map(r => `<span class="chip">🌎 ${esc(r)}</span>`).join('')}<span class="chip">${esc(it.status)}</span>${warn}</div>
    <div class="id" title="id for config/status.yaml">${esc(it.id)}</div>
  </div>`;
}
function grouped(list) {
  const areas = [...DATA.areaOrder, ...new Set(list.map(i => i.area).filter(a => !DATA.areaOrder.includes(a)))];
  return areas.map(a => {
    const members = list.filter(i => i.area === a);
    return members.length ? `<h3>${esc(a)} (${members.length})</h3>` + members.map(card).join('') : '';
  }).join('');
}
const SECTIONS = [
  {key:'soon', title:'⏰ Deadlines in the next 14 days', flat:true, empty:'None found. Many postings only say "check page".'},
  {key:'new', title:'🆕 New this run', empty:'Nothing new today.'},
  {key:'programs', title:'📄 Watched program pages', flat:true},
  {key:'rest', title:'📋 Everything else that is open'},
  {key:'ignored', title:'🙈 Ignored by you', flat:true},
];
function render() {
  const shown = ITEMS.filter(visible);
  document.getElementById('count').textContent = `${shown.length} of ${ITEMS.length} shown`;
  document.getElementById('sections').innerHTML = SECTIONS.map(s => {
    const list = shown.filter(i => i.section === s.key);
    const all = ITEMS.filter(i => i.section === s.key).length;
    if (!all && s.key === 'ignored') return '';
    const body = list.length ? (s.flat ? list.map(card).join('') : grouped(list)) : `<p class="empty">${esc(s.empty || 'Nothing matches the filters.')}</p>`;
    return `<h2>${s.title} (${list.length}${list.length !== all ? ' of ' + all : ''})</h2>` + body;
  }).join('');
}
function renderHeader() {
  const n = s => ITEMS.filter(i => i.section === s).length;
  const fresh = ITEMS.filter(i => i.first_seen === DATA.today && i.source !== 'programs').length;
  document.getElementById('summary').textContent =
    `${DATA.today} · ${ITEMS.length} open items · ${fresh} new · ${n('soon')} deadlines within 14 days · labels by ${DATA.labeledBy}`;
  const icon = {ok:'✅', partial:'⚠️', failed:'❌'};
  document.getElementById('health').innerHTML = '<tr><th>Source</th><th>Status</th><th>Items</th><th>Checked</th><th>Time</th><th>Problems</th></tr>' +
    DATA.health.map(h => `<tr><td>${esc(h.name)}</td><td>${icon[h.status] || ''} ${esc(h.status)}</td><td>${h.items}</td><td>${h.checked}</td><td>${Math.round(h.seconds)}s</td><td>${h.errors.map(esc).join('<br>')}</td></tr>`).join('');
}
document.getElementById('q').addEventListener('input', render);
document.getElementById('reset').addEventListener('click', () => { document.getElementById('q').value = ''; buildFilters(); render(); });
renderHeader(); buildFilters(); render();
</script>
</body>
</html>
"""
