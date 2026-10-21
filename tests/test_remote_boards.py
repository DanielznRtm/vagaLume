"""Remote job boards (radar/sources/remote_boards.py). Every test reads a saved, trimmed real
response from tests/fixtures/remote_*. The boards had no student role open to Brazil on some
feeds on 2026-10-21 (Remotive, Jobicy, Working Nomads, We Work Remotely), so those tests add one
made-up job, built in the test from a real job of the fixture."""

import copy

import pytest
from conftest import fixture_json, fixture_text

from radar.labels import apply_rules
from radar.sources import remote_boards as rb


# --- open_to_brazil -------------------------------------------------------------
@pytest.mark.parametrize("restriction, expected", [
    ("", "Worldwide"),
    ("Worldwide", "Worldwide"),
    ("Anywhere in the World", "Anywhere in the World"),
    ("Brazil", "Brazil"),
    ("USA, Brazil, Mexico", "USA, Brazil, Mexico"),
    ("LATAM", "LATAM"),
    ("Europe, LATAM, APAC, the U.S., Canada", "Europe, LATAM, APAC, the U.S., Canada"),
    ("Americas", "Americas"),
    ("USA", ""),
    ("France,  Germany", ""),
    ("Mexico", ""),  # one other Latin American country only: not open to Brazil
])
def test_open_to_brazil(restriction, expected):
    assert rb.open_to_brazil(restriction) == expected


# --- Himalayas ------------------------------------------------------------------
def test_himalayas_keeps_students_open_to_brazil():
    items = rb.parse_himalayas(fixture_json("remote_himalayas.json"))
    titles = [o.title for o in items]
    assert len(items) == 7
    assert "AI Research Lab Co-Founder / CMO (100 % remote) (m/f/d)" not in titles  # filed as "Intern", seniority Executive
    assert not any("Rail Public Projects" in t or "UCD Sales" in t for t in titles)  # United States only
    first = items[0]
    assert first.title == "Agribusiness Intern (Early Careers)" and first.org == "S&P Global"
    assert first.source == "himalayas" and first.remote is True
    assert first.location == "Brazil (remote)"
    assert first.url.startswith("https://himalayas.app/companies/s-p-global/jobs/")  # applicationLink, unchanged
    assert first.posted_date == "2026-10-18" and first.deadline == "2026-12-17"  # expiryDate
    assert first.description and "<" not in first.description
    worldwide = next(o for o in items if o.title == "Growth Intern")
    assert worldwide.location == "Worldwide (remote)"
    inatel = next(o for o in items if "Inatel" in o.title)
    assert inatel.hints == ["unsure-student"]  # "program" title, but the board says Intern
    apply_rules(first)
    assert "Brazil" in first.regions and "remote" in first.regions


def test_himalayas_time_zones_and_pay():
    sample = fixture_json("remote_himalayas.json")
    job = copy.deepcopy(next(j for j in sample["jobs"] if j["title"] == "Growth Intern"))
    europe_hours = dict(job, guid="https://himalayas.app/companies/x/jobs/a", timezoneRestrictions=[0, 1, 2])
    paid = dict(job, guid="https://himalayas.app/companies/x/jobs/b", applicationLink="https://himalayas.app/companies/x/jobs/b",
                minSalary=1000, maxSalary=1000, currency="USD", salaryPeriod="monthly")
    items = rb.parse_himalayas({"jobs": [europe_hours, paid]})
    assert [o.url for o in items] == ["https://himalayas.app/companies/x/jobs/b"]  # UTC+0..2 only: not for Brazil
    assert items[0].pay == "$1,000/mo" and items[0].pay_from == "field"


def test_himalayas_bad_answer_raises():
    with pytest.raises(ValueError):
        rb.parse_himalayas({"error": "rate limited"})


# --- Remotive -------------------------------------------------------------------
def test_remotive_drops_regular_jobs_and_keeps_internships():
    sample = fixture_json("remote_remotive.json")
    assert rb.parse_remotive(sample) == []  # today's feed: no internships
    intern = dict(sample["jobs"][0], title="Data Engineering Intern", job_type="internship",
                  candidate_required_location="LATAM", url="https://remotive.com/remote-jobs/data/data-engineering-intern-1")
    us_only = dict(intern, candidate_required_location="USA", url="https://remotive.com/remote-jobs/data/x-2")
    items = rb.parse_remotive({"jobs": [intern, us_only]})
    assert len(items) == 1
    assert items[0].location == "LATAM (remote)" and items[0].source == "remotive"
    assert items[0].url.startswith("https://remotive.com/")  # their terms: link back to Remotive


# --- Jobicy ---------------------------------------------------------------------
def test_jobicy_needs_student_title_and_latam_geo():
    sample = fixture_json("remote_jobicy.json")
    assert rb.parse_jobicy(sample) == []  # interns in France/Germany and USA; LATAM roles are senior
    latam = next(j for j in sample["jobs"] if j["jobGeo"] == "LATAM")
    intern = dict(latam, jobTitle="Software Engineering Intern", jobType=["Internship"], url="https://jobicy.com/jobs/1-intern",
                  salaryMin=500, salaryMax=800, salaryCurrency="USD", salaryPeriod="monthly")
    items = rb.parse_jobicy({"jobs": [intern]})
    assert len(items) == 1
    assert items[0].location == "LATAM (remote)" and items[0].pay == "$500–800/mo"
    assert items[0].url == "https://jobicy.com/jobs/1-intern"  # keep the Jobicy URL (their terms)


# --- Remote OK ------------------------------------------------------------------
def test_remoteok_skips_legal_notice_and_keeps_student():
    items = rb.parse_remoteok(fixture_json("remote_remoteok.json"))
    assert [o.title for o in items] == ["Marketing Student Assistant"]
    assert items[0].location == "Worldwide (remote)"  # no location given
    assert items[0].url.startswith("https://remoteOK.com/remote-jobs/")


# --- Working Nomads -------------------------------------------------------------
def test_workingnomads():
    sample = fixture_json("remote_workingnomads.json")
    assert rb.parse_workingnomads(sample) == []
    intern = dict(sample[0], title="Marketing Intern", location="Europe, LATAM, APAC", url="https://www.workingnomads.com/job/go/1/")
    items = rb.parse_workingnomads([intern])
    assert len(items) == 1 and items[0].location == "Europe, LATAM, APAC (remote)"


# --- We Work Remotely ------------------------------------------------------------
def test_weworkremotely_feed():
    feed = fixture_text("remote_weworkremotely.xml")
    assert rb.parse_weworkremotely(feed) == []  # three senior roles
    first_item = feed[feed.find("<item>"): feed.find("</item>") + len("</item>")]
    title_start = first_item.find("<title>") + len("<title>")
    title_end = first_item.find("</title>")
    intern = first_item[:title_start] + "Acme: Product Design Intern" + first_item[title_end:]
    items = rb.parse_weworkremotely(feed.replace(first_item, intern))
    assert len(items) == 1
    assert items[0].title == "Product Design Intern" and items[0].org == "Acme"
    assert items[0].location.endswith("(remote)") and items[0].posted_date.startswith("2026-")


# --- Arbeitnow ------------------------------------------------------------------
def test_arbeitnow_remote_werkstudent_in_germany():
    items = rb.parse_arbeitnow(fixture_json("remote_arbeitnow.json"))
    assert len(items) == 2  # the on-site and the non-student remote roles are left out
    assert all(o.title.startswith("Werkstudent") for o in items)
    assert items[0].location == "Berlin, Germany (remote)"


# --- fetch ----------------------------------------------------------------------
def test_fetch_reads_configured_boards_and_dedupes(monkeypatch):
    calls = []
    remoteok = fixture_json("remote_remoteok.json")

    def fake_get_json(url, **kwargs):
        calls.append(url)
        if "remoteok" in url:
            return remoteok
        raise AssertionError(url)

    monkeypatch.setattr(rb, "get_json", fake_get_json)
    result = rb.fetch({"search": {"remote_boards": ["remoteok", {"name": "RemoteOK"}, "nosuchboard"]}})
    assert calls == [rb.REMOTEOK_URL]  # listed twice, read once
    assert len(result.items) == 1 and result.checked == 1
    assert result.errors and "nosuchboard" in result.errors[0]


def test_fetch_one_board_failing_does_not_stop_the_others(monkeypatch):
    def fake_get_json(url, **kwargs):
        if "himalayas" in url:
            raise RuntimeError("429 Too Many Requests")
        return fixture_json("remote_remoteok.json")

    monkeypatch.setattr(rb, "get_json", fake_get_json)
    result = rb.fetch({}, ["himalayas", "remoteok"])
    assert [o.source for o in result.items] == ["remoteok"]
    assert result.errors == ["himalayas: 429 Too Many Requests"]


def test_one_board_entry_respects_the_config_section(monkeypatch):
    monkeypatch.setattr(rb, "get_json", lambda url, **kwargs: fixture_json("remote_remoteok.json"))
    assert rb.fetch({"search": {"remote_boards": ["himalayas"]}}, ["remoteok"]).checked == 0  # switched off
    assert len(rb.fetch({}, ["remoteok"]).items) == 1  # no section: the defaults, remoteok among them


def test_default_boards():
    assert rb.configured_boards({}) == rb.DEFAULT_BOARDS
    assert "weworkremotely" not in rb.DEFAULT_BOARDS and "arbeitnow" not in rb.DEFAULT_BOARDS
