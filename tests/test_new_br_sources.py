"""New Brazilian sources: InHire, Eightfold (PCSX), BCG, Goldman Sachs, IBM,
TOTVS RH, Shopee and Academia do Universitário. Every test reads a saved
(trimmed) real response from tests/fixtures/."""

import pytest
from conftest import fixture_json, fixture_text

from radar.labels import apply_rules
from radar.sources import academia, company_sites, eightfold, inhire, shopee, totvs_rh

KPMG = {"tenant": "kpmg", "name": "KPMG"}


# --- InHire ------------------------------------------------------------------
def test_inhire_opens_only_student_looking_roles():
    wanted = inhire.candidates(fixture_json("inhire_lean.json"))
    titles = [job["displayName"] for job in wanted]
    assert len(titles) == 3  # two on the estágio career page + "Banco de Talentos Estágio"
    assert not any("Aprendiz" in t or "Gerente" in t or "Consultor Jr" in t for t in titles)


def test_inhire_reads_location_contract_and_dates():
    items = inhire.parse(fixture_json("inhire_lean.json"), fixture_json("inhire_details.json"), KPMG)
    assert len(items) == 3
    first = items[0]
    assert first.title == "Estágio - Lighthouse Technology (LHT), São Paulo, SP"
    assert first.org == "KPMG" and first.source == "inhire"
    assert first.url.startswith("https://kpmg.inhire.app/starters-advisory-estagio/vagas/")
    assert first.location.startswith("São Paulo, SP, Brazil (")
    assert len(first.posted_date) == 10 and first.posted_date.startswith("2026-")
    assert first.description and "<" not in first.description
    assert all(o.hints == ["student"] for o in items)
    pool = next(o for o in items if o.title.startswith("Banco de Talentos"))
    assert pool.url.startswith("https://kpmg.inhire.app/vagas/")  # the default career page
    apply_rules(first)
    assert first.regions == ["Brazil"] and first.states == ["SP"]


def test_inhire_early_career_page_is_unsure_and_estagio_contract_is_student():
    sample = fixture_json("inhire_deloitte.json")
    items = inhire.parse(sample["lean"], sample["details"], {"tenant": "deloitte", "name": "Deloitte"})
    hints = {o.title: o.hints for o in items}
    assert len(items) == 3  # the senior auditor on the default page is left out
    assert hints["Estágio em Gestão de Projetos (Infraestrutura e Pojetos de Capital)"] == ["student"]
    novos = [h for t, h in hints.items() if "Novos Talentos" in t]
    assert novos == [["unsure-student"], ["unsure-student"]]  # "inicio-de-carreira" page, CLT contract


def test_inhire_without_job_page_still_keeps_the_role():
    items = inhire.parse(fixture_json("inhire_lean.json"), {}, KPMG)
    assert len(items) == 3 and all(o.location == "Brazil" for o in items)


def test_inhire_bad_answer_raises():
    with pytest.raises(ValueError):
        inhire.candidates({"message": "Tenant not found"})


# --- Eightfold ---------------------------------------------------------------
def test_eightfold_keeps_interns_and_reads_places():
    site = {"host": "morganstanley.eightfold.ai", "domain": "morganstanley.com", "name": "Morgan Stanley"}
    items, total = eightfold.parse(fixture_json("eightfold_morganstanley.json"), site)
    assert total == 242
    assert len(items) == 6  # "Return to Work Program", "Vice President, Strats"... are left out
    first = items[0]
    assert first.title.startswith("Intern")
    assert first.url.startswith("https://morganstanley.eightfold.ai/careers/job/")
    assert first.location.endswith(", United States of America (on-site)")
    assert first.posted_date.startswith("20")


def test_eightfold_mercado_livre_practicantes():
    site = {"host": "mercadolibre.eightfold.ai", "domain": "mercadolibre.com", "name": "Mercado Livre"}
    items, _ = eightfold.parse(fixture_json("eightfold_mercadolibre.json"), site)
    assert len(items) == 7
    assert items[0].location.startswith("Bogotá, Colombia")
    assert items[0].org == "Mercado Livre"


def test_eightfold_not_pcsx_raises():
    with pytest.raises(ValueError):
        eightfold.parse({"message": "Not authorized for PCSX"}, {"host": "x", "domain": "x"})


def test_eightfold_brasil_place():
    assert eightfold._place("Brasil,Brazil") == "Brazil"
    assert eightfold._place("Sao Paulo, São Paulo, Brazil") == "Sao Paulo, São Paulo, Brazil"


# --- BCG, Goldman Sachs, IBM -------------------------------------------------
def test_bcg_internships_in_brazil():
    items, total = company_sites.parse_bcg(fixture_json("bcg_phenom.json"))
    assert total == 3 and len(items) == 3
    first = items[0]
    assert first.title == "Brazil Market- Research Intern"
    assert first.location == "Rio de Janeiro, RJ, Brazil / São Paulo, SP, Brazil"
    assert first.url == "https://careers.bcg.com/global/en/job/58670"
    assert first.posted_date == "2026-07-08"
    assert first.source == "bcg" and "Research Intern" in first.description
    body = company_sites.bcg_body("Brazil", 50)
    assert body["selected_fields"] == {"country": ["Brazil"], "jobType": ["Internship"]} and body["from"] == 50


def test_goldman_keeps_off_cycle_internship_not_new_analyst():
    items, total = company_sites.parse_goldman(fixture_json("goldman_campus.json"))
    assert total == 2
    assert [o.title for o in items] == ["2027 | Americas | Sao Paulo | Investment Banking | Seasonal/Off Cycle Internship (Trainee)"]
    role = items[0]
    assert role.url == "https://higher.gs.com/roles/182565"
    assert role.location == "Sao Paulo, SP, Brazil"
    assert role.posted_date == "2026-10-06"
    apply_rules(role)
    assert role.states == ["SP"]


def test_goldman_bad_answer_raises():
    with pytest.raises(ValueError):
        company_sites.parse_goldman({"errors": [{"message": "x"}]})


def test_ibm_keeps_internship_level_only():
    items, total = company_sites.parse_ibm(fixture_json("ibm_search.json"))
    assert total == 7
    assert [o.title for o in items] == ["Estagiário(a) em Operações de Vendas (Sales Operations Intern)"]
    intern = items[0]
    assert intern.location.startswith("São Paulo, SP, Brazil")
    assert intern.url.startswith("https://careers.ibm.com/careers/JobDetail?jobId=")
    assert intern.posted_date.startswith("2026-")
    assert intern.hints == ["student"]


def test_ibm_text_fixes():
    assert company_sites._unmangle("Youâ€™ll work") == "You’ll work"
    assert company_sites._unmangle("SÃO PAULO") == "SÃO PAULO"  # already right
    assert company_sites._ibm_place("SÃO PAULO, BR") == "São Paulo, SP, Brazil"
    assert company_sites._ibm_place("No City, BR") == "Brazil"


# --- TOTVS RH ------------------------------------------------------------------
def test_totvs_rh_keeps_the_estagiario_position():
    items = totvs_rh.parse(fixture_text("totvs_rh_vagas.html"), {"tenant": "vempratotvs", "name": "TOTVS"})
    assert len(items) == 1
    role = items[0]
    assert role.title == "Estagiário – Quality Assurance - Time 2"
    assert role.location == "São Paulo, SP, Brazil"
    assert role.url == "https://atracaodetalentos.totvs.app/vempratotvs/job-opportunity/11654"
    assert role.hints == ["student"]


def test_totvs_rh_bad_page_raises():
    with pytest.raises(ValueError):
        totvs_rh.parse("<html>Página não encontrada</html>", {"tenant": "x"})


# --- Shopee --------------------------------------------------------------------
def test_shopee_offices_and_internships():
    cities = shopee.parse_cities(fixture_json("shopee_meta.json"), ["Brazil"])
    assert cities == {2: ("São Paulo", "Brazil")}
    both = shopee.parse_cities(fixture_json("shopee_meta.json"), ["Brazil", "Singapore"])
    items, total = shopee.parse(fixture_json("shopee_jobs.json"), both)
    assert total == 165
    # The 4 Singapore internships; the two São Paulo jobs only mention estágio in the text.
    assert len(items) == 4 and all("Intern" in o.title for o in items)
    first = items[0]
    assert first.location == "Singapore"
    assert first.url.startswith("https://careers.shopee.com.br/job-detail/J") and first.url.endswith("/1")
    assert first.hints == ["student"] and first.description
    only_brazil, _ = shopee.parse(fixture_json("shopee_jobs.json"), cities)
    assert only_brazil == []


# --- Academia do Universitário ------------------------------------------------
def test_academia_programs_with_cities_pay_and_deadline():
    items, pages = academia.parse(fixture_json("academia_programs.json"), fixture_json("academia_details.json"))
    assert pages == 1 and len(items) == 3
    braskem, vw, cinpal = items
    assert braskem.title == "Programa de estágio Braskem 2027" and braskem.org == "Braskem"
    assert braskem.pay == "R$2,200–2,800/mo"
    assert braskem.location.startswith("Camaçari, BA, Brazil / Campinas, SP, Brazil")
    assert "+6 cities" in braskem.location and braskem.location.endswith("(hybrid / on-site)")
    assert braskem.posted_date == "2026-10-01" and braskem.deadline == "check page"
    assert braskem.url == "https://vagas.academiadouniversitario.com.br/programas/programa-de-estagio-braskem"
    assert vw.deadline == "2026-10-24"
    assert cinpal.location.startswith("São Paulo, SP, Brazil")  # no page read: the list's main city
    assert all(o.hints == ["student"] for o in items)


def test_academia_jobs():
    items, _ = academia.parse(fixture_json("academia_jobs.json"), fixture_json("academia_details.json"))
    ons, pool, rd = items
    assert ons.title == "Estagio Administrativo" and ons.org == "ONS"
    assert ons.location == "Rio de Janeiro, RJ, Brazil (hybrid)"
    assert ons.pay == "R$1,737/mo"
    assert (ons.posted_date, ons.deadline) == ("2026-10-14", "2026-11-13")
    assert ons.hints == ["student"]
    assert pool.hints == ["unsure-student"]  # "Banco de talentos Volkswagen"
    assert pool.location == "Brazil (hybrid)"  # "Múltiplas localidades"
    assert pool.pay == ""  # the list says R$ 0,01
    assert rd.location == "São Paulo, SP, Brazil (hybrid)" and rd.pay == "R$2,700/mo"  # no page read: the list's city
    apply_rules(ons)
    assert ons.states == ["RJ"]


def test_academia_bad_answer_raises():
    with pytest.raises(ValueError):
        academia.parse({"message": "erro"}, {})


def test_ibm_places_use_the_country_we_searched():
    from radar.sources import company_sites

    assert company_sites._ibm_place("TORONTO, CA", "Canada") == "Toronto, Canada"  # CA is Canada here, not California
    assert company_sites._ibm_place("Multiple Cities", "United States") == "United States"
    assert company_sites._ibm_place("SÃO PAULO, BR") == "São Paulo, SP, Brazil"
