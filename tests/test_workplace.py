"""Remote, hybrid or on-site (radar/workplace.py)."""

import pytest

from radar.labels import apply_rules
from radar.models import Opportunity
from radar.workplace import find_workplaces


@pytest.mark.parametrize(
    "location, remote, expected",
    [
        ("São Paulo, São Paulo, Brazil (hybrid)", False, ["hybrid"]),
        ("Curitiba, PR, Brazil (on-site)", False, ["on-site"]),
        ("Brazil (remote)", True, ["remote"]),
        ("Home based - Worldwide", False, ["remote"]),
        ("New York City, NY (Hybrid); United States (Remote)", False, ["remote", "hybrid"]),
        ("Boston, MA", False, []),
    ],
)
def test_workplace_from_the_location(location, remote, expected):
    assert find_workplaces(location, remote) == expected


@pytest.mark.parametrize(
    "description, expected",
    [
        ("Modelo de trabalho: Híbrido, sendo 4 dias presenciais e 1 dia de home office por semana.", ["hybrid"]),
        ("Benefícios: VR, VT. Modelo híbrido (3x2) na unidade de Porto Alegre.", ["hybrid"]),
        ("Modalidade: Presencial. Tipo de contrato: Estágio.", ["on-site"]),
        ("Residir em João Pessoa - Vaga presencial.", ["on-site"]),
        ("Modalidade de trabalho: Presencial (primeiro mês), posteriormente 100% remoto.", ["hybrid"]),
        ("This role is hybrid, with an expectation of working in our New York office.", ["hybrid"]),
        ("Ability to work at least 1 day per week in our San Francisco office.", ["hybrid"]),
        ("Internship program: 12 weeks, full-time, in-person in the Berlin office.", ["on-site"]),
        # Not about this role:
        ("Trabalho 100% remoto, com possibilidade de migrar para híbrido a médio prazo.", ["remote"]),
        ("This is a fully remote role with the option to work hybrid near our offices.", ["remote"]),
        ("In-office perks: lunch, snacks, drinks.", ["remote"]),
    ],
)
def test_a_clear_sentence_in_the_description_wins(description, expected):
    assert find_workplaces("Brazil (remote)", True, description) == expected


def test_several_places_keep_their_own_workplaces():
    location = "New York City, NY (Hybrid); United States (Remote)"
    assert find_workplaces(location, False, "Some interns will work in a hybrid model.") == ["remote", "hybrid"]


def test_a_remote_role_that_is_really_hybrid_loses_the_remote_region():
    opp = apply_rules(Opportunity(title="Estagiário(a) de Direito", org="X", source="gupy", url="https://x/1",
                                  location="Porto Alegre, RS, Brazil (remote)", remote=True,
                                  description="Local: Porto Alegre/RS (modelo híbrido)."))
    assert opp.workplaces == ["hybrid"]
    assert opp.regions == ["Brazil"]
    assert opp.location == "Porto Alegre, RS, Brazil (hybrid)"


def test_a_remote_role_stays_remote():
    opp = apply_rules(Opportunity(title="Estágio em Dados", org="X", source="gupy", url="https://x/2",
                                  location="Brazil (remote)", remote=True, description="Trabalho 100% remoto."))
    assert opp.workplaces == ["remote"] and "remote" in opp.regions
