"""Brazilian sources: CIEE, Sólides, Super Estágios, IEL, Cia de Talentos,
FAPESP, SmartRecruiters and Workday (Brazil). Every test reads a saved
sample response from tests/fixtures/."""

from datetime import date

import pytest
from conftest import fixture_json, fixture_text

from radar.labels import apply_rules
from radar.sources import ciadetalentos, ciee, fapesp, iel, smartrecruiters, solides, superestagios, workday

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
