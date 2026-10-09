"""The daily run, step by step.

    python -m radar                 run everything
    python -m radar --only gupy     run only some sources (comma-separated)
    python -m radar status ID applied
    python -m radar check-config    verify every company slug and program URL
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from . import db, labels, llm, notify, report, site
from .config import ROOT, load_config
from .models import Opportunity
from .sources import (
    SourceResult, amazon, ashby, ciadetalentos, ciee, fapesp, github_lists, google, greenhouse, gupy, iel, lever, meta,
    microsoft, nextjs_sites, nvidia, programs, smartrecruiters, solides, superestagios, workday,
)

log = logging.getLogger("radar")

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "radar.db"  # working copy, rebuilt from the text files below (not committed)
REPORTS_DIR = ROOT / "reports"
SITE_DIR = ROOT / "docs"  # served by GitHub Pages

# name -> function(config, conn, today) -> SourceResult
SOURCES: dict[str, Callable[[dict[str, Any], sqlite3.Connection, str], SourceResult]] = {
    "greenhouse": lambda cfg, conn, today: greenhouse.fetch(cfg),
    "lever": lambda cfg, conn, today: lever.fetch(cfg),
    "ashby": lambda cfg, conn, today: ashby.fetch(cfg),
    "github_lists": lambda cfg, conn, today: github_lists.fetch(cfg),
    "gupy": lambda cfg, conn, today: gupy.fetch(cfg),
    "programs": lambda cfg, conn, today: programs.fetch(cfg, conn, today),
    "google": lambda cfg, conn, today: google.fetch(cfg),
    "amazon": lambda cfg, conn, today: amazon.fetch(cfg),
    "nvidia": lambda cfg, conn, today: nvidia.fetch(cfg),
    "microsoft": lambda cfg, conn, today: microsoft.fetch(cfg),
    "deshaw": lambda cfg, conn, today: nextjs_sites.fetch_deshaw(cfg),
    "drw": lambda cfg, conn, today: nextjs_sites.fetch_drw(cfg),
    "meta": lambda cfg, conn, today: meta.fetch(cfg),  # needs Playwright (headless browser)
    # --- Brazil -------------------------------------------------------------
    "ciee": lambda cfg, conn, today: ciee.fetch(cfg),
    "solides": lambda cfg, conn, today: solides.fetch(cfg),
    "superestagios": lambda cfg, conn, today: superestagios.fetch(cfg),
    "iel": lambda cfg, conn, today: iel.fetch(cfg),
    "ciadetalentos": lambda cfg, conn, today: ciadetalentos.fetch(cfg),
    "fapesp": lambda cfg, conn, today: fapesp.fetch(cfg),
    "smartrecruiters": lambda cfg, conn, today: smartrecruiters.fetch(cfg),
    "workday": lambda cfg, conn, today: workday.fetch(cfg),
}


def run_source(name: str, config: dict[str, Any], conn: sqlite3.Connection, today: str) -> tuple[list[Opportunity], report.SourceHealth]:
    """Run one source. Whatever happens inside, this never raises."""
    health = report.SourceHealth(name=name)
    started = time.monotonic()
    try:
        result = SOURCES[name](config, conn, today)
        health.items, health.checked, health.errors = len(result.items), result.checked, result.errors
        if result.errors:
            # Everything failed -> "failed"; some parts failed -> "partial".
            health.status = "failed" if not result.items else "partial"
        items = result.items
    except Exception as error:  # noqa: BLE001 - one source must never break the run
        log.exception("Source %s crashed", name)
        health.status, health.errors, items = "failed", [f"{type(error).__name__}: {error}"], []
    health.seconds = time.monotonic() - started
    log.info("%-13s %-7s %4d items (%d checked, %d problems, %.0fs)",
             name, health.status, health.items, health.checked, len(health.errors), health.seconds)
    return items, health


def dedupe(items: list[Opportunity]) -> list[Opportunity]:
    """Same URL from two sources (e.g. Greenhouse and a GitHub list) -> keep the first."""
    unique: dict[str, Opportunity] = {}
    for opp in items:
        unique.setdefault(opp.id, opp)
    return list(unique.values())


def apply_status_file(conn: sqlite3.Connection, statuses: dict[str, str]) -> None:
    """Copy the statuses from config/status.yaml into the database."""
    for opp_id, status in (statuses or {}).items():
        try:
            if not db.set_status(conn, str(opp_id), str(status)):
                log.warning("status.yaml: id %s not found", opp_id)
        except ValueError as error:
            log.warning("status.yaml: %s (%s)", error, opp_id)


def run(
    only: list[str] | None = None,
    db_path: Path = DB_PATH,
    reports_dir: Path = REPORTS_DIR,
    site_dir: Path = SITE_DIR,
    send: bool = True,
    text_dir: Path | None = None,
) -> report.ReportData:
    today = date.today().isoformat()
    config = load_config()
    text_dir = Path(text_dir or Path(db_path).parent)  # data/opportunities.jsonl, data/page_hashes.jsonl
    conn = db.open_state(db_path, text_dir)
    db.mark_previous_new_as_seen(conn, today)

    # 1. Collect from every source.
    collected: dict[str, list[Opportunity]] = {}
    health: list[report.SourceHealth] = []
    for name in SOURCES:
        if only and name not in only:
            continue
        items, source_health = run_source(name, config, conn, today)
        collected[name] = items
        health.append(source_health)
    all_items = dedupe([opp for items in collected.values() for opp in items])

    # 2. Label: keyword rules always; Claude on top for new items if a key is set.
    for opp in all_items:
        labels.apply_rules(opp)
    labeled_by = "keyword rules"
    if llm.enabled():
        known = db.existing_ids(conn)
        fresh = [opp for opp in all_items if opp.id not in known]
        done = llm.refine_labels(fresh)
        labeled_by = f"keyword rules + Claude ({done} new items)"

    # 3. Store. A source that worked completely also tells us which of its
    #    old postings disappeared (= closed). Failed/partial sources don't.
    for opp in all_items:
        db.upsert(conn, opp, today)
    for h in health:
        if h.status == "ok":
            db.mark_missing_as_closed(conn, h.name, {o.id for o in collected[h.name] if o.is_open})
    db.close_stale(conn, today)
    apply_status_file(conn, config.get("status") or {})
    conn.commit()

    # 4. Reports, website data and notifications.
    everything = db.load_all(conn)
    data = report.build(everything, health, today, labeled_by)
    report.write_reports(data, reports_dir)
    site.write_data(everything, health, today, labeled_by, site_dir)
    db.save_text(conn, text_dir)  # the committed copy of the database (see db.save_text)
    conn.close()
    if send:
        notify.notify(data)
    return data


def check_config() -> int:
    """Verify every company slug and program URL; print a table. Returns #problems."""
    from .http import get_json, get_text

    config = load_config()
    urls = {"greenhouse": greenhouse.URL, "lever": lever.URL, "ashby": ashby.URL}
    problems = 0
    for ats, url in urls.items():
        for company in config["companies"].get(ats) or []:
            try:
                data = get_json(url.format(slug=company["slug"]))
                count = len(data) if isinstance(data, list) else len(data.get("jobs", []))
                print(f"OK    {ats:10} {company['slug']:28} {count} jobs")
            except Exception as error:  # noqa: BLE001
                problems += 1
                print(f"FAIL  {ats:10} {company['slug']:28} {error}")
    for program in config["programs"]:
        try:
            text = programs.page_text(program)
            print(f"OK    program    {program['name'][:45]:45} {len(text)} chars")
        except Exception as error:  # noqa: BLE001
            problems += 1
            print(f"FAIL  program    {program['name'][:45]:45} {error}")
    return problems


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(prog="python -m radar", description="Collect student opportunities.")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "status", "check-config"])
    parser.add_argument("args", nargs="*", help="for status: <id> <new|seen|applied|ignored>")
    parser.add_argument("--only", help="comma-separated source names, e.g. gupy,programs")
    parser.add_argument("--no-notify", action="store_true", help="don't send Telegram/email")
    options = parser.parse_args(argv)

    if options.command == "status":
        if len(options.args) != 2:
            parser.error("usage: python -m radar status <id> <new|seen|applied|ignored>")
        conn = db.open_state(DB_PATH, DATA_DIR)
        found = db.set_status(conn, options.args[0], options.args[1])
        conn.commit()
        db.save_text(conn, DATA_DIR)
        print("updated" if found else "id not found")
        return 0 if found else 1
    if options.command == "check-config":
        return 1 if check_config() else 0

    only = [name.strip() for name in options.only.split(",")] if options.only else None
    if only:
        unknown = set(only) - set(SOURCES)
        if unknown:
            parser.error(f"unknown source(s): {', '.join(sorted(unknown))}; choose from {', '.join(SOURCES)}")
    data = run(only=only, send=not options.no_notify)
    print(f"\nDone: {data.total_open} open, {data.new_total} new. Website data in {SITE_DIR}/, report in {REPORTS_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
