"""Reading a role's own job page (radar/details.py)."""

from radar import db, details
from radar.labels import apply_rules
from radar.models import Opportunity


def role(url: str, source: str = "github_lists", **kwargs) -> Opportunity:
    return Opportunity(title="Software Engineer Intern", org="X", source=source, url=url, **kwargs)


def test_each_job_board_is_asked_through_its_api(monkeypatch):
    asked = []

    def fake_get_json(url, **kwargs):
        asked.append(url)
        if "greenhouse" in url:
            return {"content": "&lt;p&gt;Build things.&lt;/p&gt;", "pay_input_ranges": [{"min_cents": 4500000, "max_cents": 5500000, "currency_type": "USD"}]}
        if "myworkdayjobs" in url:
            return {"jobPostingInfo": {"jobDescription": "<p>The pay range is $40 - $50 per hour.</p>"}}
        if "lever" in url:
            return {"descriptionPlain": "Hello", "salaryRange": {"min": 30, "max": 40, "currency": "USD", "interval": "per-hour-wage"}}
        return {}

    monkeypatch.setattr(details, "get_json", fake_get_json)
    gh = role("https://job-boards.greenhouse.io/acme/jobs/123")
    assert details.read(gh) and gh.pay == "$45K–55K/yr" and "Build things." in gh.description
    wd = role("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Intern_JR1")
    assert details.read(wd) and apply_rules(wd).pay == "$40–50/hr"
    lv = role("https://jobs.lever.co/acme/abc-123")
    assert details.read(lv) and lv.pay == "$30–40/hr"
    assert asked == [
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/123?pay_transparency=true",
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Intern_JR1",
        "https://api.lever.co/v0/postings/acme/abc-123",
    ]
    assert not details.read(role("https://www.tesla.com/careers/123"))  # no reader: left as it is


def test_iel_pay_is_on_the_vacancy_page(monkeypatch):
    monkeypatch.setattr(details, "get_text", lambda url: "<p>Cidade: Belo Horizonte</p><p>Remuneração: R$ 1.200,00</p>")
    opp = Opportunity(title="Estágio de Calibração", org="X", source="iel", url="https://carreiras.iel.org.br/MG/vaga/estagio/22928/x")
    assert details.read(opp) and apply_rules(opp).pay == "R$1,200/mo"


def test_enrich_reads_new_roles_once_and_the_database_keeps_what_the_page_gave(monkeypatch, tmp_path):
    monkeypatch.setattr(details, "get_text", lambda url: "Remuneração: R$ 1.500,00. Requisitos: Excel, Power BI.")
    conn = db.connect(tmp_path / "radar.db")
    url = "https://carreiras.iel.org.br/MG/vaga/estagio/1/x"

    first = Opportunity(title="Estágio Administrativo", org="X", source="iel", url=url)
    assert details.enrich([first], conn, "2026-10-16") == {"iel": 1}
    db.upsert(conn, apply_rules(first), "2026-10-16")

    # The next day the page isn't read again (not due), and the list alone has no pay: keep the page's.
    second = Opportunity(title="Estágio Administrativo", org="X", source="iel", url=url)
    assert details.enrich([second], conn, "2026-10-17") == {}
    db.upsert(conn, apply_rules(second), "2026-10-17")
    stored = db.load_all(conn)[0]
    assert stored.pay == "R$1,500/mo" and stored.detail_checked == "2026-10-16"

    # After a month it is read again.
    third = Opportunity(title="Estágio Administrativo", org="X", source="iel", url=url)
    assert details.enrich([third], conn, "2026-11-20") == {"iel": 1}
