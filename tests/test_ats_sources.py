"""Greenhouse, Lever and Ashby parsers, using saved API responses."""

from conftest import fixture_json

from radar.labels import apply_rules
from radar.sources import ashby, greenhouse, lever


def test_greenhouse_keeps_only_student_roles():
    items = greenhouse.parse(fixture_json("greenhouse.json"), "Jane Street")
    titles = [o.title for o in items]
    # "Accounting Coordinator" and "Swag Program Manager" are regular jobs.
    assert len(items) == 2
    assert not any("Accounting" in t or "Swag" in t for t in titles)


def test_greenhouse_uses_employment_type_metadata():
    items = greenhouse.parse(fixture_json("greenhouse.json"), "Jane Street")
    internship = items[0]
    # The title alone doesn't say "intern"; the metadata does, so we append it.
    assert internship.title.endswith("(Summer Internship)")
    assert "student" in internship.hints
    assert "May-August" in internship.hints  # the "Duration" field
    apply_rules(internship)
    assert internship.season == "May–Aug"


def test_greenhouse_fields():
    item = greenhouse.parse(fixture_json("greenhouse.json"), "Duolingo")[1]
    assert item.title == "Associate Product Manager, Intern"
    assert item.location == "Pittsburgh, PA"
    assert item.posted_date == "2026-09-15"
    assert item.deadline == "2026-10-08"  # Greenhouse's application_deadline field
    assert item.url.startswith("https://careers.duolingo.com/")
    assert item.description  # HTML was turned into text
    assert "<" not in item.description


def test_lever_commitment_intern_but_not_international():
    items = lever.parse(fixture_json("lever.json"), "Shield AI")
    titles = [o.title for o in items]
    assert any("Co-op" in t for t in titles)
    # commitment "International Office Entity" must not count as "intern"
    assert not any("Business Development" in t for t in titles)


def test_lever_new_grad_is_kept_with_warning():
    items = lever.parse(fixture_json("lever.json"), "Palantir")
    new_grad = next(o for o in items if "New Grad" in o.title)
    apply_rules(new_grad)
    assert "new-grad role (after graduation)" in new_grad.warnings
    assert new_grad.posted_date == "2026-08-10"
    assert new_grad.url.startswith("https://jobs.lever.co/")


def test_ashby_interns_and_locations():
    items = ashby.parse(fixture_json("ashby.json"), "Cohere")
    assert [o.title for o in items] == ["Research Internship (Winter 2027)", "Machine Learning Intern/Co-op  (Winter 2027)"]
    first = items[0]
    assert first.remote is True
    assert "Toronto" in first.location and "London" in first.location  # secondary locations included
    apply_rules(first)
    assert first.area == "research"
    assert first.season == "year-round"  # "Winter 2027" = during the semester
    assert {"US/Canada", "Europe", "remote"} <= set(first.regions)
