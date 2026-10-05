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
        ("Software Engineer Co-op (Fall 2026)", "year-round"),
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
        ("Cape Town, ZAF", ["unknown"]),
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


def test_unsure_roles_are_labelled_not_dropped():
    opp = apply_rules(Opportunity(title="Applied AI Rotational Program", org="X", source="t", url="https://e.com/2"))
    assert "unsure if student role" in opp.warnings


def test_calendar_notes_cover_all_seasons():
    for season in ("Dec–Feb", "Jul", "May–Aug", "year-round", "unknown"):
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
