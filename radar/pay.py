"""Find the pay (salary, hourly wage, bolsa-auxílio) in a job description.

Postings write pay in many ways:

    "$54 — $60 USD"                         (Greenhouse pay-transparency box)
    "Austin, TX, USA - 109,395.00 USD Annually"     (Amazon)
    "US: $94000 - $125000 (USD) + 0% bonus target"  (Google)
    "Bolsa Auxílio: R$1.357,28/mês"                 (Gupy, Brazilian number format)
    "1,800 Swiss Francs per month"                  (program pages)

find_pay() returns one short label such as "$54–60/hr", "R$1,357/mo" or
"$94K–125K/yr", or "" when the text states no pay. It is deliberately
strict, because a wrong pay is worse than none:

- An amount counts when its sentence (or the heading right above it) has a
  clear pay word: salary, compensation, pay range, hourly rate, wage,
  salário, remuneração, bolsa.
- Weaker words (stipend, allowance, auxílio, "per month") only count outside
  perks: "a weekly lunch stipend of $75" or "auxílio transporte R$200" are
  benefits, not pay, and so is anything under a Benefits / Perks heading.
- Company figures never count ("$124 trillion of assets", "US$ 3 bilhões").
- The period (hour, week, month, year) comes from the words around the
  amount, before or after it. It is guessed from the size of the number only
  when the sentence is clearly about pay.
- Amounts outside believable ranges for their period are dropped.

Every case that went wrong once is in tests/fixtures/pay_cases.yaml, so it
can't come back.
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

# Clear pay words: one in the amount's sentence (or the heading above it) is enough.
STRONG_PAY = re.compile(
    r"\bpay\b|\bpaid\b|salary|salaries|compensation|\bwages?\b|hourly (?:rate|range|pay|wage)|pay rate|rate of pay|"
    r"base pay|remunera|sal[áa]rio|\bbolsa\b|(?-i:(?<=[a-zà-ú])(?:Bolsa|BOLSA))|valor d[oa] (?:est[áa]gio|bolsa)",
    re.I,
)
# Weaker words: they count only when nothing around says "perk".
WEAK_PAY = re.compile(
    r"stipend|allowance|hourly|per hour|/\s?hr|annually|monthly|per month|\bbase\b|aux[íi]lio|ganho|mensal|"
    r"por m[êe]s|/m[êe]s|\brange\b|\brate\b|pro rata|per year|a year|/\s?(?:yr|year)\b|per annum|💰",
    re.I,
)
# Perks and benefits: an amount next to these is not the pay (unless a clear pay word is right there too).
PERKS = re.compile(
    r"lunch|dinner|breakfast|meals?\b|snack|food|coffee|wellness|well-being|learning|education|tuition|internet|"
    r"phone|mobile plan|gym|fitness|commut|transport|equipment|home office|coworking|books?\b|conference|childcare|"
    r"relocat|housing|travel|per diem|gift|vale|refei[çc][ãa]o|alimenta[çc][ãa]o|plano de sa[úu]de|odonto|seguro|"
    r"gympass|totalpass|wellhub|day off|parental|pension|401|insurance|dental|vision|medical|(?-i:\bV[ART]\b)",
    re.I,
)
# Headings that open a benefits list: amounts below them need a clear pay word.
# (Headings are short lines: "Benefits:", "FULL-TIME EMPLOYEES ENJOY THESE PERKS:".)
PERKS_HEADING = re.compile(
    r"(?:^|\n)[^\n]{0,30}(?:perks|benefits|what we offer|we offer|o que oferecemos|benef[íi]cios|vantagens)[^\n]{0,30}(?:\n|:)",
    re.I,
)
PAY_HEADING = re.compile(
    r"(?:^|\n)[^\n]{0,30}(?:salary|compensation|pay range|pay\b|hourly rate|remunera|sal[áa]rio|bolsa)[^\n]{0,30}(?:\n|:)",
    re.I,
)
# ...and none of these right next to it (they are about the company).
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
    # A bare "year" or "ano" is too often something else ("final-year students", "Primeiro Ano").
    ("yr", re.compile(r"annual|annually|yearly|(?:per|a|an|each|/)\s?year\b|/\s?yr\b|(?:por|ao|/)\s?ano\b|anual", re.I)),
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


def _period(context: str, value: float, currency: str, guess: bool = True) -> str:
    """hr | wk | mo | yr from the words around the amount; "" if unsure and guess=False."""
    context = _WORK_HOURS.sub(" ", context)
    for name, pattern in PERIODS:
        if pattern.search(context):
            return name
    if currency == "R$":
        return "mo"  # Brazilian bolsas are monthly
    if not guess:
        return ""
    # No word for the period: guess from the size of the number.
    return "hr" if value < 300 else "mo" if value < 20000 else "yr"


# Believable pay for each period, in units of the currency (big currencies like ¥ and ₹ aren't checked).
_RANGES = {"hr": (5, 400), "wk": (80, 8000), "mo": (150, 60000), "yr": (4000, 1_500_000)}
_CHECKED = {"$", "R$", "€", "£", "CA$", "CHF ", "A$", "S$", "HK$"}


def _believable(amount: Amount) -> bool:
    if amount.currency not in _CHECKED:
        return True
    low, high = _RANGES[amount.period]
    return low <= amount.low and amount.high <= high * (8 if amount.currency == "HK$" else 1)


def _sentence(text: str, start: int, end: int) -> tuple[str, str, int]:
    """The sentence (or list line) around text[start:end], what comes right before it (the previous
    sentence and the last few non-empty lines, where headings like "COMPENSATION" or "Pay Range:"
    are), and where the sentence starts."""
    left = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start), text.rfind("; ", 0, start), start - 200, 0)
    right_candidates = [i for i in (text.find("\n", end), text.find(". ", end), text.find("; ", end)) if i != -1]
    right = min(right_candidates + [end + 120])
    above = [line for line in text[max(0, left - 600) : left].split("\n") if line.strip(" |\t\r")]
    return text[left:right], "\n".join(line[-160:] for line in above[-3:]), left


# Where one item of a list ends: "R$ 1.200,00 + Cursos", "Bolsa: R$1000 | Auxílio", "$5,800 in addition to".
# Gupy glues lines together ("R$ 1500,00AUXÍLIO TRANSPORTE", "por horaBenefícios"), so a capital
# right after a digit or a small letter starts a new item too.
_CLAUSE_BREAK = re.compile(r"[+|,;•·\n]|\. | in addition| as well as| plus |\band\b| e |[\U0001F300-\U0001FAFF]"
                           r"|(?<=[\da-zà-ú])(?=[A-ZÀ-Ú][a-zà-úA-ZÀ-Ú])")
# "R$ 1.600,00 (incluindo auxílio-transporte)": the perk is part of the pay, not instead of it.
_INCLUDED = re.compile(r"\(?\b(?:inclu[ií]\w*|including|includes|inclusive)\b[^)]*\)?", re.I)


def _in_perks_section(text: str, start: int) -> bool:
    """Is the amount under a Benefits / Perks heading (and not a later pay heading)?"""
    before = text[max(0, start - 1500) : start]
    perks = [m.end() for m in PERKS_HEADING.finditer(before)]
    pay = [m.end() for m in PAY_HEADING.finditer(before)]
    return bool(perks) and (not pay or perks[-1] > pay[-1])


def _in_pay_section(text: str, start: int) -> bool:
    """Is the amount in a list under a pay heading ("Pay Range:", "Remuneração")?"""
    before = text[max(0, start - 800) : start]
    perks = [m.end() for m in PERKS_HEADING.finditer(before)]
    pay = [m.end() for m in PAY_HEADING.finditer(before)]
    return bool(pay) and (not perks or pay[-1] >= perks[-1])


def _amounts(text: str) -> list[Amount]:
    found: list[Amount] = []
    for pattern in (_SYMBOL_FIRST, _NUMBER_FIRST):
        for match in pattern.finditer(text):
            end = match.start() + len(match.group(0).rstrip())  # the pattern may take a line break
            after = text[end : end + 40]
            sentence, heading, sentence_start = _sentence(text, match.start(), end)
            # Company figures right around the amount ("$3 billion in revenue").
            tight = f"{text[max(0, match.start() - 40):match.start()]} {match.group(0)} {after[:15]}"
            if NOT_PAY.search(tight):
                continue
            context = f"{heading}\n{sentence}"
            strong = bool(STRONG_PAY.search(context)) or _in_pay_section(text, match.start())
            # Perk words in this amount's own part of a list ("a weekly lunch stipend of $75",
            # "R$ 50,00 (auxílio transporte)", "+ R$ 500 VA/VR"), not in the next item
            # ("Bolsa: R$ 1.200,00 + Day off", "$5,800 in addition to company-paid housing").
            clause_before = _CLAUSE_BREAK.split(text[max(sentence_start, match.start() - 60) : match.start()])[-1]
            clause_after = _CLAUSE_BREAK.split(_INCLUDED.sub(" ", after))[0]
            near_text = f"{clause_before} {clause_after}"
            near_perk = bool(PERKS.search(near_text))
            perk = near_perk or _in_perks_section(text, match.start())
            # A clear pay word wins, unless a perk is named right next to the amount and
            # no clear pay word is ("a weekly lunch stipend of $75").
            if strong and near_perk and not STRONG_PAY.search(near_text):
                strong = False
            if not strong and (perk or not WEAK_PAY.search(context)):
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
            # The period: first right after the amount ("$54/hr", "per month"), then in its sentence
            # ("weekly ... $75"); a guess from the size only when the sentence is clearly about pay.
            # Right after the amount ("/mês", " per hour", " USD Annually"), up to a bracket or line end,
            # so "R$ 900 (a partir do 2º ano...)" is not read as per year.
            right_after = re.split(r"[(\n,;|•]|(?<=[\da-zà-ú])(?=[A-ZÀ-Ú])", _WORK_HOURS.sub(" ", after), maxsplit=1)[0][:22]
            period = (_period(f"{match.group(0)} {right_after}", low, currency, guess=False)
                      or _period(clause_before, low, currency, guess=False)
                      or _period(heading.split("\n")[-1] if heading else "", low, currency, guess=False)
                      # "💰 £42,500 pro rata": a figure that big is a yearly salary.
                      or _period("", low, currency, guess=strong or (not perk and low >= 20000)))
            if not period:
                continue
            amount = Amount(currency, low, high, period)
            if _believable(amount):
                found.append(amount)
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
