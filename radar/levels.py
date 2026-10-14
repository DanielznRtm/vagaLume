"""Which study levels a posting is for: undergrad, masters, phd.

The website hides roles meant only for other levels (a PhD internship for an
undergraduate, an undergrad-only estágio for a master's student); one click
shows them again. Roles that don't say are shown to everyone, and so are
roles open to all three levels.

The title decides when it names a level ("PhD Intern", "BS/MS",
"Bolsa de Mestrado", "Estágio | Pós-graduação"). Otherwise we read the
description's enrollment sentences only ("currently pursuing a Bachelor's or
Master's degree", "cursando graduação em Direito"), not the whole text,
because "PhD" also shows up in team descriptions and "nice to have" lists.
"""

from __future__ import annotations

import re
import unicodedata

LEVELS = ("undergrad", "masters", "phd")

# B.S./M.S. in capitals as a token of their own ("BS/MS", "Intern - MS", "(M.Sc.)"),
# but not in a list of US states ("(TN, LA, OK, MS, AR)" is Mississippi).
_DEGREE_TOKEN = (r"(?<![\w-])(?<![A-Z]{2}, )", r"(?=[\s/,)\-]|$)(?!, [A-Z]{2}\b)")

# Titles, accents removed.
_TITLE = {
    "undergrad": re.compile(
        r"(?i:undergrad|bachelor|iniciacao cientifica|graduand|(?<!pos-)(?<!pos )\bgraduacao\b)|" + "B\\.?Sc?\\.?".join(_DEGREE_TOKEN)
    ),
    "masters": re.compile(
        r"(?i:(?<!scrum )\bmasters?\b(?!\s*(?:data|card|plan|schedul|black))|\bmaster's|masterand|mestrad|mestrand|\bmba\b|pos-?graduacao|pos graduacao)"
        r"|" + "M\\.?Sc?\\.?".join(_DEGREE_TOKEN) + r"(?!\s+(?:Office|Excel|Word|Teams|Project|Access|SQL|Dynamics|Azure|Windows))"
    ),
    "phd": re.compile(r"(?i:ph\.? ?d|doctora|doutorad|doutorand)"),
}

# Sentences that say who can apply, in lower case without accents.
_ENROLLMENT = re.compile(
    r"(?:pursuing|enrolled|currently|working towards|candidates? for|students? (?:in|of|pursuing)"
    r"|cursando|matriculad[oa]s?|estudantes? de|alunos? de)[^.\n;]{0,220}"
)
_DEGREES = {
    "undergrad": re.compile(
        r"bachelor|undergrad|\bb\.?sc?\b|(?<!pos-)(?<!pos )\bgraduacao|ensino superior|curso superior|nivel superior|tecnologo"
    ),
    "masters": re.compile(r"master|\bm\.?sc?\b|\bmba\b|mestrado|pos-?graduacao|pos graduacao|especializacao"),
    "phd": re.compile(r"ph\.? ?d|doctor|doutorado"),
}
_ABBREVIATED = re.compile(r"\b(?:ph\. ?d|[bm]\.(?:sc|s|a))\.?")
# "cursando Engenharia" means an undergraduate course unless it names a graduate one.
_CURSANDO = re.compile(r"cursando (?!(?:\w+ ){0,2}(?:mestrado|doutorado|pos|especializacao|mba))")


def _plain(text: str, lower: bool = True) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text.lower() if lower else text


def _ordered(found: set[str]) -> list[str]:
    # Open to every level is the same as not saying: nothing to hide.
    return [] if len(found) == len(LEVELS) else [level for level in LEVELS if level in found]


def find_levels(title: str, description: str = "") -> list[str]:
    """The levels a posting is for, in the order of LEVELS; [] = it doesn't say (or all)."""
    plain_title = _plain(title, lower=False)
    found = {level for level, pattern in _TITLE.items() if pattern.search(plain_title)}
    if found:
        return _ordered(found)
    # "Ph.D." and "B.S." would end the sentence at their dots.
    text = _ABBREVIATED.sub(lambda m: m.group(0).replace(".", "").replace(" ", ""), _plain(description))
    for match in _ENROLLMENT.finditer(text):
        sentence = match.group(0)
        found |= {level for level, pattern in _DEGREES.items() if pattern.search(sentence)}
        if _CURSANDO.match(sentence):
            found.add("undergrad")
    return _ordered(found)
