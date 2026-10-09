"""Fields of study a posting is aimed at (used to hide other fields' roles)."""

import pytest

from radar.fields import NAMES, find_fields
from radar.labels import apply_rules
from radar.models import Opportunity


@pytest.mark.parametrize("title, expected", [
    ("Estágio em Engenharia de Produção", ["engenharia"]),
    ("ESTÁGIO | ENGENHARIAS - Presidente Prudente/SP", ["engenharia"]),
    ("Software Engineering Intern", ["engenharia", "computacao"]),
    ("Machine Learning Intern", ["computacao"]),
    ("Estagiário Arquitetura Enterprise", ["computacao"]),  # software architecture, not buildings
    ("Estágio em Arquitetura e Urbanismo", ["arquitetura"]),
    ("Estágio de Enfermagem", ["saude"]),
    ("Estágio Jurídico", ["direito"]),
    ("Estágio em Administração ou Direito", ["negocios", "direito"]),
    ("Quantitative Researcher Intern", ["exatas"]),
    ("Estágio em Marketing Digital", ["comunicacao"]),
    ("Research Intern", []),  # says nothing about the field
    ("Estágio em Educação Física", ["saude"]),  # not physics, not education
    ("Robotics Engineer Intern - Model Based Design", ["engenharia"]),  # engineering design, not graphic design
    ("Estágio em Design Gráfico", ["comunicacao"]),
    ("Estágio em Informatica", ["computacao"]),
    ("Estagiário(a) de Natação", ["saude"]),
])
def test_fields_from_the_title(title, expected):
    assert find_fields(title) == expected


def test_generic_title_uses_the_course_phrase_not_the_company_blurb():
    description = "Somos uma empresa de tecnologia e dados. Requisitos: cursando Administração ou Economia."
    assert find_fields("Estagiário(a)", description) == ["negocios"]
    assert find_fields("Estagiário(a)", "Empresa de tecnologia e dados.") == []
    # Only the sentence with the courses counts, not the activities after it.
    assert find_fields("Estágio em Gastronomia", "Área: Gastronomia. Atividades: manutenção da cozinha.") == ["humanas"]


def test_apply_rules_fills_fields():
    opp = apply_rules(Opportunity(title="Estagiário(a)", org="X", source="gupy", url="https://x.gupy.io/job/1",
                                  description="Cursando Direito a partir do 5º semestre."))
    assert opp.fields == ["direito"]


def test_every_field_has_a_name_on_the_site():
    page = open("docs/index.html", encoding="utf-8").read()
    for name in NAMES:
        assert f'"field.{name}"' in page
