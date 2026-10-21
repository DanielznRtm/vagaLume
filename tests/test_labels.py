"""Keyword rules. These never drop anything; they only describe."""

import pytest

from radar.labels import apply_rules, calendar_note, classify_area, classify_regions, classify_season, student_level
from radar.models import Opportunity, make_id, strip_tracking
from radar.textutil import find_deadline, iso_date


@pytest.mark.parametrize(
    "title, level",
    [
        ("Software Engineer Intern", "yes"),
        ("Estágio em Engenharia de Dados", "yes"),
        ("Estagiário de Automação", "yes"),
        ("AI Residency 2027", "yes"),
        ("Explore Microsoft Program", "yes"),
        ("Summer Analyst", "yes"),
        ("Graduate Rotational Program", "unsure"),
        ("Machine Learning Summer School", "yes"),
        ("Technical Program Manager", "no"),  # a job title, not a program
        ("Senior Manager, Fellows Program", "no"),
        ("Member of Technical Staff (New Grad)", "unsure"),
        ("Staff Software Engineer", "no"),
        ("Accounting Coordinator", "no"),
        # Europe and Latin America (Airbus, Thales, ZEISS, CERN...)
        ("STAGE 2027 - Acoustic Testing : Développement", "yes"),
        ("Stagiaire Data Scientist (F/H)", "yes"),
        ("Ingénieur Data H/F - Stage", "yes"),
        ("Alternance - Chargé de projet", "yes"),
        ("Praktikant Software (m/w/d)", "yes"),
        ("Masterarbeit Batteriemodellierung (m/w/d)", "yes"),
        ("Becario/a de Ingeniería", "yes"),
        ("Practicante de TI", "yes"),
        ("Technical Studentship 2027-1", "yes"),
        ("12 Month Industrial Placement - Engineering", "yes"),
        ("Stage Integration Engineer", "no"),  # a rocket stage, not a French internship
        ("Principal Stage Fluids Engineer", "no"),
        ("Stage Manager", "no"),
    ],
)
def test_student_level(title, level):
    assert student_level(title) == level


@pytest.mark.parametrize(
    "title, area",
    [
        ("Machine Learning Research Intern", "ML"),
        ("Quantitative Researcher Intern", "quant"),
        ("Research Scientist Intern, Robotics", "research"),
        ("Data Scientist Intern", "data"),
        ("Estágio em Automação Industrial", "hardware"),
        ("Software Engineer Intern", "SWE"),
        ("Legal Intern", "other"),
    ],
)
def test_area(title, area):
    assert classify_area(title) == area


@pytest.mark.parametrize(
    "title, season",
    [
        ("Software Engineer Intern, Summer 2027", "May–Aug"),
        ("Estágio de Férias - Verão 2027", "Dec–Feb"),
        ("Software Engineer Co-op (Fall 2026)", "Sep–Dec"),
        ("Software Engineer Intern (Winter 2027)", "Jan–Apr"),
        ("Estágio em Dados", "year-round"),
        ("Research Intern", "unknown"),
    ],
)
def test_season(title, season):
    assert classify_season(title) == season


def test_spring_framework_is_not_a_season():
    assert classify_season("Software Intern", "Experience with Java Spring Boot") == "unknown"


@pytest.mark.parametrize(
    "location, regions",
    [
        ("São Paulo, SP", ["Brazil"]),
        ("Florianópolis, SC", ["Brazil"]),  # SC here is Santa Catarina, not South Carolina
        ("Boise, ID", ["US/Canada"]),
        ("Berlin, DE", ["Europe"]),
        ("Remote in USA", ["US/Canada", "remote"]),
        ("London / New York, NY", ["US/Canada", "Europe"]),
        ("Cape Town, ZAF", ["Asia/ME"]),  # Africa is shown with Asia and the Middle East
        ("Belfort", ["Europe"]),  # Workday sites abroad often give just the city
        ("Bursa, , Turkey", ["Europe"]),
        ("Managua", ["LatAm"]),
        ("Makati", ["Asia/ME"]),
        ("Lebanon, PA", ["US/Canada"]),  # a US town, not the country
        ("Singapore", ["Asia/ME"]),
        ("Ciudad de México, MEX", ["LatAm"]),
        ("Porto Alegre, RS", ["Brazil"]),  # not Porto, Portugal
    ],
)
def test_regions(location, regions):
    assert classify_regions(location) == regions


def test_warnings_and_calendar():
    opp = Opportunity(
        title="Research Intern, PhD, Summer 2027",
        org="X",
        source="test",
        url="https://example.com/1",
        location="Mountain View, CA",
        description="You must be authorized to work in the US. Expected graduation date between 2027 and 2028.",
    )
    apply_rules(opp)
    assert opp.warnings == ["US work auth?", "PhD-level?", "grad-year limit?"]
    assert opp.season == "May–Aug"
    assert "clashes" in opp.calendar_note or "overlaps" in opp.calendar_note


@pytest.mark.parametrize(
    "location, description, us_auth",
    [
        # Google, Student Researcher in Europe: "work authorization" here is the local one.
        ("Zürich, Switzerland / London, UK", "Individuals applying for this position must hold valid work authorization "
         "or meet local immigration eligibility requirements for their specific work location.", False),
        ("São Paulo, Brazil", "Não oferecemos visa sponsorship.", False),
        ("New York, NY", "", True),  # a US role always gets it
        ("Remote", "Candidates must be authorized to work without sponsorship.", True),  # remote: probably the US
        ("", "Must be authorized to work.", True),  # place unknown
        ("London, UK", "This role requires U.S. citizenship and security clearance.", True),  # US-only wording
    ],
)
def test_us_work_authorization_warning(location, description, us_auth):
    opp = apply_rules(Opportunity(title="Software Engineering Intern", org="X", source="test", url="https://e.com/1",
                                  location=location, description=description))
    assert ("US work auth?" in opp.warnings) == us_auth


def test_unsure_roles_are_labelled_not_dropped():
    opp = apply_rules(Opportunity(title="Applied AI Rotational Program", org="X", source="t", url="https://e.com/2"))
    assert "unsure if student role" in opp.warnings


def test_calendar_notes_cover_all_seasons():
    for season in ("Dec–Feb", "Jul", "May–Aug", "Jan–Apr", "Sep–Dec", "year-round", "unknown"):
        assert calendar_note(season)


def test_ids_ignore_tracking_parameters():
    assert make_id("https://a.com/job/1?utm_source=Simplify&ref=Simplify") == make_id("https://a.com/job/1")
    assert strip_tracking("https://a.com/j?id=3&utm_source=x") == "https://a.com/j?id=3"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Please complete your application before October 9, 2026.", "2026-10-09"),
        ("Application deadline: 15 December 2026", "2026-12-15"),
        ("Inscrições até 30/11/2026", "2026-11-30"),
        ("We hire on a rolling basis.", ""),
    ],
)
def test_find_deadline(text, expected):
    assert find_deadline(text) == expected


def test_iso_date_formats():
    assert iso_date("2026-10-02T17:56:27.042Z") == "2026-10-02"
    assert iso_date(1786469891368) == "2026-08-11"  # milliseconds
    assert iso_date("September 15, 2026") == "2026-09-15"
    assert iso_date(None) == ""


@pytest.mark.parametrize(
    "title, description, expected",
    [
        # Portuguese ads: generic words in the description no longer decide the area.
        ("Estágio em Administrativa", "Rotinas administrativas, controle de quantidade de materiais e sistemas internos.", "other"),
        ("Estágio em Vendas", "Desenvolvimento profissional, uso de sistemas e tecnologia.", "other"),
        ("Estagiário Jurídico", "Apoio em segurança da informação e dados de clientes.", "other"),
        ("Estágio em Engenharia Civil", "Levantamento de quantitativos de obra.", "other"),  # not quant
        ("Estagiário Analista Financeiro", "", "other"),  # "analista" alone isn't data for a business role
        # ...but clear signals still count.
        ("Estágio em TI", "Desenvolvimento de software em Python e SQL.", "SWE"),
        ("Estágio", "Atuar com ciência de dados e machine learning.", "ML"),
        ("Estágio em Engenharia Elétrica", "Projetos de automação industrial com CLP.", "hardware"),
        ("Estagiário de Dados", "", "data"),
        # English titles keep working.
        ("Quantitative Research Intern", "", "quant"),
        ("Trading Intern - Summer 2027", "", "quant"),
        ("Research Intern, Inference", "", "research"),
        ("Machine Learning Intern", "", "ML"),
        ("Legal Intern - Summer 2027", "Our trading desks and quantitative teams...", "other"),
    ],
)
def test_classify_area_with_fields(title, description, expected):
    from radar.fields import find_fields
    from radar.labels import classify_area
    assert classify_area(title, description, find_fields(title, description)) == expected


def test_tech_roles_without_a_field_get_the_fields_of_their_area():
    """Stress test: "Applied Scientist Intern" named no field, so a law student saw it as a good fit."""
    opp = apply_rules(Opportunity(title="Applied Scientist Intern", org="Upstart", source="t", url="https://e.com/a"))
    assert opp.area == "ML" and "direito" not in opp.fields and "computacao" in opp.fields
    law = apply_rules(Opportunity(title="Estágio em Direito Tributário", org="X", source="t", url="https://e.com/b"))
    assert "direito" in law.fields and "computacao" not in law.fields


@pytest.mark.parametrize(
    "title, over",
    [
        ("Software Engineer Intern (Winter 2026)", True),  # Jan–Apr 2026, over by October
        ("Intern - Spring 2026", True),
        ("Summer 2026 Intern", True),
        ("Summer '25 Intern", True),
        ("Estágio 2025", True),
        ("Software Engineer Intern (Winter 2027)", False),
        ("Fall 2026 Co-op", False),  # until December
        ("Programa de Estágio 2026", False),  # the year alone: still this year
        ("Summer Analyst", False),
    ],
)
def test_past_term(title, over):
    from datetime import date

    from radar.labels import past_term

    assert past_term(title, date(2026, 10, 16)) == over


@pytest.mark.parametrize(
    "title, subs",
    [
        ("Estágio em Direito Tributário", ["tributario"]),
        ("Estagiário(a) Contencioso Cível Estratégico", ["contencioso"]),
        ("Estagiário Engenharia (Elétrica, Mecânica ou Civil)", ["mecanica", "eletrica", "civil"]),
        ("Estágio em Enfermagem", ["enfermagem"]),
        ("(PP) Estagiário(a) Ensino Superior (Farmácia) - CURITIBA - PR", ["farmacia"]),
        ("Software Engineer Intern", []),  # tech roles keep their own areas (SWE)
    ],
)
def test_subareas(title, subs):
    from radar.subareas import find_subareas

    assert find_subareas(title) == subs


def test_word_lists_are_compiled_once_and_match_like_one_search_per_word():
    from radar.labels import _WORD_RES, _any, _mentions
    assert _any([r"intern", r"est[áa]gio"], "Estágio em Dados") and not _any([r"intern"], "International Sales")
    assert _any([r"ab|cd"], "xcd")  # each word keeps its own \b...\b, as before: \bab|cd\b
    assert not _any([], "anything")
    assert _mentions([r"singapore", r"SGP"], "SGP-Singapore") and not _mentions([r"SGP"], "sgp")
    roles = [("Software Engineer Intern", "London, UK"), ("Estágio Jurídico", "São Paulo - SP")]
    for title, place in roles:
        apply_rules(Opportunity(title=title, org="X", source="gupy", url=title, location=place))
    warmed = len(_WORD_RES)
    for title, place in roles:
        apply_rules(Opportunity(title=title + " 2027", org="Y", source="gupy", url=title + "2", location=place))
    assert len(_WORD_RES) == warmed  # no new regex per role


@pytest.mark.parametrize("title, place, season", [
    ("Summer Job | Data & Analytics", "Barueri, SP, Brazil", "Dec–Feb"),  # Equifax: the Brazilian summer
    ("Programa Summer Undergrad 2027", "São Paulo, SP, Brazil", "Dec–Feb"),
    ("Summer Internship", "Buenos Aires, Argentina", "Dec–Feb"),
    ("Summer Analyst", "New York, NY", "May–Aug"),
    ("Summer Internship (June-August)", "São Paulo, Brazil", "May–Aug"),  # says northern months
    ("Summer Intern", "São Paulo, Brazil / London, UK", "May–Aug"),  # also in the north
])
def test_summer_in_the_south_is_december_to_february(title, place, season):
    assert apply_rules(Opportunity(title=title, org="X", source="workday", url=title + place, location=place)).season == season


@pytest.mark.parametrize("location, regions", [
    ("Madrid, MD, Spain", ["Europe"]),  # MD is a Spanish region here, not Maryland
    ("Vargarda, SE, Sweden", ["Europe"]),  # not Sergipe
    ("Porto Velho, RO, Brazil", ["Brazil"]),  # not Portugal
    ("US, New Mexico, Albuquerque", ["US/Canada"]),
    ("Mexico City, Distrito Federal, Mexico", ["LatAm"]),
    ("San Salvador, , El Salvador", ["LatAm"]),
    ("Vienna, VA", ["US/Canada"]),
    ("Melbourne, FL", ["US/Canada"]),
    ("US-IA-CEDAR RAPIDS-182 ~ 1100 Cimmie Ave Ne ~ BLDG 182", ["US/Canada"]),
    ("PL-18-RZESZOW", ["Europe"]),
    ("Prague, Czechia", ["Europe"]),
    ("Remote (US)", ["US/Canada", "remote"]),
    ("London, Montreal, Singapore", ["US/Canada", "Europe", "Asia/ME"]),  # a list of cities
    ("Costa Rica, San Jose", ["LatAm"]),
])
def test_the_country_a_place_names_wins(location, regions):
    assert classify_regions(location) == regions
