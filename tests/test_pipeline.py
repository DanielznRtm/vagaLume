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

    path = site.write_data(everything, health, "2026-10-05", "keyword rules", tmp_path)
    payload = json.loads(path.read_text())
    assert payload["updated"] == "2026-10-05"
    assert sorted(i["title"] for i in payload["items"]) == ["Fresh Intern", "Old Intern", "Soon Intern"]  # open only
    fresh = next(i for i in payload["items"] if i["title"] == "Fresh Intern")
    assert fresh["url"] == "https://e.com/new"  # tracking parameters removed
    assert "deadline" not in fresh  # "check page" becomes empty, and empty values are left out (the page fills them in)
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
    data = main.run(db_path=tmp_path / "radar.db", site_dir=tmp_path, send=False)
    statuses = {h.name: h.status for h in data.health}
    assert statuses == {"broken": "failed", "working": "ok", "partial": "partial"}
    assert data.total_open == 2
    assert "site is down" in next(h for h in data.health if h.name == "broken").errors[0]
    assert len(json.loads((tmp_path / "data.json").read_text())["items"]) == 2


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


def test_site_leaves_out_past_terms_and_repeats(tmp_path):
    """Stress test: "Winter 2026" roles in October and the same role listed twice."""
    from radar.site import shown_items

    conn = db.connect(tmp_path / "radar.db")
    for title, url in [("Software Engineer Intern (Winter 2026)", "https://e.com/1"), ("Enfermagem - Auditoria", "https://e.com/2"),
                       ("Enfermagem - Auditoria", "https://e.com/3"), ("Software Engineer Intern (Winter 2027)", "https://e.com/4")]:
        db.upsert(conn, apply_rules(Opportunity(title=title, org="Santa Casa", source="gupy", url=url, location="Belo Horizonte, MG")), "2026-10-16")
    program = apply_rules(Opportunity(title="Journeys into Theoretical Physics", org="ICTP", source="programs", url="https://p", deadline="2026-05-01"))
    db.upsert(conn, program, "2026-10-16")
    items = shown_items(db.load_all(conn), "2026-10-16")
    titles = sorted(i["title"] for i in items)
    assert titles == ["Enfermagem - Auditoria", "Journeys into Theoretical Physics", "Software Engineer Intern (Winter 2027)"]
    assert next(i for i in items if i["source"] == "programs")["deadline"] == ""  # last year's edition


def test_the_site_shows_one_row_per_job_and_merges_places():
    from radar import db
    from radar.labels import apply_rules
    from radar.models import Opportunity
    from radar.site import shown_items

    conn = db.connect(":memory:")
    roles = [
        # One Boeing job: a staff-only site, the public site via a GitHub list, and Boeing's Workday.
        Opportunity(title="Data Science Intern", org="Boeing", source="github_lists", location="Richmond, BC, Canada",
                    url="https://boeing.wd1.myworkdayjobs.com/external_subsidiary/job/CAN/Data-Science-Intern_JR1?utm_source=Simplify"),
        Opportunity(title="Data Science Intern", org="Boeing", source="github_lists", location="Richmond, BC, Canada",
                    url="https://boeing.wd1.myworkdayjobs.com/EXTERNAL_CAREERS/job/CAN/Data-Science-Intern_JR1-1"),
        Opportunity(title="Data Science Intern", org="Boeing", source="workday", location="2 Locations, Canada",
                    url="https://boeing.wd1.myworkdayjobs.com/en-US/External_Careers/job/CAN/Data-Science-Intern_JR1-1"),
        # The same estágio in three DF regions: one row, every place, a link for each.
        *[Opportunity(title="Estágio em Agronomia", org="SEEC/DF", source="superestagios", location=f"{place}, DF, Brazil",
                      url=f"https://www.superestagios.com.br/index/vagasEstagioDestaque.php?i={n}")
          for n, place in enumerate(["Ceilândia", "Guará", "Gama"])],
        # Two confidential companies are not one.
        Opportunity(title="Estágio em Direito", org="Empresa confidencial", source="superestagios", location="Recife, PE, Brazil", url="https://s/x?i=1"),
        Opportunity(title="Estágio em Direito", org="Empresa confidencial", source="superestagios", location="Natal, RN, Brazil", url="https://s/x?i=2"),
    ]
    for opp in roles:
        db.upsert(conn, apply_rules(opp), "2026-10-19")
    items = shown_items(db.load_all(conn), "2026-10-19")
    boeing = [i for i in items if i["org"] == "Boeing"]
    assert len(boeing) == 1 and "subsidiary" not in boeing[0]["url"]
    df = [i for i in items if i["org"] == "SEEC/DF"]
    assert len(df) == 1 and df[0]["location"].count(" / ") == 2 and len(df[0]["alts"]) == 2 and len(df[0]["also"]) == 2
    assert len([i for i in items if i["org"] == "Empresa confidencial"]) == 2


def test_a_partial_source_still_closes_the_roles_of_the_boards_that_answered():
    from radar import db
    from radar.labels import apply_rules
    from radar.models import Opportunity

    conn = db.connect(":memory:")
    a = Opportunity(title="Intern A", org="Acme", source="workday", url="https://acme/1")
    b = Opportunity(title="Intern B", org="Beta", source="workday", url="https://beta/1")
    for opp in (a, b):
        db.upsert(conn, apply_rules(opp), "2026-10-20")
    # Next day Beta's board fails (429) and Acme's no longer lists its role.
    db.mark_missing_as_closed(conn, "workday", set(), keep_orgs={"Beta"})
    open_orgs = {o.org for o in db.load_all(conn) if o.is_open}
    assert open_orgs == {"Beta"}
