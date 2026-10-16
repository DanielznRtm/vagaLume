"""Today's highlights for one person: the few best new roles for their profile.

The website shows them in the "Destaques de hoje" tab and the Telegram bot
(radar/telegram_bot.py) sends the same ones every day. The site does it in
JavaScript (the `pickToday` block in docs/index.html), the bot in Python; the
two follow the same rule, and tests/test_picks.py runs both on the same data
to keep them identical. The rule:

1. Only roles first seen today (the day of the run).
2. Only student roles (not "new grad" jobs for after graduation) that fit the
   preferences:
   - level: the role doesn't say, or it is for one of your levels;
   - field: the role doesn't say, or it is for one of your fields or a related
     one ("Outra" turns this off);
   - place: "anywhere"; or one of your regions, or your state when you
     picked "in my state" (a Brazilian role whose state we can't tell counts);
     or remote, unless it needs US work authorization and you didn't pick the
     US. Unlike the main list, a role whose place we can't tell at all is
     left out: highlights should be safe bets;
   - area: one of the areas you picked: a tech area (ML, Software...) or a
     sub-area of any section (Tributário, Enfermagem, Finanças... from
     radar/subareas.py). None picked = every area.
3. Best résumé match first: the share of the skills the posting mentions that
   you have (programming languages count once, as alternatives); then roles
   for your own field, then for a related one, then those that don't say;
   then roles that state the pay; then the closest deadline.
4. At most one role per company, unless there aren't enough.

Preferences travel in the Telegram link as a short code (encode in the site,
`decode_prefs` here). The lists below fix the order of the bits in that code:
only ever add to their END.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .subareas import SUBAREAS

LEVELS = ["undergrad", "masters", "phd"]
FIELDS = ["engenharia", "computacao", "exatas", "negocios", "direito", "saude", "biologicas", "comunicacao",
          "humanas", "arquitetura", "outra"]
UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
       "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]
WORK = ["state", "Brazil", "LatAm", "US/Canada", "Europe", "Asia/ME", "any"]
AREAS = ["ML", "research", "SWE", "data", "quant", "hardware", "other"]
SUBS = list(SUBAREAS)  # the same as PICK.subs in docs/index.html: new sub-areas go at the end of SUBAREAS
COUNTS = [3, 5, 10]

# Same as FIELD_RELATED in docs/index.html.
FIELD_RELATED = {
    "engenharia": ["computacao", "exatas", "arquitetura"],
    "computacao": ["engenharia", "exatas"],
    "exatas": ["engenharia", "computacao", "negocios"],
    "negocios": ["exatas", "comunicacao"],
    "direito": [],
    "saude": ["biologicas"],
    "biologicas": ["saude", "exatas"],
    "comunicacao": ["negocios", "humanas", "arquitetura"],
    "humanas": ["comunicacao"],
    "arquitetura": ["engenharia", "comunicacao"],
}
# Programming languages usually come as alternatives ("Java, Python or Go"): knowing one counts as one hit.
LANGUAGES = {"Python", "C++", "C", "C#", "Java", "JavaScript", "TypeScript", "Go", "Rust", "Kotlin", "Swift", "Scala",
             "OCaml", "Haskell", "R", "MATLAB"}
CODE_VERSION = 2  # 2 added the sub-areas; codes from version 1 are still read
NEW_GRAD = "new-grad role (after graduation)"  # warnings from radar/labels.py
US_AUTH = "US work auth?"


@dataclass
class Prefs:
    count: int = 5
    levels: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    home: str = ""  # a UF, or ""
    work: list[str] = field(default_factory=lambda: ["any"])
    areas: list[str] = field(default_factory=list)  # tech areas; with `subs` empty too = every area
    subs: list[str] = field(default_factory=list)  # sub-areas (radar/subareas.py)
    skills: list[str] = field(default_factory=list)  # names from radar/skills.py
    lang: str = "pt"

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Prefs:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# --- the code in the Telegram link -------------------------------------------
def _bits(names: list[str], universe: list[str]) -> int:
    return sum(1 << i for i, name in enumerate(universe) if name in names)


def _names(bits: int, universe: list[str]) -> list[str]:
    return [name for i, name in enumerate(universe) if bits >> i & 1]


def encode_prefs(prefs: Prefs, skill_names: list[str]) -> str:
    """The short code for a Telegram link (the site does the same in JavaScript)."""
    skills = _bits(prefs.skills, skill_names)
    skill_bytes = skills.to_bytes(max(1, math.ceil(len(skill_names) / 8)), "little")
    subs = _bits(prefs.subs, SUBS)
    sub_bytes = subs.to_bytes(math.ceil(subs.bit_length() / 8), "little")  # nothing when no sub-area is picked
    raw = bytes([
        CODE_VERSION,
        COUNTS.index(prefs.count) if prefs.count in COUNTS else 1,
        _bits(prefs.levels, LEVELS) | (128 if prefs.lang == "en" else 0),
        *_bits(prefs.fields, FIELDS).to_bytes(2, "little"),
        UFS.index(prefs.home) + 1 if prefs.home in UFS else 0,
        _bits(prefs.work, WORK),
        _bits(prefs.areas, AREAS),
        len(sub_bytes),
    ]) + sub_bytes + skill_bytes
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_prefs(code: str, skill_names: list[str]) -> Prefs:
    """Read the code from a Telegram link; raises ValueError if it isn't one of ours."""
    try:
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
    except Exception as error:  # noqa: BLE001
        raise ValueError("not a vagaLume code") from error
    if len(raw) < 8 or raw[0] not in (1, CODE_VERSION) or raw[1] >= len(COUNTS):
        raise ValueError("not a vagaLume code")
    work = _names(raw[6], WORK) or ["any"]
    subs, rest = 0, raw[8:]
    if raw[0] == 2:
        if not rest or len(rest) < 1 + rest[0]:
            raise ValueError("not a vagaLume code")
        subs, rest = int.from_bytes(rest[1:1 + rest[0]], "little"), rest[1 + rest[0]:]
    return Prefs(
        count=COUNTS[raw[1]],
        levels=_names(raw[2] & 127, LEVELS),
        lang="en" if raw[2] & 128 else "pt",
        fields=_names(int.from_bytes(raw[3:5], "little"), FIELDS),
        home=UFS[raw[5] - 1] if 0 < raw[5] <= len(UFS) else "",
        work=work,
        areas=_names(raw[7], AREAS),
        subs=_names(subs, SUBS),
        skills=_names(int.from_bytes(rest, "little"), skill_names),
    )


# --- the rule ------------------------------------------------------------------
def fits(item: dict[str, Any], prefs: Prefs) -> bool:
    """Rule 2. `item` is a role as in docs/data.json."""
    levels = item.get("levels") or []
    if levels and prefs.levels and not set(levels) & set(prefs.levels):
        return False
    mine = [f for f in prefs.fields if f != "outra"]
    fields = item.get("fields") or []
    if mine and "outra" not in prefs.fields and fields:
        ok = set(mine) | {r for f in mine for r in FIELD_RELATED.get(f, [])}
        if not set(fields) & ok:
            return False
    warnings = item.get("warnings") or []
    if NEW_GRAD in warnings:
        return False
    regions = item.get("regions") or []
    where = [r for r in regions if r not in ("remote", "unknown")]
    if "any" not in prefs.work:
        states = item.get("states") or []
        in_my_state = "state" in prefs.work and prefs.home and "Brazil" in where and (not states or prefs.home in states)
        remote_ok = "remote" in regions and (US_AUTH not in warnings or "US/Canada" in prefs.work)
        if not (in_my_state or set(where) & set(prefs.work) or remote_ok):
            return False
    if (prefs.areas or prefs.subs) and item.get("area") not in prefs.areas \
            and not set(item.get("subs") or []) & set(prefs.subs):
        return False
    return True


def skill_score(item: dict[str, Any], skills: list[str]) -> int:
    """0-100: how much of what the posting asks for you have (rule 3)."""
    asks = item.get("skills") or []
    mine = {s.lower() for s in skills}
    have = [s for s in asks if s.lower() in mine]
    langs = [s for s in asks if s in LANGUAGES]
    needed = len(asks) - len(langs) + (1 if langs else 0)
    got = len([s for s in have if s not in LANGUAGES]) + (1 if any(s in LANGUAGES for s in have) else 0)
    if not needed:
        return 0
    return round(100 * min(1, got / max(3, math.ceil(needed * 0.6))))


def field_rank(item: dict[str, Any], prefs: Prefs) -> int:
    """0 = your field, 1 = a related one, 2 = the role doesn't say (or you picked "Outra")."""
    mine = [f for f in prefs.fields if f != "outra"]
    fields = item.get("fields") or []
    if not mine or not fields:
        return 2
    if set(fields) & set(mine):
        return 0
    return 1 if set(fields) & {r for f in mine for r in FIELD_RELATED.get(f, [])} else 2


def _deadline_days(item: dict[str, Any], today: date) -> int:
    deadline = item.get("deadline") or ""
    if not deadline[:1].isdigit():
        return 10_000
    days = (date.fromisoformat(deadline[:10]) - today).days
    return days if days >= 0 else 10_000


def pick_today(items: list[dict[str, Any]], prefs: Prefs, today_iso: str) -> list[dict[str, Any]]:
    """The roles to show and send today, best first."""
    today = date.fromisoformat(today_iso)
    candidates = [i for i in items if i.get("added") == today_iso and i.get("source") != "programs" and fits(i, prefs)]
    candidates.sort(key=lambda i: (-skill_score(i, prefs.skills), field_rank(i, prefs), 0 if i.get("pay") else 1,
                                   _deadline_days(i, today), i["title"].lower(), i["id"]))
    chosen: list[dict[str, Any]] = []
    orgs: set[str] = set()
    for item in candidates:  # rule 4: one per company first...
        if item["org"] not in orgs:
            chosen.append(item)
            orgs.add(item["org"])
        if len(chosen) == prefs.count:
            return chosen
    picked = {i["id"] for i in chosen}  # ...then fill up if there weren't enough companies
    chosen += [i for i in candidates if i["id"] not in picked][: prefs.count - len(chosen)]
    return sorted(chosen, key=candidates.index)
