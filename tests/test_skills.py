"""Skill detection used by the résumé match on the website."""

from radar.labels import apply_rules
from radar.models import Opportunity
from radar.skills import NAMES, find_skills


def test_finds_common_skills_in_english() -> None:
    text = "You have experience with Python and C++, PyTorch or JAX, and Linux. Bonus: CUDA, ROS 2."
    assert find_skills(text) == ["Python", "C++", "PyTorch", "JAX", "CUDA", "Linux", "ROS"]


def test_finds_portuguese_skills() -> None:
    text = "Conhecimento em CLP, sistemas supervisórios, Excel e análise de dados. Desejável: visão computacional."
    found = find_skills(text)
    for name in ("PLC", "SCADA", "Excel", "Data analysis", "Computer vision"):
        assert name in found


def test_short_names_need_context() -> None:
    # "R$" is money, "R&D" is research, "go" is a verb, "rust" is corrosion.
    assert find_skills("Bolsa de R$ 1.800. R&D team. You will go to the office. Prevent rust.") == []
    assert "R" in find_skills("Experience in Python or R")
    assert "Go" in find_skills("We use Rust and Go")
    assert "C" in find_skills("Strong C/C++ skills")


def test_ordinary_words_are_not_skills() -> None:
    found = find_skills("You will excel at teamwork, react quickly to feedback, and present at the Cloud Summit.")
    assert found == []
    # Real sentences that used to match by mistake.
    assert find_skills("you'll spend 12 weeks embedded on a product team") == []
    assert find_skills("weekly stipend of 3,850 USD / 4,300 CAD + benefits. Canada: $120000 (CAD)") == []
    assert find_skills("experience with version control systems") == []
    assert find_skills("otimização de processos") == []
    assert find_skills("Experience with CAD tools such as SolidWorks") == ["CAD"]


def test_apply_rules_fills_skills() -> None:
    opp = Opportunity(title="Machine Learning Intern", org="Acme", source="greenhouse",
                      url="https://example.com/1", description="Python, PyTorch and SQL.")
    apply_rules(opp)
    assert opp.skills == ["Python", "SQL", "Machine learning", "PyTorch"]


def test_names_are_unique() -> None:
    assert len(NAMES) == len(set(NAMES))
