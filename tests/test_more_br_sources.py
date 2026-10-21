"""More Brazilian sources: CIEE public-sector editais, Fundação Mudes, Recrutei,
TAQE, Quickin, the Paraná state Central de Estágios and USP's estágio murals.
Every test reads a saved (trimmed) real response from tests/fixtures/."""

from datetime import date

import pytest
from conftest import fixture_json, fixture_text

from radar.labels import apply_rules
from radar.models import NO_DEADLINE
from radar.sources import ciee_editais, mudes, parana, quickin, recrutei, taqe, usp_estagios
from radar.sources.brtext import SCHOOL_TITLE, br_place, join_places, title_pt

TODAY = date(2026, 10, 21)


# --- shared helpers -------------------------------------------------------------
def test_title_pt_keeps_acronyms_and_small_words():
    assert title_pt("TRIBUNAL REGIONAL ELEITORAL DO ESTADO DE MATO GROSSO DO SUL | TRE-MS") == (
        "Tribunal Regional Eleitoral do Estado de Mato Grosso do Sul | TRE-MS")
    assert title_pt("FINANCIADORA DE ESTUDOS E PROJETOS - FINEP", acronym_tail=True) == "Financiadora de Estudos e Projetos - FINEP"
    assert title_pt("TRIBUNAL REGIONAL DO TRABALHO DA 3ª REGIÃO - TRT 3 - MG") == "Tribunal Regional do Trabalho da 3ª Região - TRT 3 - MG"
    assert title_pt("SANTA BÁRBARA D'OESTE") == "Santa Bárbara D'Oeste"
    assert title_pt("EDITAL 02/2026 (NÍVEL SUPERIOR)") == "Edital 02/2026 (Nível Superior)"
    assert title_pt("HCB (BRASÍLIA-DF)") == "HCB (Brasília-DF)"
    assert title_pt("Estágio em Dados - Pricing") == "Estágio em Dados - Pricing"  # mixed case: untouched


def test_br_place_and_join_places():
    assert br_place("CAMPO GRANDE", "MS") == "Campo Grande, MS, Brazil"
    assert br_place("Rio de Janeiro", "Rio de Janeiro") == "Rio de Janeiro, RJ, Brazil"  # full state name
    assert br_place("NITERÓI") == "Niterói, RJ, Brazil"  # state from IBGE's city list
    assert br_place("", "SP") == "SP, Brazil" and br_place("") == "Brazil"
    many = [br_place(c, "SP") for c in ("Santos", "Bauru", "Franca", "Marília", "Sorocaba", "Jundiaí", "Avaré", "Santos")]
    assert join_places(many) == ("Santos, SP, Brazil / Bauru, SP, Brazil / Franca, SP, Brazil / Marília, SP, Brazil / "
                                 "Sorocaba, SP, Brazil / Jundiaí, SP, Brazil / +1 cities, Brazil")


@pytest.mark.parametrize("title, school", [
    ("ESTÁGIO ENSINO MÉDIO - VGAJPN210", True),
    ("Estágio Técnico em Elétrica / Eletrônica ou Mecânica", True),
    ("ESTÁGIO EM TÉCNICO EM ENFERMAGEM (RIO DE JANEIRO - RJ)", True),
    ("Estagiário(a) Técnico(a) - Osasco", True),
    ("Estágio em Engenharia Elétrica", False),
    ("Estágio em Suporte Técnico", False),
])
def test_school_level_titles(title, school):
    assert bool(SCHOOL_TITLE.search(title)) is school


# --- CIEE public-sector editais ---------------------------------------------------
def test_ciee_editais_keeps_open_and_upcoming_without_apprentices():
    sample = fixture_json("ciee_editais.json")
    ids = [e["id"] for e in ciee_editais.open_editais(sample["vitrine"])]
    # Jovem Aprendiz pre-registration, a finished edital and an inactive one are left out.
    assert ids == [17411, 13721, 13766, 17443]


def test_ciee_editais_reads_courses_places_and_deadline():
    sample = fixture_json("ciee_editais.json")
    items = ciee_editais.parse(sample["vitrine"], sample["details"])
    assert [o.url for o in items] == [f"https://pp.ciee.org.br/vitrine/{i}/detalhe" for i in (17411, 13721, 17443)]  # 13766: ensino médio only
    tre = items[0]
    assert tre.title == "Processo seletivo de estágio: Edital 02/2026 (Nível Superior)"
    assert tre.org == "Tribunal Regional Eleitoral do Estado de Mato Grosso do Sul - TRE-MS"
    assert tre.location == "Campo Grande, MS, Brazil"
    assert (tre.posted_date, tre.deadline) == ("2026-10-14", "2026-10-29")
    assert "Engenharia Civil (3º ao 9º semestre)" in tre.description
    assert "<" not in tre.description and tre.hints == ["student"]
    finep = items[1]
    assert finep.org == "Financiadora de Estudos e Projetos - FINEP"
    assert finep.location == "Brasília, DF, Brazil / Rio de Janeiro, RJ, Brazil / São Paulo, SP, Brazil"
    cptm = items[2]  # no cities listed yet: the state from the órgão name
    assert cptm.location == "SP, Brazil" and cptm.description.startswith("Inscrições em breve.")
    apply_rules(tre)
    assert tre.regions == ["Brazil"] and tre.states == ["MS"]


def test_ciee_editais_bolsa_table_when_given():
    detail = {"bolsasAuxilio": [
        {"valor": 1100, "periodo": "MES", "editalCurso": {"curso": {"nivel": "SU"}}},
        {"valor": 1400, "periodo": "MES", "editalNivel": {"nivel": {"sigla": "PG"}}},
        {"valor": 700, "periodo": "MES", "editalCurso": {"curso": {"nivel": "EM"}}},  # high school: ignored
    ]}
    assert ciee_editais._pay(detail) == "R$1,100–1,400/mo"
    assert ciee_editais._pay({"bolsasAuxilio": []}) == ""


# --- Fundação Mudes -----------------------------------------------------------------
def test_mudes_keeps_higher_education_estagios_only():
    rows = mudes.parse_list(fixture_text("mudes_vagas.html"))
    assert [r["code"] for r in rows] == ["83900", "85198", "85250"]
    # Técnico / ensino médio estágios, the aprendiz programme, PCD and CLT jobs are left out.
    assert all("TÉCNICO" not in r["course"].upper() for r in rows)


def test_mudes_reads_bolsa_city_and_detail_page():
    items = mudes.parse(fixture_text("mudes_vagas.html"), {"83900": fixture_text("mudes_detail.html")})
    first = items[0]
    assert first.title == "Estágio em Administração" and first.org == "Fundação Mudes"
    assert first.url == "https://mudes.org.br/descricao-vaga?codigoOferta=83900"
    assert first.location == "Maricá, RJ, Brazil (on-site)"
    assert first.pay == "R$1,000/mo" and first.pay_from == "field"
    assert "2º ao 6º Período" in first.description and "<" not in first.description
    no_detail = items[1]
    assert no_detail.location == "Niterói, RJ, Brazil" and no_detail.pay == "R$800/mo"
    assert mudes._bolsa("Bolsa: R$437.60") == "R$437.60/mo"


# --- Recrutei ---------------------------------------------------------------------
def test_recrutei_list_keeps_estagios_in_brazil():
    rows = recrutei.parse_list(fixture_text("recrutei_estagios.html"), TODAY)
    titles = [r["title"] for r in rows]
    assert len(rows) == 6 and len({r["url"] for r in rows}) == 6
    assert not any("ENSINO MÉDIO" in t or "JOVEM" in t or "SUMINISTRO" in t or "VENTAS" in t for t in titles)
    first = rows[0]
    assert first["id"] == "162528" and first["company"] == "PeoplePlan" and first["place"] == "Palhoça, SC"
    assert first["url"] == "https://empregos.recrutei.com.br/vaga/PeoplePlan/162528-estagio-em-departamento-pessoal"
    assert first["posted"] == "2026-10-21"  # "Publicada há 7 horas"
    assert recrutei.has_next(fixture_text("recrutei_estagios.html"), 1)


def test_recrutei_detail_and_pay():
    items = recrutei.parse(fixture_text("recrutei_estagios.html"), {"162528": fixture_json("recrutei_vacancy.json")}, TODAY)
    first = items[0]
    assert first.title == "Estágio em Departamento Pessoal" and first.org == "PeoplePlan"
    assert first.location == "Palhoça, SC, Brazil (on-site)"
    assert (first.posted_date, first.deadline) == ("2026-10-21", "2026-11-20")
    assert first.pay == "R$1,000/mo" and first.hints == ["student"]
    assert first.description and "<" not in first.description
    ranged = next(o for o in items if "COD:1157" in o.title)
    assert ranged.pay == "R$1,100–1,300/mo" and ranged.deadline == NO_DEADLINE
    hybrid = next(o for o in items if "Home Office" in o.title)
    assert hybrid.location.endswith("(hybrid)")
    assert recrutei._ago("Publicada há 2 semanas", TODAY) == "2026-10-07"
    assert recrutei._pay("A combinar") == ""


# --- TAQE -------------------------------------------------------------------------
def test_taqe_keeps_university_estagios():
    sample = fixture_json("taqe_vacancies.json")
    wanted = taqe.students(sample["list"])
    # ensino médio estágios, the jovem aprendiz role and a course without a regime are left out
    assert [v["key"] for v in wanted] == ["servier-estagio-administracao-ou-direito-v1", "banco-de-talentos-estagio-diversos-cursos"]


def test_taqe_reads_detail_pay_and_hidden_company():
    sample = fixture_json("taqe_vacancies.json")
    items = taqe.parse(sample["list"], {sample["detail"]["key"]: sample["detail"]})
    servier = items[0]
    assert servier.title.startswith("Servier - Estágio - Marketing")
    assert servier.org == "Ciee One Rio de Janeiro"
    assert servier.url == "https://vagas.taqe.com.br/ciee-rj/servier-estagio-administracao-ou-direito-v1"
    assert servier.location == "Rio de Janeiro, RJ, Brazil (on-site)"
    assert servier.pay == "R$1,700/mo" and servier.posted_date == "2026-10-20"
    assert "Atividades:" in servier.description and "Requisitos:" in servier.description
    hidden = items[1]
    assert hidden.org == "Empresa confidencial"
    assert hidden.url.startswith("https://vagas.taqe.com.br/company-confidential/")
    assert hidden.pay == "R$800–1,500/mo"


# --- Quickin ----------------------------------------------------------------------
def test_quickin_keeps_estagios():
    sample = fixture_json("quickin_levelcinco.json")
    board = {"slug": "levelcinco", "name": "Level Cinco"}
    items = quickin.parse(sample["jobs"], board)
    assert len(items) == 4 and not any(o.title.startswith("CLT") for o in items)
    first = items[0]
    assert first.url == "https://jobs.quickin.io/levelcinco/jobs/6ab2afcba2ae7c00135c88c4"
    assert first.location == "Porto Alegre, RS, Brazil (on-site)" and first.org == "Level Cinco"
    assert first.posted_date == "2026-09-22" and first.hints == ["student"]
    paid = next(o for o in items if "Comercial" in o.title)
    assert paid.pay == "R$900/mo" and paid.location.startswith("Cachoeirinha, RS, Brazil")


def test_quickin_rejects_odd_answer():
    with pytest.raises(ValueError):
        quickin.parse({"error": "not found"}, {"slug": "x"})


# --- Paraná Central de Estágios ------------------------------------------------------
def test_parana_reads_rows_and_detail():
    rows = parana.parse_list(fixture_text("parana_vagas.html"))
    assert len(rows) == 6 and rows[0]["code"] == "172876"  # the header row is skipped
    items = parana.parse(fixture_text("parana_vagas.html"), {"179111": fixture_text("parana_detalhe.html")})
    info = next(o for o in items if o.url.endswith("codoferta=179111"))
    assert info.title == "Estágio em Informática - Nucleo de Tecnologia da Informação"
    assert info.org == "UNIOESTE-DDH-PRO-REITORIA (Governo do Paraná)"
    assert info.location == "Cascavel, PR, Brazil"
    assert (info.posted_date, info.deadline) == ("2026-10-21", "2026-11-20")
    assert info.pay == "R$10/hr"
    assert "períodos 1-4" in info.description and "Montagem e manutenção" in info.description
    assert "@" not in info.description  # HR contacts are left out
    apply_rules(info)
    assert info.states == ["PR"]


# --- USP estágio murals --------------------------------------------------------------
def test_usp_mural_and_vacancy_page():
    board = usp_estagios.DEFAULT_BOARDS[0]
    items = usp_estagios.parse(fixture_text("fflch_mural.html"), {"/vagas/1559": fixture_text("fflch_vaga.html")}, board)
    assert len(items) == 5
    iri = next(o for o in items if o.url.endswith("/vagas/1559"))
    assert iri.title == "Estágio no Instituto de Relações Internacionais - USP"
    assert iri.deadline == "2026-10-30" and iri.pay == "R$1,081/mo"
    assert iri.location == "São Paulo, SP, Brazil" and iri.org == "FFLCH-USP"
    assert "Atendimento ao público" in iri.description and iri.hints == ["student"]
    tutor = next(o for o in items if o.url.endswith("/vagas/1534"))
    assert tutor.pay == "" and tutor.hints == ["unsure-student"]  # "R$ 35" for one weekly hour
