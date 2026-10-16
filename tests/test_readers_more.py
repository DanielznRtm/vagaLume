"""More job-page readers (radar/readers_more.py), on trimmed copies of real answers."""

import json
from pathlib import Path

import pytest

from radar import details, readers_more
from radar.labels import apply_rules
from radar.models import Opportunity
from radar.pay import find_pay

FIXTURES = Path(__file__).parent / "fixtures"

# (link as the GitHub lists give it, fixture, reader, address asked, pay field, pay in the text)
CASES = [
    ("https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26013190?utm_source=Simplify&ref=Simplify",
     "readers_oracle_hcm.json", "_oracle_hcm",
     "https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
     "?expand=all&onlyData=true&finder=ById;Id=%2226013190%22,siteNumber=CX_1",
     "$24.05–63/hr", "$24.05–63/hr"),
    ("https://eaton.eightfold.ai/careers/job/687239256112?utm_source=Simplify&ref=Simplify",
     "readers_eightfold.json", "_eightfold", "https://eaton.eightfold.ai/api/apply/v2/jobs/687239256112",
     "", "$22.15–37.50/hr"),
    ("https://careers.amd.com/jobs/91177?icims=1&utm_source=Simplify&ref=Simplify",
     "readers_jibe.json", "_jibe", "https://careers.amd.com/api/jobs?keywords=91177&limit=10",
     "$83K–125K/yr", "$83K–125K/yr"),
    ("https://ats.rippling.com/momentumcareers/jobs/dd4281b8-fa2a-4833-8370-b1859933b612?utm_source=Simplify&ref=Simplify",
     "readers_rippling.json", "_rippling",
     "https://api.rippling.com/platform/api/ats/v1/board/momentumcareers/jobs/dd4281b8-fa2a-4833-8370-b1859933b612",
     "$110K–155K/yr", ""),
    ("https://amazon.jobs/en/jobs/10578090/hardware-development-engineer-intern-summer-2027?utm_source=Simplify&ref=Simplify",
     "readers_amazon.json", "_amazon", "https://www.amazon.jobs/en/search.json?base_query=10578090&result_limit=10",
     "", "$107K–119K/yr"),
    ("https://careersus-shure.icims.com/jobs/4968/job?mobile=true&needsRedirect=false&utm_source=Simplify&ref=Simplify",
     "readers_icims.html", "_icims", "https://careersus-shure.icims.com/jobs/4968/job?in_iframe=1",
     "", "$23–43/hr"),
    ("https://careers.qorvo.com/job/Richardson-Research-Engineering-Intern-TX-75080/1424726900/?ats=successfactors&utm_source=Simplify&ref=Simplify",
     "readers_successfactors.html", "_successfactors",
     "https://careers.qorvo.com/job/Richardson-Research-Engineering-Intern-TX-75080/1424726900/",
     "", "$31–42/hr"),
    ("https://lifeattiktok.com/search/7668584161852229893?utm_source=github-vansh-ouckah",
     "readers_tiktok.html", "_tiktok", "https://lifeattiktok.com/search/7668584161852229893",
     "", "$45–60/hr"),
    ("https://jobs.ea.com/en_US/careers/JobDetail/Software-Engineer-Intern/216227",
     "readers_avature.html", "_avature", "https://jobs.ea.com/en_US/careers/JobDetail/Software-Engineer-Intern/216227",
     "", "CA$65K–70K/yr"),
    ("https://recruiting.paylocity.com/Recruiting/Jobs/Details/4501298?utm_source=Simplify&ref=Simplify",
     "readers_paylocity.html", "_jsonld_page", "https://recruiting.paylocity.com/Recruiting/Jobs/Details/4501298",
     "$17.50–27/hr", ""),
    ("https://www.metacareers.com/jobs/929757023499411?utm_source=Simplify&ref=Simplify",
     "readers_meta.html", "_meta", "https://www.metacareers.com/jobs/929757023499411/",
     "", ""),
]


def serve(monkeypatch, body: str) -> list[str]:
    """Answer every request with `body` (JSON or HTML) and note the addresses asked."""
    asked: list[str] = []

    def fake_get_json(url, **kwargs):
        asked.append(url)
        return json.loads(body)

    def fake_get_text(url, **kwargs):
        asked.append(url)
        return body

    monkeypatch.setattr(readers_more, "get_json", fake_get_json)
    monkeypatch.setattr(readers_more, "get_text", fake_get_text)
    return asked


def reader_for(url: str):
    return next((read for pattern, read in readers_more.MORE_READERS if pattern.search(url)), None)


@pytest.mark.parametrize("url, fixture, name, address, field_pay, text_pay", CASES, ids=[c[2] for c in CASES])
def test_each_board_is_read_from_its_api_or_page(monkeypatch, url, fixture, name, address, field_pay, text_pay):
    asked = serve(monkeypatch, (FIXTURES / fixture).read_text(encoding="utf-8"))
    read = reader_for(url)
    assert read is not None and read.__name__ == name
    text, pay = read(url)
    assert asked == [address]
    assert len(text) > 500 and "<" not in text[:200]
    assert pay == field_pay
    assert find_pay(text) == text_pay


def test_the_page_text_leaves_out_the_site_around_the_posting(monkeypatch):
    serve(monkeypatch, (FIXTURES / "readers_tiktok.html").read_text(encoding="utf-8"))
    text, _ = readers_more._tiktok("https://lifeattiktok.com/search/7668584161852229893")
    assert text.startswith("Responsibilities") and "Newsroom" not in text and "Apply to this job" not in text
    serve(monkeypatch, (FIXTURES / "readers_successfactors.html").read_text(encoding="utf-8"))
    text, _ = readers_more._successfactors("https://careers.qorvo.com/job/x/1424726900/?ats=successfactors")
    assert "Similar jobs" not in text and "Privacy" not in text and "Careers Home" not in text


def test_workable_job_api(monkeypatch):
    job = {"title": "Intern", "description": "<p>Build robots.</p>", "requirements": "<ul><li>Python</li></ul>",
           "benefits": "<p>Pay: $25 - $30 per hour</p>"}
    asked = serve(monkeypatch, json.dumps(job))
    url = "https://apply.workable.com/zaber/j/EAB5877DC3/apply?utm_source=Simplify&ref=Simplify"
    text, pay = reader_for(url)(url)
    assert asked == ["https://apply.workable.com/api/v2/accounts/zaber/jobs/EAB5877DC3"]
    assert "Build robots." in text and "Python" in text and pay == "" and find_pay(text) == "$25–30/hr"


def test_a_closed_role_gives_nothing(monkeypatch):
    serve(monkeypatch, json.dumps({"items": [], "count": 0}))
    url = "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011796"
    assert readers_more._oracle_hcm(url) == ("", "")
    serve(monkeypatch, json.dumps({"jobs": [{"data": {"req_id": "999", "description": "Another job"}}]}))
    assert readers_more._jibe("https://careers.garmin.com/jobs/19098?icims=1") == ("", "")
    serve(monkeypatch, "<html><body>Search jobs</body></html>")
    assert readers_more._tiktok("https://lifeattiktok.com/search/1") == ("", "")


def test_links_go_to_the_right_reader():
    expected = {
        "https://fa-etbx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/nfcu/job/32455": "_oracle_hcm",
        "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210796061": "_oracle_hcm",
        "https://qualcomm.eightfold.ai/careers/job/446721064018?utm_source=Simplify": "_eightfold",
        "https://jobs.infineon.com/careers/job/563808971855358?utm_source=indeed&domain=infineon.com": "_eightfold",
        "https://careers-gdms.icims.com/jobs/74785/job?mobile=true&needsRedirect=false": "_icims",
        "https://jobs.keysight.com/jobs/54138?icims=1&utm_source=Simplify&ref=Simplify": "_jibe",
        "https://discounttire.jibeapply.com/jobs/19242": "_jibe",
        "https://jobs.l3harris.com/job/Rochester-Software-Engineer-Intern-NY-14623/1428440700/?ats=successfactors": "_successfactors",
        "https://jobs.bytedance.com/en/position/7665108869591140613/detail?utm_source=Simplify": "_tiktok",
        "https://joinbytedance.com/search/7668464504736876853": "_tiktok",
        "https://twosigma.avature.net/careers/JobDetail/14020": "_avature",
        "https://www.amazon.jobs/jobs/10567698/data-center-technician---internship-?cmpid=DA": "_amazon",
    }
    for url, name in expected.items():
        read = reader_for(url)
        assert read is not None and read.__name__ == name, url
        assert details.reader_for(url) is read, url  # details.READERS includes them, and no older reader takes them first
    assert reader_for("https://www.tesla.com/careers/search/job/279570?source=Indeed") is None  # bot-protected


def test_details_reads_a_role_through_the_new_readers(monkeypatch):
    monkeypatch.setattr(details, "READERS", details.READERS + readers_more.MORE_READERS)
    serve(monkeypatch, (FIXTURES / "readers_tiktok.html").read_text(encoding="utf-8"))
    opp = Opportunity(title="Frontend Software Engineer Intern", org="TikTok", source="github_lists",
                      url="https://lifeattiktok.com/search/7668584161852229893?utm_source=github-vansh-ouckah")
    assert details.read(opp) and apply_rules(opp).pay == "$45–60/hr"

    serve(monkeypatch, (FIXTURES / "readers_rippling.json").read_text(encoding="utf-8"))
    opp = Opportunity(title="Software Engineer 1", org="Momentum", source="github_lists",
                      url="https://ats.rippling.com/momentumcareers/jobs/dd4281b8-fa2a-4833-8370-b1859933b612")
    assert details.read(opp) and opp.pay == "$110K–155K/yr" and opp.pay_from == "field"
