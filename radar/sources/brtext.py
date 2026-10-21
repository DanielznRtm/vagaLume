"""Small text helpers shared by the Brazilian sources that get names in CAPITALS
(CIEE's public-sector notices, Fundação Mudes, Recrutei, TAQE): turn
"TRIBUNAL REGIONAL ELEITORAL DO ESTADO DE MATO GROSSO DO SUL - TRE-MS" into
"Tribunal Regional Eleitoral do Estado de Mato Grosso do Sul - TRE-MS", and
build "City, UF, Brazil" locations.
"""

from __future__ import annotations

import re
import unicodedata

from ..places import UFS, city_state

# Estágios for high-school and technical students: "ESTÁGIO ENSINO MÉDIO", "Estágio Técnico em
# Elétrica", "Estagiário(a) Técnico(a)", "Estágio em Técnico em Enfermagem". The site hides them
# (level "school"), so the sources leave them out.
SCHOOL_TITLE = re.compile(
    r"ensino m[ée]dio|n[íi]vel m[ée]dio|n[íi]vel t[ée]cnico|ensino fundamental|t[ée]cnic[oa]\s+em\b"
    r"|est[áa]gi\w*\s*(?:\(a\)\s*)?(?:em\s+|de\s+)?t[ée]cnic", re.I)

_SMALL = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "as", "os", "para", "com", "na", "no", "nas", "nos", "ou"}
# Full state name (lower case, no accents) -> UF, for "Rio de Janeiro" in TAQE's addresses.
_STATE_NAMES = {name: uf for uf, name in UFS.items()}
_ROMAN = re.compile(r"^(?:[ivxl]+)$", re.I)


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _vowelless(word: str) -> bool:
    return not re.search(r"[aeiouáéíóúâêôãõà]", word, re.I)


def _capital(word: str) -> str:
    """ "(NÍVEL" -> "(Nível", "D'OESTE" -> "D'Oeste"."""
    word = word.lower()
    word = re.sub(r"^([^a-zà-ÿ]*)([a-zà-ÿ])", lambda m: m[1] + m[2].upper(), word)
    return re.sub(r"'([a-zà-ÿ])", lambda m: "'" + m[1].upper(), word)


def title_pt(text: str, acronym_tail: bool = False) -> str:
    """Title case for a name typed in capitals; names already in mixed case are left alone.
    Acronyms stay: UFs ("SP"), words without vowels ("TRT", "PMSP"), roman numerals ("II"),
    words with digits and, with `acronym_tail` (organisation names), a single last word after a
    dash or bar ("... - FINEP", "| TRE-MS")."""
    text = " ".join(str(text or "").split())
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) < 0.8 * len(letters):
        return text
    # A last part that is one word ("- FINEP", "| TRE-MS", "- CAESB") is an acronym.
    keep: set[int] = set()
    parts = re.split(r"(\s[-–|]\s)", text)
    if acronym_tail and len(parts) >= 3 and len(parts[-1].split()) == 1:
        keep.add(len(text) - len(parts[-1]))
    out: list[str] = []
    position = 0
    for index, word in enumerate(text.split(" ")):
        start = text.index(word, position)
        position = start + len(word)
        core = word.strip("()[],.;:")
        lower = core.lower()
        if start in keep or core.upper() in UFS or re.search(r"\d", core) or (_vowelless(core) and len(core) > 1) or (
            _ROMAN.match(core) and len(core) > 1
        ):
            out.append(word)
        elif "-" in core and all(p.upper() in UFS or _vowelless(p) or len(p) <= 3 for p in core.split("-") if p):
            out.append(word)  # "TRE-MS", "TRT-2"
        elif index and lower in _SMALL:
            out.append(word.lower())
        else:
            out.append("-".join(p if p.strip("()[],.;:").upper() in UFS else _capital(p) for p in word.split("-")))
    return " ".join(out)


def uf_of(state: str) -> str:
    """ "SP" -> "SP"; "São Paulo" -> "SP"; "" when unknown."""
    state = (state or "").strip()
    if state.upper() in UFS:
        return state.upper()
    return _STATE_NAMES.get(_plain(state), "")


def br_place(city: str, state: str = "") -> str:
    """ "CAMPO GRANDE", "MS" -> "Campo Grande, MS, Brazil"; the state is looked up when missing."""
    city = title_pt(" ".join(str(city or "").split()))
    uf = uf_of(state) or (city_state(city) if city else "")
    if city and uf:
        return f"{city}, {uf}, Brazil"
    if city:
        return f"{city}, Brazil"
    return f"{uf}, Brazil" if uf else "Brazil"


def join_places(places: list[str], limit: int = 6) -> str:
    """Several places, without repeats: "A, SP, Brazil / B, RJ, Brazil / +3 cities, Brazil"."""
    unique = list(dict.fromkeys(p for p in places if p))
    if not unique:
        return "Brazil"
    shown = " / ".join(unique[:limit])
    return shown + (f" / +{len(unique) - limit} cities, Brazil" if len(unique) > limit else "")
