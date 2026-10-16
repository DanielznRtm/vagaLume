"""Today's highlights (radar/picks.py) and the same rule in the website's JavaScript."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from radar import picks
from radar.picks import Prefs, decode_prefs, encode_prefs, fits, pick_today, skill_score
from radar.skills import NAMES as SKILL_NAMES

ROOT = Path(__file__).resolve().parents[1]
TODAY = "2026-10-15"


def role(i, **extra):
    base = {"id": f"r{i}", "title": f"Role {i}", "org": f"Org {i}", "added": TODAY, "source": "gupy", "area": "SWE",
            "regions": ["Brazil"], "states": ["SP"], "levels": [], "fields": [], "skills": [], "pay": "", "deadline": ""}
    return base | extra


def test_only_roles_first_seen_today():
    items = [role(1), role(2, added="2026-10-14"), role(3, source="programs")]
    assert [i["id"] for i in pick_today(items, Prefs(count=5), TODAY)] == ["r1"]


@pytest.mark.parametrize("item, prefs, expected", [
    (role(1, levels=["phd"]), Prefs(levels=["undergrad"]), False),
    (role(1, levels=["undergrad", "masters"]), Prefs(levels=["masters"]), True),
    (role(1, levels=[]), Prefs(levels=["phd"]), True),  # doesn't say
    (role(1, fields=["saude"]), Prefs(fields=["engenharia"]), False),
    (role(1, fields=["exatas"]), Prefs(fields=["engenharia"]), True),  # related
    (role(1, fields=["saude"]), Prefs(fields=["engenharia", "outra"]), True),
    (role(1, regions=["Brazil"], states=["RJ"]), Prefs(home="SP", work=["state"]), False),
    (role(1, regions=["Brazil"], states=["SP"]), Prefs(home="SP", work=["state"]), True),
    (role(1, regions=["Brazil"], states=[]), Prefs(home="SP", work=["state"]), True),  # can't tell
    (role(1, regions=["Europe", "remote"]), Prefs(work=["Brazil"]), True),  # remote
    (role(1, regions=["US/Canada", "remote"], warnings=["US work auth?"]), Prefs(work=["Brazil"]), False),
    (role(1, regions=["US/Canada", "remote"], warnings=["US work auth?"]), Prefs(work=["US/Canada"]), True),
    (role(1, regions=["unknown"]), Prefs(work=["Brazil"]), False),  # can't tell where: not a safe bet
    (role(1, regions=["unknown"]), Prefs(work=["any"]), True),
    (role(1, warnings=["new-grad role (after graduation)"]), Prefs(), False),
    (role(1, regions=["Europe"]), Prefs(work=["Brazil"]), False),
    (role(1, regions=["Europe"]), Prefs(work=["any"]), True),
    (role(1, area="quant"), Prefs(areas=["ML", "SWE"]), False),
    (role(1, area="other", subs=["tributario"]), Prefs(subs=["tributario", "trabalhista"]), True),
    (role(1, area="other", subs=["contabil"]), Prefs(subs=["tributario"]), False),
    (role(1, area="SWE"), Prefs(areas=["SWE"], subs=["financas"]), True),  # a tech area or a sub-area
    (role(1, area="other"), Prefs(areas=["SWE"], subs=["financas"]), False),
])
def test_fits(item, prefs, expected):
    assert fits(item, prefs) is expected


def test_skill_score_counts_languages_once():
    item = role(1, skills=["Python", "Java", "Go", "SQL", "Docker"])
    assert skill_score(item, ["Python"]) == 33  # 1 of 3 (languages are alternatives)
    assert skill_score(item, ["Python", "SQL", "Docker"]) == 100


def test_best_match_first_then_pay_then_deadline_and_one_per_company():
    items = [
        role(1, skills=["Python", "SQL", "Docker"]),
        role(2, skills=["Excel"], pay="R$1,500/mo"),
        role(3, skills=["Excel"], deadline="2026-10-20"),
        role(4, skills=["Python", "SQL", "Docker"], org="Org 1"),  # same company as r1
    ]
    picks = pick_today(items, Prefs(count=3, skills=["Python", "SQL", "Docker"]), TODAY)
    assert [i["id"] for i in picks] == ["r1", "r2", "r3"]
    # Not enough companies: the second role from Org 1 fills the gap.
    assert [i["id"] for i in pick_today(items, Prefs(count=10, skills=["Python", "SQL", "Docker"]), TODAY)] == ["r1", "r4", "r2", "r3"]


def test_own_field_before_related_before_unknown():
    items = [role(1, fields=[]), role(2, fields=["exatas"]), role(3, fields=["engenharia"])]
    assert [i["id"] for i in pick_today(items, Prefs(count=3, fields=["engenharia"]), TODAY)] == ["r3", "r2", "r1"]


def test_the_code_round_trips():
    prefs = Prefs(count=10, levels=["undergrad", "masters"], fields=["engenharia", "computacao"], home="SP",
                  work=["state", "Europe"], areas=["ML", "data"], skills=["Python", "PyTorch", "SQL"], lang="en")
    code = encode_prefs(prefs, SKILL_NAMES)
    assert len(code) <= 64 and re.fullmatch(r"[A-Za-z0-9_-]+", code)  # what Telegram accepts after /start
    assert decode_prefs(code, SKILL_NAMES) == canonical(prefs)


def test_the_code_with_sub_areas_still_fits_telegram_and_old_links_still_work():
    every = Prefs(count=10, levels=list(picks.LEVELS), fields=list(picks.FIELDS), home="SP", work=list(picks.WORK),
                  areas=list(picks.AREAS), subs=list(picks.SUBS), skills=list(SKILL_NAMES))
    code = encode_prefs(every, SKILL_NAMES)
    assert len(code) <= 64 and decode_prefs(code, SKILL_NAMES) == canonical(every)
    old = "AQEBAwAZAQAAAAAAAAAAAAAAAAAAAAAA"  # version 1 (before sub-areas): undergrad, Engenharia + Computação, SP, state, 5 a day
    assert decode_prefs(old, SKILL_NAMES).fields == ["engenharia", "computacao"] and decode_prefs(old, SKILL_NAMES).subs == []


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_the_site_lists_the_sub_areas_in_the_same_order():
    assert run_js("process.stdout.write(JSON.stringify(PICK.subs))", {}) == picks.SUBS


@pytest.mark.parametrize("code", ["", "hello", "AAAA", "x" * 64])
def test_bad_codes_are_refused(code):
    with pytest.raises(ValueError):
        decode_prefs(code, SKILL_NAMES)


def canonical(prefs: Prefs) -> Prefs:
    """The same preferences with every list in the code's order (decoding returns them that way)."""
    order = lambda names, universe: [n for n in universe if n in names]  # noqa: E731
    return Prefs(prefs.count, order(prefs.levels, picks.LEVELS), order(prefs.fields, picks.FIELDS), prefs.home,
                 order(prefs.work, picks.WORK), order(prefs.areas, picks.AREAS), order(prefs.subs, picks.SUBS),
                 order(prefs.skills, SKILL_NAMES), prefs.lang)


# --- the website's JavaScript gives the same answers ---------------------------
def run_js(script: str, payload: dict) -> object:
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    block = page[page.index("// <picks>"): page.index("// </picks>")]
    program = block + "\nconst input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n" + script
    out = subprocess.run(["node", "-e", program], input=json.dumps(payload), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


PROFILES = [
    Prefs(count=5),
    Prefs(count=3, levels=["undergrad"], fields=["engenharia", "computacao"], home="SP", work=["state"],
          skills=["Python", "SQL", "Excel", "AutoCAD", "CAD"]),
    Prefs(count=10, levels=["masters"], fields=["computacao"], work=["Brazil", "Europe"], areas=["ML", "data"],
          skills=["Python", "PyTorch", "Machine learning", "SQL"]),
    Prefs(count=5, levels=["phd"], fields=["exatas"], work=["any"], areas=["quant", "research"], skills=["C++", "Statistics"]),
    Prefs(count=10, levels=["undergrad"], fields=["direito"], home="RJ", work=["state", "LatAm"]),
    Prefs(count=10, fields=["direito", "negocios"], work=["Brazil"], subs=["tributario", "contabil", "financas", "quimica"]),
    Prefs(count=5, fields=["saude"], work=["any"], areas=["data"], subs=["enfermagem"]),
]


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
@pytest.mark.parametrize("prefs", PROFILES)
def test_site_and_bot_pick_the_same_roles(prefs):
    data = json.loads((ROOT / "docs" / "data.json").read_text(encoding="utf-8"))
    today = data["updated"]
    py = [i["id"] for i in pick_today(data["items"], prefs, today)]
    js = run_js("process.stdout.write(JSON.stringify(pickToday(input.items, input.prefs, input.today).map(i => i.id)))",
                {"items": data["items"], "prefs": prefs.to_dict(), "today": today})
    assert js == py


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
@pytest.mark.parametrize("prefs", PROFILES)
def test_the_site_writes_codes_the_bot_reads(prefs):
    code = run_js("process.stdout.write(JSON.stringify(encodePrefs(input.prefs, input.names)))",
                  {"prefs": prefs.to_dict(), "names": SKILL_NAMES})
    assert code == encode_prefs(prefs, SKILL_NAMES)
    assert decode_prefs(code, SKILL_NAMES) == canonical(prefs)


def test_the_page_has_no_stray_control_characters():
    """A "\\b" once reached docs/index.html as a real backspace, so /\\blaw\\b/ never matched "Law"."""
    from pathlib import Path

    page = (Path(__file__).parent.parent / "docs" / "index.html").read_text(encoding="utf-8")
    assert not [c for c in page if ord(c) < 32 and c not in "\n\t\r"]
