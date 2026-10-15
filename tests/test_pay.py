"""Pay extraction. The phrasings are copied from real postings."""

from pathlib import Path

import pytest
import yaml

from radar import db
from radar.pay import find_pay, from_range, parse_number
from radar.sources import ashby, lever


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Zone 1 pay range\n$54 — $60 USD", "$54–60/hr"),  # Greenhouse
        ("The base pay range is $54 — $60 USD per hour. Other locations: $51.50 — $60 USD", "$51.50–60/hr"),
        ("Pay: Austin, TX, USA - 109,395.00 USD Annually\nEast Palo Alto, CA, USA - 125,885.00 USD Annually", "$109K–126K/yr"),  # Amazon
        ("The US base salary range for this position is US: $94000 - $125000 (USD) + 0% bonus target", "$94K–125K/yr"),  # Google
        ("Milan, ITA - 1,800.00 EUR Monthly", "€1,800/mo"),
        ("Bolsa Auxílio: R$1.357,28/mês;", "R$1,357/mo"),  # Gupy, Brazilian format
        ("Bolsa de R$2.471,97, e após 90 dias o valor é reajustado para R$2.707,80", "R$2,472–2,708/mo"),
        ("Students receive a monthly living allowance of 1,800 Swiss Francs", "CHF 1,800/mo"),
        ("Compensation: $8,000/month", "$8,000/mo"),
        ("Bolsa Auxílio: R$1.357,28/mês; Auxílio home office: R$\n200,00 (se híbrido ou presencial);", "R$1,357/mo"),
    ],
)
def test_find_pay(text, expected):
    assert find_pay(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "An estimated $124 trillion of assets will be inherited by younger generations",
        "o Grupo Messer, que hoje representa um empreendimento global de US$ 3 bilhões",
        "We offer a $5,000 relocation stipend.",
        "Personal learning and development budget of USD 2,000 per year.",
        "Internship of 40 hours per week starting in 2027.",
        "",
    ],
)
def test_amounts_that_are_not_pay(text):
    assert find_pay(text) == ""


@pytest.mark.parametrize("raw, value", [("1.357,28", 1357.28), ("109,395.00", 109395), ("2.000", 2000), ("51.50", 51.5), ("125K", 125000), ("1108,50", 1108.5)])
def test_parse_number(raw, value):
    assert parse_number(raw) == pytest.approx(value)


def test_structured_pay_fields():
    assert from_range(300000, 300000, "USD", "") == "$300K/yr"  # Jane Street metadata
    assert lever._pay({"salaryRange": {"min": 45, "max": 50, "currency": "USD", "interval": "per-hour-wage"}}) == "$45–50/hr"
    assert lever._pay({}) == ""
    job = {"compensation": {"compensationTierSummary": "$50/hr • Offers Equity"}}
    assert ashby._pay(job) == "$50/hr"


def test_old_database_gets_pay_column(tmp_path):
    path = tmp_path / "old.db"
    conn = db.connect(path)
    conn.execute("ALTER TABLE opportunities DROP COLUMN pay")
    conn.commit()
    conn.close()
    conn = db.connect(path)  # reopening adds it back
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(opportunities)")}
    assert "pay" in columns


def test_weekly_hours_are_not_the_pay_period():
    assert find_pay("Bolsa-auxílio de R$ 1.870,00, 30 horas semanais, por até 2 anos.") == "R$1,870/mo"
    assert find_pay("Stipend: $2,500 per month, 40 hours per week.") == "$2,500/mo"


def _cases():
    path = Path(__file__).parent / "fixtures" / "pay_cases.yaml"
    return [pytest.param(case["text"], case["pay"], id=f"case{i + 1}") for i, case in enumerate(yaml.safe_load(path.read_text()))]


@pytest.mark.parametrize("text, expected", _cases())
def test_real_cases(text, expected):
    """tests/fixtures/pay_cases.yaml: every reported mistake stays fixed."""
    assert find_pay(text) == expected


def test_the_site_marks_pay_read_from_the_text(tmp_path):
    """Pay from a salary field is shown as is; pay read from the description gets a "check the posting" mark."""
    from radar.labels import apply_rules
    from radar.models import Opportunity
    from radar.site import item_record

    field = apply_rules(Opportunity(title="Estágio", org="A", source="solides", url="https://a/1", pay="R$1,500/mo"))
    text = apply_rules(Opportunity(title="Estágio", org="B", source="gupy", url="https://b/2", description="Bolsa auxílio: R$ 1.800,00"))
    assert (field.pay, field.pay_from) == ("R$1,500/mo", "field")
    assert (text.pay, text.pay_from) == ("R$1,800/mo", "text")
    conn = db.connect(tmp_path / "radar.db")
    for opp in (field, text):
        db.upsert(conn, opp, "2026-10-15")
    records = {r.org: item_record(r) for r in db.load_all(conn)}
    assert "pay_text" not in records["A"]
    assert records["B"]["pay_text"] == 1
