"""Gupy, Google, Amazon, NVIDIA and the program-page watcher."""

from datetime import date

import pytest
from conftest import fixture_json, fixture_text

from radar import db
from radar.labels import apply_rules
from radar.sources import amazon, google, gupy, nvidia, programs


def test_gupy_reads_the_json_api():
    items = gupy.parse(fixture_json("gupy_api.json"))
    titles = [o.title for o in items]
    assert "Analista de Dados Pleno" not in titles  # not a student role
    assert len(items) == 5
    first = items[0]
    assert first.title == "Estagiário(a)"
    assert first.location == "Goiânia, Goiás, Brazil (on-site)"
    assert first.deadline == "2027-01-30"
    assert first.posted_date == "2026-10-09"
    assert first.url.startswith("https://colegiosimbios.gupy.io/job/")
    apply_rules(first)
    assert first.regions == ["Brazil"]


def test_gupy_trainee_without_place_or_dates():
    trainee = gupy.parse(fixture_json("gupy_api.json"))[-1]
    assert trainee.hints == ["unsure-student"]  # trainee: maybe for recent graduates
    assert trainee.location == "Brazil (remote)" and trainee.remote
    assert trainee.posted_date == "" and trainee.deadline == "check page"
    apply_rules(trainee)
    assert trainee.pay == "R$6,000/mo"


def test_gupy_pages_until_a_short_page(monkeypatch):
    pages = []

    def fake_get_json(url, **kwargs):
        pages.append(url)
        offset = int(url.split("offset=")[1])
        jobs = fixture_json("gupy_api.json")["data"][:1] * (100 if offset < 200 else 3)
        return {"data": [dict(job, jobUrl=f"https://x.gupy.io/job/{offset}-{n}") for n, job in enumerate(jobs)]}

    monkeypatch.setattr(gupy, "get_json", fake_get_json)
    result = gupy.fetch({"search": {}})
    # 3 pages of student job types, then 3 pages for each title search in other job types.
    assert len(pages) == 3 + 3 * len(gupy.TITLE_SEARCHES) and result.checked == len(pages)
    assert "type=vacancy_type_internship%2Cvacancy_type_summer%2Cvacancy_type_trainee" in pages[0]
    assert "vacancy_type_talent_pool" in pages[3] and "jobName=est%C3%A1gio" in pages[3]
    assert len(result.items) == 203  # the same roles again are not repeated


def test_gupy_title_search_keeps_only_student_roles(monkeypatch):
    """Itaú files its "Programa de Estágio Corporativo" as a talent pool."""
    job = fixture_json("gupy_api.json")["data"][0]
    jobs = [dict(job, name="Programa de Estágio Corporativo 2026", type="vacancy_type_talent_pool", jobUrl="https://a/1"),
            dict(job, name="Coordenador de Vendas", type="vacancy_type_effective", jobUrl="https://a/2")]
    monkeypatch.setattr(gupy, "get_json", lambda url, **kwargs: {"data": jobs if "jobName" in url else []})
    titles = [o.title for o in gupy.fetch({"search": {}}).items]
    assert titles == ["Programa de Estágio Corporativo 2026"]


def test_gupy_bad_answer_raises():
    with pytest.raises(ValueError):
        gupy.parse({"message": "Failed to fetch jobs"})


def test_google_blob():
    items, total = google.parse(fixture_text("google_results.html"))
    assert total == 78
    assert [o.title for o in items] == [
        "Technical Program Manager Intern, BS/MS, Summer 2027",
        "Software Engineering Intern, PhD, Summer 2027",
    ]
    tpm, phd = items
    assert tpm.url == "https://www.google.com/about/careers/applications/jobs/results/80582381009806022"
    assert tpm.deadline == "2026-10-09"  # "complete your application before October 9, 2026"
    assert "Mountain View, CA, USA" in tpm.location
    apply_rules(phd)
    assert "PhD-level?" in phd.warnings
    assert phd.season == "May–Aug"


def test_amazon():
    items = amazon.parse(fixture_json("amazon.json"))
    assert len(items) == 4
    first = items[0]
    assert first.title == "WHS Intern"
    assert first.url == "https://www.amazon.jobs/en/jobs/10541373/whs-intern"
    assert first.posted_date == "2026-09-15"
    apply_rules(first)
    assert first.regions == ["Europe"]  # "ESP" country code


def test_nvidia_workday():
    items = nvidia.parse(fixture_json("nvidia.json"), from_intern_facet=True, today=date(2026, 10, 5))
    assert len(items) == 3
    assert items[0].url.startswith("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/")
    assert all("student" in o.hints for o in items)


@pytest.mark.parametrize(
    "posted, expected",
    [("Posted Today", "2026-10-05"), ("Posted Yesterday", "2026-10-04"), ("Posted 30+ Days Ago", "2026-09-05")],
)
def test_nvidia_posted_dates(posted, expected):
    assert nvidia._posted(posted, date(2026, 10, 5)) == expected


def test_program_main_text_ignores_noise():
    text = programs.main_text(fixture_text("program_page.html"))
    assert "Student Summer Research Fellowship" in text
    assert "tracking" not in text  # scripts removed
    assert "12:34" not in text  # navigation removed
    assert "All rights reserved" not in text  # footer removed


def test_program_change_detection():
    conn = db.connect(":memory:")
    html = fixture_text("program_page.html")
    first_hash = programs.content_hash(programs.main_text(html))
    assert db.page_hash_changed(conn, "https://x", first_hash, "2026-10-01") == (False, "2026-10-01")
    assert db.page_hash_changed(conn, "https://x", first_hash, "2026-10-02") == (False, "2026-10-01")
    changed_html = html.replace("December 15, 2026", "January 10, 2027")
    new_hash = programs.content_hash(programs.main_text(changed_html))
    assert db.page_hash_changed(conn, "https://x", new_hash, "2026-10-03") == (True, "2026-10-03")


def test_program_opportunity_uses_presets():
    program = {"name": "ETH SSRF", "url": "https://x", "area": "research", "season": "May–Aug", "regions": ["Europe"]}
    text = programs.main_text(fixture_text("program_page.html"))
    opp = apply_rules(programs.build_opportunity(program, text, changed=True, last_changed="2026-10-05"))
    assert opp.area == "research" and opp.season == "May–Aug" and opp.regions == ["Europe"]
    assert opp.deadline == "2026-12-15"
    assert opp.note.startswith("page changed on 2026-10-05")
    assert "grad-year limit?" in opp.warnings  # "expect to graduate in 2028 or later"


@pytest.mark.parametrize(
    "window, months",
    [("Nov–Jan", [11, 12, 1]), ("Feb, Aug", [2, 8]), ("Mar", [3]), ("Dec-Feb", [12, 1, 2]), ("", [])],
)
def test_program_application_months(window, months):
    assert programs.application_months(window) == months


def test_every_program_application_window_is_readable():
    """A typo in config/programs.yaml ("Novmber") would silently drop the window."""
    from radar.config import load_config

    for program in load_config()["programs"]:
        if program.get("applications"):
            assert programs.application_months(program["applications"]), program["name"]


def test_the_site_gets_the_application_months(tmp_path):
    from radar.site import write_data

    program = {"name": "CERN Summer Student Programme", "url": "https://careers.cern/x", "applications": "Nov–Jan"}
    opp = apply_rules(programs.build_opportunity(program, "x" * 300, changed=False, last_changed="2026-10-15"))
    conn = db.connect(tmp_path / "radar.db")
    db.upsert(conn, opp, "2026-10-15")
    path = write_data(db.load_all(conn), [], "2026-10-15", "rules", tmp_path, programs=[program])
    import json

    assert json.loads(path.read_text())["items"][0]["apply"] == [11, 12, 1]
