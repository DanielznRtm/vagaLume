"""Study levels (radar/levels.py) and Brazilian states (radar/places.py)."""

import pytest

from radar.labels import apply_rules
from radar.levels import find_levels
from radar.models import Opportunity
from radar.places import brazil_states


@pytest.mark.parametrize(
    "title, expected",
    [
        ("PhD Intern, Data Science (2027)", ["phd"]),
        ("2027 Summer Intern, MS/PhD, Machine Learning", ["masters", "phd"]),
        ("Student Researcher, BS/MS, Fall 2026", ["undergrad", "masters"]),
        ("Design Verification Intern - MS", ["masters"]),
        ("Analog Layout Intern - BS", ["undergrad"]),
        ("Business Analyst MBA Intern, 2027", ["masters"]),
        ("Quantitative Masters Intern - Investments", ["masters"]),
        ("Summer Undergrad 2027", ["undergrad"]),
        ("Estágio em Jurídica | Pós-graduação", ["masters"]),
        ("Estágio em Audiovisual - Graduação", ["undergrad"]),
        ("Bolsa de Iniciação Científica em Enfermagem", ["undergrad"]),
        ("Bolsa de Mestrado em Geofísica", ["masters"]),
        ("Bolsa de Doutorado Direto em Físico-Química", ["phd"]),
        # Not degrees:
        ("Area Manager Intern – Summer 2027 (TN, LA, OK, MS, AR)", []),
        ("Estágio MS Office", []),
        ("Master Data Intern", []),
        ("Scrum Master Intern", []),
        ("Digital IC Design Intern", []),
        ("Software Engineering Intern", []),
    ],
)
def test_levels_from_the_title(title, expected):
    assert find_levels(title) == expected


@pytest.mark.parametrize(
    "description, expected",
    [
        ("Requirements: Currently pursuing a Bachelor's or Master's degree in Computer Science.", ["undergrad", "masters"]),
        ("You are currently pursuing a PhD in statistics, mathematics or physics.", ["phd"]),
        ("Currently enrolled in an MBA program focused on operations.", ["masters"]),
        ("Requisitos: cursando graduação em Direito a partir do 5º semestre.", ["undergrad"]),
        ("Requisitos: cursando Engenharia Civil ou Arquitetura.", ["undergrad"]),  # a course name means graduação
        ("Requisitos: cursando mestrado em temática correlata.", ["masters"]),
        # Open to all three is the same as not saying.
        ("Currently pursuing a final year of Bachelor's, Master's, or Ph.D. degree.", []),
        # "PhD" outside an enrollment sentence says nothing about who can apply.
        ("Our team of PhD researchers builds models. Nice to have: experience with PyTorch.", []),
        ("", []),
    ],
)
def test_levels_from_the_enrollment_sentences(description, expected):
    assert find_levels("Software Engineering Intern", description) == expected


def test_title_wins_over_the_description():
    assert find_levels("PhD Research Intern", "Currently pursuing a Bachelor's degree.") == ["phd"]


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Ceilândia, DF, Brazil (on-site)", ["DF"]),
        ("Curitiba/PR", ["PR"]),
        ("Recife - PE", ["PE"]),
        ("Vitória, Espírito Santo, Brazil", ["ES"]),
        ("Campo Grande, Mato Grosso do Sul", ["MS"]),
        ("Sao Paulo, Sao Paulo, BRA", ["SP"]),
        ("São Paulo, Rio de Janeiro e Remoto", ["RJ", "SP"]),
        ("Belo Horizonte, MG; São Paulo, SP", ["MG", "SP"]),
        ("Brasília, Brazil", ["DF"]),
        # City names that contain a state's name:
        ("Ji-Paraná, Rondônia, Brazil (on-site)", ["RO"]),
        ("Paraíba do Sul, RJ, Brazil", ["RJ"]),
        ("Pará de Minas, MG", ["MG"]),
        # Can't tell:
        ("Brazil (remote)", []),
        ("2 Locations, Brazil", []),
        ("", []),
    ],
)
def test_brazilian_states(location, expected):
    assert brazil_states(location) == expected


def test_apply_rules_fills_levels_and_states_for_brazil_only():
    br = apply_rules(Opportunity(title="Estágio em Direito", org="X", source="gupy", url="https://x/1",
                                 location="Recife, PE, Brazil", description="Requisitos: cursando graduação em Direito."))
    assert br.levels == ["undergrad"] and br.states == ["PE"]
    us = apply_rules(Opportunity(title="PhD Intern", org="Y", source="greenhouse", url="https://y/1", location="Boston, MA"))
    assert us.levels == ["phd"] and us.states == []  # "MA" is Massachusetts here, not Maranhão


def test_a_source_can_preset_levels():
    opp = apply_rules(Opportunity(title="Bolsa em Química", org="FAPESP", source="fapesp", url="https://f/1",
                                  location="Campinas, SP, Brazil", preset={"levels": ["masters"]}))
    assert opp.levels == ["masters"]
