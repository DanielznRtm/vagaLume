"""The numbers the README and the guide quote ("45 fontes") follow the config."""

from radar import counts
from radar.config import ROOT, load_config
from radar.main import SOURCES


def test_marked_numbers_are_replaced():
    text = "**45<!--n:sources--> fontes** e 93<!--n:programs--> páginas; 7<!--n:other--> fica"
    assert counts.fill(text, {"sources": 46, "programs": 90}) == "**46<!--n:sources--> fontes** e 90<!--n:programs--> páginas; 7<!--n:other--> fica"


def test_the_readmes_and_the_guide_mark_their_numbers():
    values = counts.counts(load_config(), len(SOURCES))
    for name in counts.FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "<!--n:sources-->" in text, name
        for match in counts.MARKED.finditer(text):
            assert match[1] in values, f"{name}: unknown count {match[1]!r}"


def test_update_rewrites_only_files_that_changed(tmp_path):
    (tmp_path / "README.md").write_text("34<!--n:sources--> fontes\n", encoding="utf-8")
    assert counts.update(tmp_path, {"sources": 45}) == [tmp_path / "README.md"]
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "45<!--n:sources--> fontes\n"
    assert counts.update(tmp_path, {"sources": 45}) == []
