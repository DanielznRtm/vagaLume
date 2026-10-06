"""Shared test helpers. Tests never touch the network: every parser is fed
a saved sample response from tests/fixtures/."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str):
    return json.loads(fixture_text(name))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if a test accidentally tries to download something."""

    def blocked(*args, **kwargs):
        raise AssertionError("tests must not use the network")

    from radar import http

    monkeypatch.setattr(http._session, "request", blocked)  # radar/http.py
    monkeypatch.setattr("requests.post", blocked)  # Claude API and Telegram
