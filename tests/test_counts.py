"""The numbers the README and the guide quote ("45 fontes") follow the config."""

from types import SimpleNamespace

from radar import counts
from radar.config import ROOT, load_config
from radar.main import SOURCES


def test_marked_numbers_are_replaced():
    text = "**45<!--n:sources--> fontes** e 93<!--n:programs--> páginas; 7<!--n:other--> fica"
    assert counts.fill(text, {"sources": 46, "programs": 90}) == "**46<!--n:sources--> fontes** e 90<!--n:programs--> páginas; 7<!--n:other--> fica"


def test_open_roles_are_rounded_and_split_between_brazil_and_abroad():
    roles = [SimpleNamespace(regions=["Brazil"])] * 13285 + [SimpleNamespace(regions=["Europe"])] * 17000 \
        + [SimpleNamespace(regions=["remote"])] * 944 + [SimpleNamespace(regions=["unknown"])] * 81
    values = counts.counts({}, 45, roles)
    assert (values["open"], values["open_brazil"], values["open_abroad"]) == (31000, 13000, 17000)
    text = "cerca de **30.000<!--n:open--> vagas**, mais de 11.000<!--n:open_brazil--> no Brasil"
    assert counts.fill(text, values, ".") == "cerca de **31.000<!--n:open--> vagas**, mais de 13.000<!--n:open_brazil--> no Brasil"
    assert counts.fill("about 30,000<!--n:open--> roles", values, ",") == "about 31,000<!--n:open--> roles"


def test_the_readmes_and_the_guide_mark_their_numbers():
    values = counts.counts(load_config(), len(SOURCES), [SimpleNamespace(regions=["Brazil"])])
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
