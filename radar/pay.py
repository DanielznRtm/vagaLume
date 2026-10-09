"""Find the pay (salary, hourly wage, bolsa-auxílio) in a job description.

Postings write pay in many ways:

    "$54 — $60 USD"                         (Greenhouse pay-transparency box)
    "Austin, TX, USA - 109,395.00 USD Annually"     (Amazon)
    "US: $94000 - $125000 (USD) + 0% bonus target"  (Google)
    "Bolsa Auxílio: R$1.357,28/mês"                 (Gupy, Brazilian number format)
    "1,800 Swiss Francs per month"                  (program pages)

find_pay() returns one short label such as "$54–60/hr", "R$1,357/mo" or
"$94K–125K/yr", or "" when the text states no pay. It is deliberately
strict: an amount only counts when the text around it talks about pay,
so "$124 trillion of assets" or "US$ 3 bilhões" are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Currency as written -> symbol we show.
CURRENCIES = {
    "R$": "R$", "BRL": "R$", "US$": "$", "USD": "$", "$": "$", "CA$": "CA$", "CAD": "CA$",
    "€": "€", "EUR": "€", "£": "£", "GBP": "£", "CHF": "CHF ", "SWISS FRANCS": "CHF ",
    "SGD": "S$", "S$": "S$", "HK$": "HK$", "HKD": "HK$", "A$": "A$", "AUD": "A$",
    "INR": "₹", "₹": "₹", "JPY": "¥", "¥": "¥", "PLN": "PLN ", "AED": "AED ",
}
_CUR = r"(?:R\$|US\$|CA\$|HK\$|S\$|A\$|\$|€|£|₹|¥|BRL|USD|CAD|EUR|GBP|CHF|SGD|HKD|AUD|INR|JPY|PLN|AED)"
_NUM = r"(?:\d[\d.,]*\d|\d)\s?[kK]?"  # never ends in "." or "," (sentence punctuation)
_DASH = r"\s*(?:-|–|—|to|a|até)\s*"

# "$54 — $60 USD", "R$ 1.357,28", "€1,800 - 2,000"
_SYMBOL_FIRST = re.compile(
    rf"(?P<cur>{_CUR})\s?(?P<low>{_NUM})(?:{_DASH}(?:{_CUR})?\s?(?P<high>{_NUM}))?(?:\s*\(?(?P<cur2>USD|EUR|GBP|BRL|CAD|CHF)\)?)?"
)
# "109,395.00 USD Annually", "1,800 Swiss Francs per month"
_NUMBER_FIRST = re.compile(
    rf"(?P<low>{_NUM})(?:{_DASH}(?P<high>{_NUM}))?\s?(?P<cur>USD|EUR|GBP|BRL|CAD|CHF|SGD|HKD|AUD|INR|JPY|PLN|AED|Swiss Francs|reais)\b",
    re.I,
)

# Words that must appear near an amount for it to count as pay.
PAY_WORDS = re.compile(
    r"pay|salary|salaries|compensation|wage|stipend|allowance|hourly|per hour|/\s?hr|annually|monthly|"
    r"per month|base|remunera|sal[áa]rio|bolsa|aux[íi]lio|ganho|mensal|por m[êe]s|/m[êe]s|range",
    re.I,
)
# ...and none of these (they are about the company, perks or relocation).
NOT_PAY = re.compile(
    r"billion|million|trillion|bilh|milh|revenue|valuation|raised|funding|assets|customers|relocat|"
    r"sign[- ]on|signing|bonus target is|tuition|housing|travel|401|donat|equity grant|capital|"
    r"budget|reimburs|wellness|gym|meal|commut|vale|transporte|refei[çc][ãa]o|alimenta[çc][ãa]o|home office|"
    r"se h[íi]brido|presencial\)",
    re.I,
)
PERIODS = [
    ("hr", re.compile(r"hour|hourly|/\s?hr\b|/\s?h\b|por hora", re.I)),
    ("wk", re.compile(r"\bweek|weekly|semana", re.I)),
    ("mo", re.compile(r"month|monthly|/\s?mo\b|m[êe]s|mensal", re.I)),
    ("yr", re.compile(r"annual|annually|year|yearly|/\s?yr\b|\bano\b|anual", re.I)),
]


@dataclass
class Amount:
    currency: str  # symbol to show, e.g. "$"
    low: float
    high: float
    period: str  # hr | wk | mo | yr


def parse_number(text: str) -> float | None:
    """'1.357,28' (Brazil) and '1,357.28' (US) -> 1357.28; '125K' -> 125000."""
    text = text.strip().replace(" ", "")
    multiplier = 1000 if text[-1:] in "kK" else 1
    text = text.rstrip("kK")
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
    elif "," in text:
        decimal = "," if re.search(r",\d{2}$", text) else None  # "1108,50" vs "109,395"
    elif "." in text:
        decimal = None if re.search(r"\.\d{3}$", text) else "."  # "2.000" vs "51.50"
    else:
        decimal = None
    thousands = {",": ".", ".": ","}.get(decimal or "", ",.")
    for mark in thousands:
        text = text.replace(mark, "")
    if decimal:
        text = text.replace(decimal, ".")
    try:
        return float(text) * multiplier
    except ValueError:
        return None


# "30 horas semanais", "40 hours per week" describe working hours, not the pay period.
_WORK_HOURS = re.compile(r"\d+\s*(?:h|hrs?|horas?|hours?)\s*(?:semanais|por semana|/\s?semana|per week|/\s?week|a week|weekly)", re.I)


def _period(context: str, value: float, currency: str) -> str:
    context = _WORK_HOURS.sub(" ", context)
    for name, pattern in PERIODS:
        if pattern.search(context):
            return name
    if currency == "R$":
        return "mo"  # Brazilian bolsas are monthly
    # No word for the period: guess from the size of the number.
    return "hr" if value < 300 else "mo" if value < 20000 else "yr"


def _amounts(text: str) -> list[Amount]:
    found: list[Amount] = []
    for pattern in (_SYMBOL_FIRST, _NUMBER_FIRST):
        for match in pattern.finditer(text):
            before = text[max(0, match.start() - 120) : match.start()]
            after = text[match.end() : match.end() + 40]
            near = f"{before} {match.group(0)} {after}"
            # The words right around the amount must not be about perks or the company.
            tight = f"{text[max(0, match.start() - 40):match.start()]} {match.group(0)} {after[:15]}"
            if not PAY_WORDS.search(near) or NOT_PAY.search(tight):
                continue
            low = parse_number(match.group("low"))
            high = parse_number(match.group("high")) if match.group("high") else low
            if not low or not high or low < 1:
                continue
            currency = CURRENCIES.get(match.group("cur").upper(), CURRENCIES.get(match.group("cur"), ""))
            if match.groupdict().get("cur2"):
                currency = CURRENCIES.get(match.group("cur2").upper(), currency)
            if not currency:
                continue
            low, high = min(low, high), max(low, high)
            found.append(Amount(currency, low, high, _period(f"{match.group(0)} {after}", low, currency)))
    return found


def _fmt(value: float, period: str) -> str:
    if period == "yr" or value >= 20000:
        return f"{value / 1000:.0f}K"
    if value >= 1000:
        return f"{value:,.0f}"
    return f"{value:.0f}" if value == int(value) else f"{value:.2f}"  # "$54", "$51.50"


def format_amount(amount: Amount) -> str:
    low, high = _fmt(amount.low, amount.period), _fmt(amount.high, amount.period)
    span = low if low == high else f"{low}–{high}"
    return f"{amount.currency}{span}/{amount.period}"


def find_pay(text: str) -> str:
    """Short pay label for a description, or "" if none is stated."""
    if not text:
        return ""
    amounts = _amounts(text)
    if not amounts:
        return ""
    # Several ranges (e.g. one per city): merge those in the first currency
    # and period into one overall range. Amounts far from the first one are
    # probably something else (a meal allowance), so they are left out.
    first = amounts[0]
    same = [
        a for a in amounts
        if a.currency == first.currency and a.period == first.period and first.low / 2.5 <= a.low <= first.high * 2.5
    ]
    merged = Amount(first.currency, min(a.low for a in same), max(a.high for a in same), first.period)
    return format_amount(merged)


def from_range(low: float | None, high: float | None, currency: str, period: str) -> str:
    """Build a label from structured fields (Lever salaryRange, Jane Street metadata)."""
    if not low and not high:
        return ""
    low = low or high
    high = high or low
    symbol = CURRENCIES.get((currency or "USD").upper(), (currency or "") + " ")
    if not period:
        period = _period("", float(low), symbol)  # type: ignore[arg-type]
    return format_amount(Amount(symbol, float(low), float(high), period))  # type: ignore[arg-type]
