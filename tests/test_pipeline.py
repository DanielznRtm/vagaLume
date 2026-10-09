"""Database, reports, notifications, Claude labelling and the main loop."""

import json

import pytest

from radar import db, llm, main, notify, report, site
from radar.labels import apply_rules
from radar.models import Opportunity
from radar.sources import SourceResult


def make(title="Software Engineer Intern", url="https://example.com/1", **kwargs) -> Opportunity:
    return apply_rules(Opportunity(title=title, org="Org", source=kwargs.pop("source", "greenhouse"), url=url, **kwargs))


def test_upsert_dedupes_and_keeps_status():
    conn = db.connect(":memory:")
    assert db.upsert(conn, make(), "2026-10-01") is True
    db.set_status(conn, make().id, "applied")
    assert db.upsert(conn, make(title="Software Engineer Intern (renamed)"), "2026-10-02") is False
    [row] = db.load_all(conn)
    assert row.status == "applied"  # your status is never overwritten
    assert row.first_seen == "2026-10-01"
    assert row.title.endswith("(renamed)")


def test_new_becomes_seen_next_day_and_missing_items_close():
    conn = db.connect(":memory:")
    db.upsert(conn, make(url="https://e.com/a"), "2026-10-01")
    db.upsert(conn, make(url="https://e.com/b"), "2026-10-01")
    db.mark_previous_new_as_seen(conn, "2026-10-02")
    db.mark_missing_as_closed(conn, "greenhouse", {make(url="https://e.com/a").id})
    rows = {r.url: r for r in db.load_all(conn)}
    assert rows["https://e.com/a"].status == "seen"
    assert rows["https://e.com/a"].is_open and not rows["https://e.com/b"].is_open


def test_set_status_rejects_unknown_values():
    conn = db.connect(":memory:")
    with pytest.raises(ValueError):
        db.set_status(conn, "x", "maybe")


def test_report_sections_and_website_data(tmp_path):
    conn = db.connect(":memory:")
    db.upsert(conn, make(title="Old Intern", url="https://e.com/old"), "2026-09-01")
    fresh_opp = make(title="Fresh Intern", url="https://e.com/new?utm_source=x")
    fresh_opp.skills = ["Python", "ROS"]
    db.upsert(conn, fresh_opp, "2026-10-05")
    db.upsert(conn, make(title="Soon Intern", url="https://e.com/soon", deadline="2026-10-10"), "2026-09-01")
    db.upsert(conn, make(title="Closed Intern", url="https://e.com/closed", is_open=False), "2026-09-01")
    health = [report.SourceHealth(name="greenhouse", items=3, checked=1)]
    everything = db.load_all(conn)
    data = report.build(everything, health, "2026-10-05", "keyword rules")
    assert [o.title for o in data.soon] == ["Soon Intern"]
    assert [o.title for o in data.new] == ["Fresh Intern"]
    assert [o.title for o in data.rest] == ["Old Intern"]

    report.write_reports(data, tmp_path)
    markdown = (tmp_path / "latest.md").read_text()
    assert markdown.index("Deadlines in the next") < markdown.index("New this run") < markdown.index("Everything else")

    path = site.write_data(everything, health, "2026-10-05", "keyword rules", tmp_path)
    payload = json.loads(path.read_text())
    assert payload["updated"] == "2026-10-05"
    assert sorted(i["title"] for i in payload["items"]) == ["Fresh Intern", "Old Intern", "Soon Intern"]  # open only
    fresh = next(i for i in payload["items"] if i["title"] == "Fresh Intern")
    assert fresh["url"] == "https://e.com/new"  # tracking parameters removed
    assert fresh["deadline"] == ""  # "check page" becomes empty
    assert fresh["skills"] == ["Python", "ROS"]  # stored and read back for the résumé match
    assert "PyTorch" in payload["skillNames"]  # the site puts these names in its résumé prompt
    assert payload["sources"][0]["name"] == "greenhouse"
    badge = json.loads((tmp_path / "stats.json").read_text())  # read by the README badges
    assert badge == {"updated": "2026-10-05", "open": "3", "new": "1", "with_pay": "0", "sources": "1/1 healthy", "sources_ok": True}


def test_notifications_are_skipped_without_env(monkeypatch):
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "EMAIL_TO"):
        monkeypatch.delenv(name, raising=False)
    assert notify.send_telegram("hi") is False
    assert notify.send_email("hi", "subject") is False


def test_claude_labels_merge(monkeypatch):
    opp = make(title="Research Intern", description="Remote. Deadline not stated.")
    answer = {
        "area": "ML", "season": "Dec–Feb", "regions": ["Brazil", "remote"],
        "warnings": ["grad-year limit?"], "deadline": "2026-11-30", "student_role": "unsure",
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_ask_claude", lambda o, key: answer)
    assert llm.refine_labels([opp]) == 1
    assert (opp.area, opp.season, opp.regions, opp.deadline) == ("ML", "Dec–Feb", ["Brazil", "remote"], "2026-11-30")
    assert "grad-year limit?" in opp.warnings and "unsure if student role" in opp.warnings
    assert opp.labeled_by == "claude"


def test_claude_errors_keep_keyword_labels(monkeypatch):
    opp = make(title="Research Intern")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def broken(o, key):
        raise RuntimeError("API down")

    monkeypatch.setattr(llm, "_ask_claude", broken)
    assert llm.refine_labels([opp]) == 0
    assert opp.labeled_by == "rules" and opp.area == "research"


def test_one_failing_source_does_not_break_the_run(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def broken(config, conn, today):
        raise ConnectionError("site is down")

    def working(config, conn, today):
        return SourceResult(items=[make(title="Data Intern", url="https://e.com/w")], checked=1)

    def partial(config, conn, today):
        return SourceResult(items=[make(title="ML Intern", url="https://e.com/p")], errors=["one board 404"], checked=2)

    monkeypatch.setattr(main, "SOURCES", {"broken": broken, "working": working, "partial": partial})
    monkeypatch.setattr(main, "load_config", lambda: {"status": {}})
    data = main.run(db_path=tmp_path / "radar.db", reports_dir=tmp_path, site_dir=tmp_path, send=False)
    statuses = {h.name: h.status for h in data.health}
    assert statuses == {"broken": "failed", "working": "ok", "partial": "partial"}
    assert data.total_open == 2
    assert "site is down" in (tmp_path / "latest.md").read_text()
    assert len(json.loads((tmp_path / "data.json").read_text())["items"]) == 2


def test_report_stays_short_with_many_roles():
    conn = db.connect(":memory:")
    for n in range(400):
        db.upsert(conn, make(title=f"Intern {n}", url=f"https://e.com/{n}"), "2026-09-01")
    for n in range(200):
        db.upsert(conn, make(title=f"New Intern {n}", url=f"https://e.com/new{n}"), "2026-10-05")
    data = report.build(db.load_all(conn), [], "2026-10-05", "keyword rules")
    markdown = report.render_markdown(data)
    assert "… and 140 more on the [website]" in markdown  # 200 new roles in one area, 60 listed
    assert "Intern 399" not in markdown  # "everything else" is a table of counts
    assert "| other | 400 | 400 |" in markdown  # area, region (unknown) and total


def test_database_round_trips_through_text(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    db.upsert(conn, make(title="Estágio em Dados", url="https://e.com/b", pay="R$2,000/mo"), "2026-10-01")
    db.upsert(conn, make(title="Research Intern", url="https://e.com/a"), "2026-10-02")
    db.set_status(conn, make(url="https://e.com/a").id, "applied")
    db.page_hash_changed(conn, "https://p.org/", "abc", "2026-10-02")
    conn.commit()
    db.save_text(conn, tmp_path)
    lines = (tmp_path / "opportunities.jsonl").read_text().splitlines()
    assert len(lines) == 2 and lines == sorted(lines, key=lambda line: json.loads(line)["id"])  # one sorted line per role

    rebuilt = db.open_state(tmp_path / "b.db", tmp_path)
    before = sorted(map(tuple, conn.execute("SELECT * FROM opportunities").fetchall()))
    after = sorted(map(tuple, rebuilt.execute("SELECT * FROM opportunities").fetchall()))
    assert before == after  # nothing lost: statuses, dates, pay, labels
    assert rebuilt.execute("SELECT hash FROM page_hashes").fetchone()[0] == "abc"
    db.save_text(rebuilt, tmp_path / "again")
    assert (tmp_path / "again" / "opportunities.jsonl").read_text() == (tmp_path / "opportunities.jsonl").read_text()


def test_first_run_after_the_switch_reads_the_old_database(tmp_path):
    old = db.connect(tmp_path / "radar.db")
    db.upsert(old, make(), "2026-10-01")
    old.commit()
    old.close()
    conn = db.open_state(tmp_path / "radar.db", tmp_path)  # no .jsonl files yet
    assert len(db.load_all(conn)) == 1


def test_last_seen_is_refreshed_weekly():
    conn = db.connect(":memory:")
    db.upsert(conn, make(), "2026-10-01")
    last_seen = lambda: conn.execute("SELECT last_seen FROM opportunities").fetchone()[0]
    db.upsert(conn, make(), "2026-10-05")
    assert last_seen() == "2026-10-01"  # seen again 4 days later: unchanged
    db.upsert(conn, make(), "2026-10-08")
    assert last_seen() == "2026-10-08"  # 7 days later: refreshed
    db.close_stale(conn, "2026-11-06")  # 29 days after the refresh: still open
    assert db.load_all(conn)[0].is_open
