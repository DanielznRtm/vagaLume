"""Where the work happens: remote, hybrid or on-site.

Job boards have a "workplace" field, and the sources put it in the location
("São Paulo, SP, Brazil (hybrid)"). Recruiters often get it wrong, though: a
Gupy estágio marked remote whose description says "Modelo de trabalho:
Híbrido, 4 dias presenciais". So a clear sentence in the description wins over
the field. Only clear sentences count: "In-office perks" or "possibilidade de
migrar para híbrido" don't make a role hybrid.

A role can have more than one ("New York (Hybrid); United States (Remote)").
[] means nobody says.
"""

from __future__ import annotations

import re
import unicodedata

WORKPLACES = ("remote", "hybrid", "on-site")

# "Brazil-Remote Location-Araguaia" (Vale) is a mine far away, not remote work.
REMOTE_PLACE = re.compile(r"\bremot[eo]\b(?![- ](?:location|site|area|camp))", re.I)
_LOCATION = {
    "remote": re.compile(rf"{REMOTE_PLACE.pattern}|home[- ]?office|home[- ]based|\banywhere\b|\bworldwide\b|\bvirtual\b", re.I),
    "hybrid": re.compile(r"\bhybrid\b|\bhibrid[oa]\b", re.I),
    "on-site": re.compile(r"\bon[- ]?site\b|\bpresencial\b|\bin[- ]office\b", re.I),
}

# Sentences in the description, lower case without accents.
_HYBRID_TEXT = re.compile(
    r"(?:modelo|modalidade|regime|formato|jornada)(?: de trabalho)?:? ?(?:e )?hibrid"
    r"|(?:vaga|trabalho|atuacao) hibrid"
    r"|hibrido,? (?:sendo|com) \d"
    r"|\d dias? (?:da semana |por semana |na semana )?(?:presencia|no escritorio)"
    r"|hybrid (?:role|model|position|internship|technical internship|schedule|work model|work arrangement|arrangement|setup)"
    r"|(?:role|position|internship|job) is hybrid"
    r"|this hybrid"
    r"|(?:\d|one|two|three|four) days? (?:a|per|each) week in (?:the|our|an?) [a-z ]{0,20}office"
    r"|in-office requirement"
)
_ONSITE_TEXT = re.compile(
    r"(?:modelo|modalidade|regime|formato)(?: de trabalho)?:? ?presencial"
    r"|vaga presencial|100% presencial|trabalho presencial|atuar presencialmente|atuacao presencial"
    r"|(?:fully|100%) (?:on-?site|in[- ]office|in[- ]person)"
    r"|(?:role|position|internship|job) is (?:on-?site|in[- ]office|in[- ]person)"
    r"|on-?site (?:role|position|internship)|in-person in the"
)
_REMOTE_TEXT = re.compile(r"100% remot|totalmente remot|fully remote|100% home office")


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def find_workplaces(location: str, remote: bool = False, description: str = "") -> list[str]:
    """remote / hybrid / on-site, in the order of WORKPLACES; [] = nobody says."""
    found = {name for name, pattern in _LOCATION.items() if pattern.search(location)}
    if remote:
        found.add("remote")
    several_places = len(re.split(r";| / |\|", location)) > 1
    if several_places and found:
        return [w for w in WORKPLACES if w in found]  # each place has its own; trust the list
    text = _plain(description)
    if _HYBRID_TEXT.search(text):
        found = {"hybrid"}
    elif _ONSITE_TEXT.search(text):
        # "Presencial no primeiro mês, depois 100% remoto" is some of each.
        found = {"hybrid"} if _REMOTE_TEXT.search(text) else {"on-site"}
    return [w for w in WORKPLACES if w in found]
