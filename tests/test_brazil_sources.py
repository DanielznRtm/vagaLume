"""Brazilian sources: CIEE, Sólides, Super Estágios, IEL, Cia de Talentos,
FAPESP, SmartRecruiters and Workday (Brazil). Every test reads a saved
sample response from tests/fixtures/."""

from datetime import date

import pytest
from conftest import fixture_json, fixture_text

from radar.labels import apply_rules
from radar.sources import abler, ciadetalentos, ciee, eureca, fapesp, iel, oracle_hcm, rss_jobs, smartrecruiters, solides, superestagios, workday

TODAY = date(2026, 10, 9)


def test_ciee_builds_titles_from_the_area():
    items = ciee.parse(fixture_json("ciee_vagas.json"))
    assert len(items) == 3
    first = items[0]
    assert first.title.startswith("Estágio em ")
    assert first.url.startswith("https://portal.ciee.org.br/quero-uma-vaga/?codigoVaga=")
    assert first.location.endswith(", Brazil")
    assert items[2].pay == "R$1,200–1,500/mo"  # "a combinar" range
    apply_rules(first)
    assert first.regions == ["Brazil"]


def test_ciee_bad_answer_raises():
    with pytest.raises(ValueError):
        ciee.parse({"error": "x"})


def test_solides_skips_hidden_jobs_and_reads_pay():
    items = solides.parse(fixture_json("solides_vacancies.json"))
    assert len(items) == 2  # the third is hidden
    assert items[0].url.startswith("https://vagas.solides.com.br/vaga/")
    assert items[1].pay == "R$1,400/mo"
    assert all(o.hints == ["student"] for o in items)


def test_solides_stops_at_old_pages(monkeypatch):
    page = fixture_json("solides_vacancies.json")
    calls = []

    def fake_get_json(url, **kwargs):
        calls.append(url)
        old = len(calls) > 2
        jobs = [dict(page["data"][0], id=len(calls) * 100 + n, createdAt="2020-01-01" if old else "2026-10-01") for n in range(20)]
        return {"data": jobs}

    monkeypatch.setattr(solides, "get_json", fake_get_json)
    result = solides.fetch({}, today=TODAY)
    assert len(calls) == 3 and len(result.items) == 40


def test_superestagios_strips_the_html_comment_and_keeps_superior():
    items = superestagios.parse(fixture_text("superestagios_vagas.txt"), ["Superior"])
    assert [o.title for o in items] == ["Estágio em Turismo, Administração", "Estágio em Engenharia de Produção, Engenharia Mecânica"]
    first = items[0]
    assert first.org == "Empresa confidencial"
    assert first.location == "Rio de Janeiro, RJ, Brazil (on-site)"
    assert first.pay == "R$2,500/mo"
    assert first.url.endswith("?i=MzI1Njk2QEAyNjI0OQ==")  # base64 of "325696@@26249"
    everything = superestagios.parse(fixture_text("superestagios_vagas.txt"), [])
    assert len(everything) == 4


def test_iel_reads_liferay_objects():
    items = iel.parse(fixture_json("iel_vagas.json"))
    assert len(items) == 3
    first = items[0]
    assert first.title == "Estágio técnico em eletrotécnica"  # ALL CAPS made readable
    assert first.location == "Natal, RN, Brazil (on-site)"
    assert first.posted_date == "2026-10-08"
    assert first.org == "Empresa não informada (IEL)"


def test_cia_de_talentos_keeps_open_programs_only():
    items = ciadetalentos.parse(fixture_json("ciadetalentos.json"), today=TODAY)
    titles = [o.title for o in items]
    assert "Quem Indica" not in titles  # a referral campaign
    assert "Programa de Estágio Aché 2026" not in titles  # closed 157 days ago
    globo = items[0]
    assert globo.title == "Programa Estagiar Globo 2026" and globo.deadline == "2026-10-13"
    assert globo.hints == ["student"]
    trainee = next(o for o in items if "Trainee" in o.title)
    assert trainee.hints == ["unsure-student"]


def test_fapesp_keeps_grad_and_undergrad_grants_only():
    items = fapesp.parse(fixture_text("fapesp_oportunidades.html"))
    titles = [o.title for o in items]
    assert len(items) == 2  # postdoc (tipo 1) and TT-IV (tipo 7) are left out
    assert any("Mestrado" in t for t in titles) and any("Doutorado" in t for t in titles)
    doctorate = next(o for o in items if "Doutorado" in o.title)
    apply_rules(doctorate)
    assert "PhD-level?" in doctorate.warnings and doctorate.area == "research"
    assert doctorate.url.startswith("https://fapesp.br/oportunidades/x/")
    assert doctorate.deadline[:4] == "2026"
    assert doctorate.location.endswith(", SP, Brazil")


def test_fapesp_page_without_postings_raises():
    with pytest.raises(ValueError):
        fapesp.parse("<html>em manutenção</html>")


def test_smartrecruiters_keeps_student_titles():
    company = {"id": "SyngentaGroup", "name": "Syngenta"}
    items = smartrecruiters.parse(fixture_json("smartrecruiters_postings.json"), company)
    assert len(items) == 2  # "Analista ... Pleno" is not a student role
    assert all(o.org == "Syngenta" for o in items)
    assert items[0].url.startswith("https://jobs.smartrecruiters.com/SyngentaGroup/")
    assert items[0].location.endswith("Brazil")


def test_workday_picks_brazil_and_student_job_types():
    data = fixture_json("workday_gm.json")
    applied, student = workday.choose_facets(data)
    assert applied["Location_Country"] == [workday.BRAZIL_ID]
    assert student and len(applied["workerSubType"]) == 3  # intern/trainee, co-op, apprentice
    site = {"tenant": "generalmotors", "wd": 5, "site": "Careers_GM", "name": "General Motors"}
    items = workday.parse(data, site, from_student_facet=True, today=TODAY)
    assert items[0].location == "São Caetano do Sul, Brazil"
    assert items[0].url == "https://generalmotors.wd5.myworkdayjobs.com/en-US/Careers_GM/job/Sao-Caetano-do-Sul/Programa-de-Estgio-GM-2027_JR-1"
    assert items[0].posted_date == "2026-10-06"
    assert items[1].location == "2 Locations, Brazil"
    # Without the job-type filter, only student-looking titles stay.
    titles = [o.title for o in workday.parse(data, site, from_student_facet=False, today=TODAY)]
    assert titles == ["Programa de Estágio GM 2027", "Aprendizes Senai"]


def test_workday_site_without_brazil_filter_raises():
    with pytest.raises(ValueError):
        workday.choose_facets({"facets": []})


def test_workday_falls_back_to_brazilian_cities():
    """GE Vernova and J&J have only a city filter (sometimes inside a group)."""
    cities = [("Sao Paulo", "sp"), ("Taubate", "tb"), ("Buenos Aires", "ba"), ("Abidjan", "ab"),
              ("São José dos Campos, São Paulo, Brazil", "sjc"), ("Erie, PA, United States", "erie")]
    data = {"facets": [
        {"facetParameter": "workerSubType", "values": [{"descriptor": "Co-op/Intern (Fixed Term)", "id": "intern"}]},
        {"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locations", "values": [{"descriptor": d, "id": i} for d, i in cities]}]},
    ]}
    applied, student = workday.choose_facets(data)
    assert applied["locations"] == ["sp", "tb", "sjc"] and applied["workerSubType"] == ["intern"] and student


def test_eureca_keeps_internships_and_trainees():
    job = {"id": "abc", "name": "Finanças", "programName": "Programa de Estágio Serasa Experian 2027",
           "companyName": "Serasa Experian ", "contractTypeKey": "internship", "workModel": "hibrido",
           "locations": {"states": ["SP"], "cities": ["São Paulo"]}, "salary": {"minCents": 215000, "maxCents": None},
           "createdAt": "2026-10-01 18:17:14+00", "endApplying": "2026-11-05T02:59:00.000Z", "description": "<p>x</p>"}
    apprentice = dict(job, id="d", contractTypeKey="young-apprentice")
    items = eureca.parse({"items": [job, apprentice], "total": 2, "pageSize": 200})
    assert len(items) == 1
    opp = items[0]
    assert opp.title == "Programa de Estágio Serasa Experian 2027: Finanças" and opp.org == "Serasa Experian"
    assert opp.location == "São Paulo, SP, Brazil (hybrid)" and opp.pay == "R$2,150/mo"
    assert opp.deadline == "2026-11-04"  # 02:59 UTC is 23:59 the day before in Brasília
    assert opp.url == "https://app.eureca.me/vagas/abc" and opp.hints == ["student"]


def test_abler_reads_vale_estagios():
    payload = {"pagy": {"next": None}, "vacancies": {"data": [
        {"attributes": {"title": "Estágio | Operações Logísticas | Vale (MG)", "salary": "R$ 1.500,00",
                        "created_at": "01/10/2026", "location": "Nova Lima - MG", "contracting_regime": "Estagiário"},
         "links": {"vacancy_url": "https://estagionavale.abler.com.br/vagas/x"}},
        {"attributes": {"title": "Analista de RH", "contracting_regime": "CLT"}, "links": {"vacancy_url": "y"}},
    ]}}
    items = abler.parse(payload, {"subdomain": "estagionavale", "name": "Vale"})
    assert [(o.title, o.location, o.pay, o.posted_date) for o in items] == [
        ("Estágio | Operações Logísticas | Vale (MG)", "Nova Lima - MG, Brazil", "R$1,500/mo", "2026-10-01")]


def test_oracle_hcm_takes_the_state_from_the_title():
    payload = {"items": [{"TotalJobsCount": 3, "requisitionList": [
        {"Id": "41627", "Title": "Programa de Estágio ArcelorMittal | Ceará", "PrimaryLocation": "Brazil", "PostedDate": "2026-09-21"},
        {"Id": "2", "Title": "PESSOA ESTAGIÁRIA - ENSINO SUPERIOR", "PrimaryLocation": "Resende, RJ, Brazil"},
        {"Id": "3", "Title": "Analista Financeiro Sênior", "PrimaryLocation": "Brazil"},
    ]}]}
    site = {"host": "emfg.fa.em4.oraclecloud.com", "site": "CX_4001", "name": "ArcelorMittal"}
    items, total = oracle_hcm.parse(payload, site)
    assert total == 3 and [o.location for o in items] == ["Ceará, CE, Brazil", "Resende, RJ, Brazil"]
    assert items[0].url == "https://emfg.fa.em4.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_4001/job/41627"


def test_rss_jobs_reads_the_place_in_successfactors_titles():
    feed = """<rss><channel>
      <item><title>Estagiário de Vendas | Itajaí/SC (Itajaí, SC, BR, 88311-480)</title><link>https://k/1</link>
            <pubDate>Thu, 15 Oct 2026 00:00:00 GMT</pubDate></item>
      <item><title>Estágio em Engenharia (Araras, BR, 13690-000)</title><link>https://k/2</link></item>
      <item><title>Gerente de Produção (Lages, SC, BR, 88500-000)</title><link>https://k/3</link></item>
    </channel></rss>"""
    items = rss_jobs.parse(feed, {"name": "Klabin", "country": "Brazil"})
    assert [(o.title, o.location) for o in items] == [
        ("Estagiário de Vendas | Itajaí/SC", "Itajaí, SC, Brazil"), ("Estágio em Engenharia", "Araras, Brazil")]
    assert items[0].posted_date == "2026-10-15"


def test_workday_global_goes_country_by_country(monkeypatch):
    """Airbus-like site: the job-type filter is called Worker_Type, places are "Toulouse Area",
    and Workday sends the total on the first page only."""
    facets = [{"facetParameter": "Worker_Type", "values": [{"descriptor": "Trainee / Student", "id": "stu"},
                                                            {"descriptor": "Regular", "id": "reg"}]},
              {"facetParameter": "Location_Country", "values": [{"descriptor": "France", "id": "fr", "count": 25},
                                                                 {"descriptor": "Germany", "id": "de", "count": 1}]}]
    calls = []

    def fake_post(url, payload):
        calls.append(payload)
        applied, offset = payload["appliedFacets"], payload["offset"]
        if payload["limit"] == 1:
            return {"facets": facets, "total": 26}
        country = applied["Location_Country"][0]
        count = 25 if country == "fr" else 1
        jobs = [{"title": f"STAGE 2027 - Job {country}{offset + n}", "externalPath": f"/job/{country}{offset + n}",
                 "locationsText": "Toulouse Area" if country == "fr" else "Munich, Germany", "postedOn": "Posted Today"}
                for n in range(min(20, count - offset))]
        return {"jobPostings": jobs, "total": count if offset == 0 else 0}

    monkeypatch.setattr(workday, "post_json", fake_post)
    items, requests_made = workday.fetch_site_global({"tenant": "ag", "wd": 3, "site": "Airbus", "name": "Airbus"})
    assert len(items) == 26 and requests_made == len(calls) == 2 + 2 + 1
    assert items[0].location == "Toulouse Area, France" and items[-1].location == "Munich, Germany"
    assert all(c["appliedFacets"].get("Worker_Type") == ["stu"] for c in calls[1:])
