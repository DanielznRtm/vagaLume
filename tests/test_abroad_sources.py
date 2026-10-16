"""Sources for roles abroad: SuccessFactors feeds (SAP, Volvo Group, Volvo Cars).
Every test reads a saved sample response from tests/fixtures/."""

from conftest import fixture_text

from radar.labels import apply_rules
from radar.sources import successfactors

SITE = {"host": "careers.sap.com", "name": "SAP"}


def test_successfactors_reads_every_place_shape():
    items = successfactors.parse(fixture_text("successfactors_feed.xml"), SITE)
    places = {o.title: o.location for o in items}
    assert places["SAP iXp Intern (w/m/d) - Industrie Marketing"] == "Walldorf, Germany"
    # A region with its own parentheses, a postcode with a space, a region name, a US state.
    assert places["Sales Account Executive - SAP Academy for Customer Success - PHILIPPINES (Hybrid)"] == "Taguig City, Philippines"
    assert places["Customer Success Manager - SAP Next Gen Academy for Customer Success - UK (Hybrid)"] == "Middlesex, United Kingdom"
    assert places["All programs - Academy for Customer Success - JAPAN (Hybrid)"] == "Tokyo, Japan"
    assert places["SAP iXp Intern - Site Speed Performance [Newtown Square, PA]"] == "Newtown Square, PA, United States"


def test_successfactors_keeps_students_only_and_cleans_links():
    items = successfactors.parse(fixture_text("successfactors_feed.xml"), SITE)
    titles = [o.title for o in items]
    assert not any("Area Product Owner" in t or "Senior Launch Engineer" in t for t in titles)  # staff jobs
    assert not any(t.startswith("Ausbildung") for t in titles)  # vocational training
    assert all("?" not in o.url and "/job/" in o.url for o in items)
    assert items[0].url == "https://careers.sap.com/job/Walldorf-SAP-iXp-Intern-%28wmd%29-Industrie-Marketing-69190/1448527333/"
    assert items[0].posted_date[:4] == "2026"


def test_successfactors_sweden_is_not_sergipe():
    items = successfactors.parse(fixture_text("successfactors_feed.xml"), SITE)
    thesis = next(o for o in items if o.title.startswith("Thesis: Architecture"))
    assert thesis.location == "Göteborg, Sweden"
    apply_rules(thesis)
    assert thesis.regions == ["Europe"]
    # "Examensarbete" (a Swedish thesis) is kept and marked as a student role.
    exjobb = next(o for o in items if o.title.startswith("Examensarbete"))
    assert exjobb.hints == ["student"] and exjobb.location == "Olofstrom, Sweden"


def test_successfactors_feed_url_asks_for_every_row():
    url = successfactors.feed_url({"host": "jobs.volvogroup.com"})
    assert url.startswith("https://jobs.volvogroup.com/services/rss/job/?locale=en_US&keywords=(intern%20OR%20")
    assert url.endswith("&rows=1000")


def test_successfactors_split_place_leaves_other_parentheses():
    assert successfactors.split_place("Working Student (f/m/d)") == ("Working Student (f/m/d)", "")
    assert successfactors.split_place("Intern (Hybrid)") == ("Intern (Hybrid)", "")
