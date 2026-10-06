"""Scraped sites without a public API: Meta, Microsoft, D. E. Shaw, DRW."""

import pytest
import requests
from conftest import fixture_json, fixture_text

from radar import http
from radar.browser import RenderedPage
from radar.labels import apply_rules
from radar.sources import meta, microsoft, nextjs_sites, programs


def test_meta_graphql_response():
    items = meta.parse(fixture_json("meta_graphql.json"))
    assert len(items) >= 10
    first = items[0]
    assert first.title == "Electrical Engineering Intern"
    assert first.url == "https://www.metacareers.com/jobs/1105729655266553/"
    assert first.location == "Sunnyvale, CA / New York, NY"
    apply_rules(first)
    assert first.area == "hardware" and first.regions == ["US/Canada"]


def test_meta_only_keeps_the_job_list_request():
    assert meta.is_job_list("https://www.metacareers.com/graphql", "fb_api_req_friendly_name=CareersJobSearchResultsV2DataQuery")
    assert not meta.is_job_list("https://www.metacareers.com/graphql", "fb_api_req_friendly_name=CareersJobSearchFiltersV3Query")


def test_microsoft_search_page():
    items, total = microsoft.parse(fixture_json("microsoft.json"))
    assert total == 102
    assert len(items) == 4
    first = items[0]
    assert first.url == "https://apply.careers.microsoft.com/careers/job/1970393556922922"
    assert first.location == "Redmond, Washington, United States"
    assert first.posted_date.startswith("2026-")
    assert not first.title.endswith(",")


def test_deshaw_next_data():
    items = nextjs_sites.parse_deshaw(fixture_text("deshaw_internships.html"))
    titles = [o.title for o in items]
    assert len(titles) == 3  # the 3 internships; "Receptionist" etc. are regular jobs
    first = items[0]
    assert first.location == "New York"
    assert first.url.startswith("https://www.deshaw.com/careers/")
    assert first.url == first.url.lower()
    apply_rules(first)
    assert first.deadline == "2026-12-02"  # "Applications are open until ... December 2, 2026"
    assert first.season == "May–Aug"


def test_drw_campus_category():
    items = nextjs_sites.parse_drw(fixture_text("drw_listings.html"))
    assert [o.title for o in items] == ["AI/ML Research Intern", "Floor Trader"]  # both in "Campus"
    assert items[0].url == "https://www.drw.com/work-at-drw/listings/aiml-research-intern-3466679"
    assert items[0].location == "Montréal, Canada"


def test_program_pages_can_be_rendered(monkeypatch):
    monkeypatch.setattr(programs, "render", lambda url: RenderedPage(text="Rendered text"))
    assert programs.page_text({"url": "https://x", "render": True}) == "Rendered text"


class FakeResponse:
    def __init__(self, status: int):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_http_waits_and_retries_after_429(monkeypatch):
    answers = [FakeResponse(429), FakeResponse(200)]
    pauses = []
    monkeypatch.setattr(http._session, "request", lambda *a, **k: answers.pop(0))
    monkeypatch.setattr(http.time, "sleep", pauses.append)
    assert http._request("GET", "https://example.com").status_code == 200
    assert http.RATE_LIMIT_WAITS[0] in pauses  # it slowed down before retrying


def test_http_gives_up_on_404(monkeypatch):
    monkeypatch.setattr(http._session, "request", lambda *a, **k: FakeResponse(404))
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(requests.HTTPError):
        http._request("GET", "https://example.com")
