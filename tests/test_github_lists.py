"""SimplifyJobs (HTML tables) and vanshb03 (Markdown tables) READMEs."""

from datetime import date

from conftest import fixture_text

from radar.labels import apply_rules
from radar.sources import github_lists

TODAY = date(2026, 10, 5)


def test_simplify_html_table():
    items = github_lists.parse(fixture_text("simplify_summer.md"), "Simplify", today=TODAY, season="May–Aug")
    assert len(items) == 6
    first = items[0]
    assert first.org == "Khan Academy"
    assert first.title == "Software Engineer Intern"
    assert first.location == "Remote in USA / Remote in Canada"
    assert first.posted_date == "2026-10-05"  # "0d"
    assert first.url.startswith("https://job-boards.greenhouse.io/khanacademy/")
    apply_rules(first)
    assert first.season == "May–Aug"  # from search.yaml, since the title doesn't say
    assert first.area == "SWE"


def test_arrow_rows_inherit_company():
    items = github_lists.parse(fixture_text("simplify_summer.md"), "Simplify", today=TODAY)
    assert items[2].org == items[3].org == "Expedia Group"


def test_collapsed_locations_and_flags():
    items = github_lists.parse(fixture_text("simplify_summer.md"), "Simplify", today=TODAY)
    ey = next(o for o in items if o.org == "Ernst & Young")
    assert ey.location == "Nashville, TN / Dallas, TX / Chicago, IL / Atlanta, GA"  # <details> list
    waymo = next(o for o in items if o.org == "Waymo")
    assert "🎓" not in waymo.title
    apply_rules(waymo)
    assert "PhD-level?" in waymo.warnings


def test_offseason_skips_closed_rows_and_uses_terms():
    markdown = fixture_text("simplify_offseason.md")
    assert "🔒" in markdown
    items = github_lists.parse(markdown, "Off-season", today=TODAY)
    assert len(items) == 2  # the closed (🔒) rows are skipped
    assert items[0].title.endswith("(Winter 2026)")
    apply_rules(items[0])
    assert items[0].season == "year-round"


def test_new_grad_list():
    items = github_lists.parse(fixture_text("simplify_newgrad.md"), "New grad", kind="new-grad", today=TODAY)
    assert len(items) == 2
    apply_rules(items[0])
    assert "new-grad role (after graduation)" in items[0].warnings
    assert "unsure if student role" not in items[0].warnings


def test_markdown_pipe_table():
    items = github_lists.parse(fixture_text("vansh_summer.md"), "vansh", today=TODAY)
    assert [o.org for o in items] == ["Vertiv", "Vertiv", "The Nuclear Company"]
    assert items[0].title == "Product Management Intern"  # 🛂 removed from the title
    assert "no-sponsorship" in items[0].hints
    assert items[0].posted_date == "2026-08-21"  # "Aug 21"
    apply_rules(items[0])
    assert "US work auth?" in items[0].warnings
