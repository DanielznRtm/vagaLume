"""Finding companies with jobs in Brazil on Ashby, Greenhouse and Lever (radar/discover.py)."""

import gzip
from datetime import date

import yaml

from radar import discover
from radar.config import merge_discovered


def test_board_names_from_index_keys():
    assert discover.slug_from_key("com,ashbyhq,jobs)/acme-ai/7b4407a2", "com,ashbyhq,jobs)/") == "acme-ai"
    assert discover.slug_from_key("io,greenhouse,boards)/embed/job_app?for=nubank&token=1", "io,greenhouse,boards)/") == "nubank"
    assert discover.slug_from_key("com,ashbyhq,jobs)/api/x", "com,ashbyhq,jobs)/") == ""
    assert discover.slug_from_key("com,ashbyhq,jobs)/%20bad", "com,ashbyhq,jobs)/") == ""


def test_index_slugs_reads_only_the_blocks_of_the_prefix(monkeypatch):
    """A tiny cluster.idx and cdx file, read through byte ranges like the real ones."""
    blocks = [
        ["com,amazon)/ 1", "com,ashbyhq,app)/x 1"],
        ["com,ashbyhq,jobs)/acme-ai 1", "com,ashbyhq,jobs)/acme-ai/123 1", "com,ashbyhq,jobs)/openai 1"],
        ["com,ashbyhq,jobs)/zeta 1", "com,ashbyhq,www)/ 1"],
        ["com,b)/ 1"],
    ]
    cdx, cluster, offset = b"", [], 0
    for block in blocks:
        data = gzip.compress(("\n".join(f"{line} {{}}" for line in block) + "\n").encode())
        cluster.append(f"{block[0]}\tcdx-00000.gz\t{offset}\t{len(data)}\t{len(cluster) + 1}")
        cdx += data
        offset += len(data)
    files = {"cluster.idx": ("\n".join(cluster) + "\n").encode(), "cdx-00000.gz": cdx}

    class Head:
        headers = {"content-length": str(len(files["cluster.idx"]))}

    monkeypatch.setattr(discover.requests, "head", lambda url, **kw: Head())
    monkeypatch.setattr(discover, "get_range", lambda url, start, end: files[url.rsplit("/", 1)[1]][start:end + 1])
    assert discover.index_slugs("CC-MAIN-2026-43", "com,ashbyhq,jobs)/") == {"acme-ai", "openai", "zeta"}


def test_a_board_counts_its_jobs_in_brazil(monkeypatch):
    jobs = [
        {"title": "Programa de Estágio 2027", "location": "São Paulo", "address": {"postalAddress": {"addressCountry": "Brazil"}}},
        {"title": "Senior Engineer", "location": "São Paulo", "secondaryLocations": []},
        {"title": "Intern", "location": "San Francisco, CA"},
    ]
    monkeypatch.setattr(discover.Platform, "job_list", lambda self, slug: jobs)
    monkeypatch.setattr(discover, "_title_name", lambda url: "Acme")
    record = discover.check("ashby", "acme-ai", "2026-10-27")
    assert record == {"platform": "ashby", "slug": "acme-ai", "checked": "2026-10-27", "jobs": 3, "brazil": 2, "students": 1, "name": "Acme"}


def test_new_boards_first_then_the_oldest_answers():
    state = {
        ("ashby", "old"): {"checked": "2026-09-01", "brazil": 0},
        ("ashby", "recent"): {"checked": "2026-10-20", "brazil": 0},
        ("ashby", "br"): {"checked": "2026-10-19", "brazil": 3},
    }
    found = {"ashby": {"old", "recent", "br", "acme-ai", "nubank"}, "greenhouse": set(), "lever": set()}
    todo = discover.due(found, state, {"ashby": {"nubank"}}, date(2026, 10, 27))
    assert todo == [("ashby", "acme-ai"), ("ashby", "br"), ("ashby", "old")]  # nubank is in companies.yaml


def test_discovered_boards_join_the_companies(tmp_path):
    state = {
        ("ashby", "acme-ai"): {"platform": "ashby", "slug": "acme-ai", "checked": "2026-10-27", "brazil": 25, "students": 3, "name": "Acme"},
        ("ashby", "abroad"): {"platform": "ashby", "slug": "abroad", "checked": "2026-10-27", "brazil": 0},
        ("ashby", "nubank"): {"platform": "ashby", "slug": "nubank", "checked": "2026-10-27", "brazil": 9, "name": "Nubank"},
        ("greenhouse", "gone"): {"platform": "greenhouse", "slug": "gone", "checked": "2026-10-27", "gone": True},
    }
    path = tmp_path / "discovered.yaml"
    assert discover.write_discovered(state, {"ashby": {"nubank"}}, path) == 1
    discovered = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert discovered["ashby"] == [{"slug": "acme-ai", "name": "Acme"}] and discovered["greenhouse"] == []
    companies = merge_discovered({"ashby": [{"slug": "nubank", "name": "Nubank"}]}, discovered)
    assert [c["slug"] for c in companies["ashby"]] == ["nubank", "acme-ai"]


def test_state_round_trips(tmp_path):
    state = {("lever", "x"): {"platform": "lever", "slug": "x", "checked": "2026-10-27", "brazil": 1}}
    discover.save_state(state, tmp_path / "s.jsonl")
    assert discover.load_state(tmp_path / "s.jsonl") == state
