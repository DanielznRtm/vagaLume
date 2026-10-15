"""Which Brazilian states (UFs) a role is in, from its location text.

The website lets you say where you live and keep only roles in your state
(remote roles always stay). Locations come in many shapes:
"Ceilândia, DF, Brazil (on-site)", "Vitória, Espírito Santo, Brazil",
"Sao Paulo, Sao Paulo, BRA", "São Paulo, Rio de Janeiro e Remoto", and
sometimes just a city ("Goiânia, Brazil", "DIVINOPOLIS, Brazil"): for those we
look the city up in IBGE's list of municipalities (radar/data/municipios.tsv,
only names that exist in a single state). A role whose state we can't tell
("Brazil (remote)", "2 Locations, Brazil") gets no state and is never hidden
for it.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from pathlib import Path

UFS = {
    "AC": "acre", "AL": "alagoas", "AP": "amapa", "AM": "amazonas", "BA": "bahia", "CE": "ceara",
    "DF": "distrito federal", "ES": "espirito santo", "GO": "goias", "MA": "maranhao", "MT": "mato grosso",
    "MS": "mato grosso do sul", "MG": "minas gerais", "PA": "para", "PB": "paraiba", "PR": "parana",
    "PE": "pernambuco", "PI": "piaui", "RJ": "rio de janeiro", "RN": "rio grande do norte",
    "RS": "rio grande do sul", "RO": "rondonia", "RR": "roraima", "SC": "santa catarina", "SP": "sao paulo",
    "SE": "sergipe", "TO": "tocantins",
}
# Abbreviations after a separator: "Ceilândia, DF", "Recife - PE", "Curitiba/PR", "(SP)".
_ABBREVIATION = re.compile(r"(?:^|[,/(\-–|])\s*(" + "|".join(UFS) + r")\b(?![a-z])")
# Full names, longest first so "mato grosso do sul" wins over "mato grosso".
_NAMES = sorted(((name, uf) for uf, name in UFS.items()), key=lambda pair: -len(pair[0]))
_BRASILIA = re.compile(r"\bbrasilia\b")


@cache
def cities() -> dict[str, str]:
    """Brazilian city (lower case, no accents) -> its state, for names found in one state only."""
    path = Path(__file__).parent / "data" / "municipios.tsv"
    rows = (line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#"))
    return {name: uf for name, uf in rows}


# Brazilian municipalities named like a big place abroad: a bare "Buenos Aires" or "Malta" in a
# company's list of cities is almost never the Brazilian one.
ALSO_ABROAD = {"santiago", "barcelona", "toledo", "florida", "lisboa", "cordoba", "buenos aires", "malta",
               "valencia", "victoria", "aurora", "martinez", "cambridge", "roma", "paris", "londres", "berlim",
               "colombia", "peru", "bolivia", "chile", "mexico", "canada", "venezuela", "uruguai", "argentina"}

# Words that come after a city in company locations: "LOUVEIRA PLANT", "Campinas Office".
_SUFFIX = re.compile(r"\s+(?:plant|planta|site|office|hub|campus|unidade|fabrica)$")


def city_state(name: str) -> str:
    """The state of a Brazilian city name ("Goiânia" -> "GO"), or "" if unknown or ambiguous."""
    return cities().get(_SUFFIX.sub("", _plain(name).lower().strip()), "")


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def brazil_states(location: str) -> list[str]:
    """The UFs named in a location, in the order of UFS; [] = can't tell."""
    plain = _plain(location)
    found = set(_ABBREVIATION.findall(plain))
    if not found:
        # No abbreviation: look for full names, but only as a whole part of the location
        # ("Vitória, Espírito Santo"), never inside a city name ("Ji-Paraná", "Paraíba do Sul").
        lower = plain.lower()
        for name, uf in _NAMES:
            if re.search(rf"(?:^|[,;/(]|\be)\s*{name}\s*(?:$|[,;/)]|\be\b|\()", lower):
                found.add(uf)
                lower = lower.replace(name, " ")  # "mato grosso do sul" is not also "mato grosso"
        if _BRASILIA.search(lower):
            found.add("DF")
    if not found and not re.search(r"[,;/(]", plain):
        # No separators at all: "Sao Paulo Sao Paulo Brazil".
        lower = plain.lower()
        found |= {uf for name, uf in _NAMES if re.search(rf"\b{name}\b", lower)}
    if not found:
        # Just a city: "Goiânia, Brazil", "LAIC R&D - LOUVEIRA, Brazil".
        for part in re.split(r"[,;/()|]|\s[-–]\s|\se\s", plain):
            uf = city_state(part)
            if uf:
                found.add(uf)
    return [uf for uf in UFS if uf in found]
