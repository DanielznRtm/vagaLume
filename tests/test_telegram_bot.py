"""The students' Telegram digest (radar/telegram_bot.py), with Telegram mocked."""

import pytest
from cryptography.fernet import Fernet

from radar import telegram_bot as bot
from radar.picks import Prefs, encode_prefs
from radar.skills import NAMES as SKILL_NAMES

TODAY = "2026-10-15"
PREFS = Prefs(count=3, levels=["undergrad"], fields=["engenharia"], home="SP", work=["state"], areas=["SWE"],
              skills=["Python", "SQL"])


def message(text, chat=42, kind="private", lang="pt-br"):
    return {"update_id": 1, "message": {"chat": {"id": chat, "type": kind}, "from": {"language_code": lang}, "text": text}}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("DIGEST_KEY", Fernet.generate_key().decode())
    sent = []
    monkeypatch.setattr(bot, "send", lambda chat, text, html=False: sent.append((chat, text)))
    return tmp_path / "subscribers.enc", sent


def test_the_list_is_encrypted(env):
    path, _ = env
    chat_id = "987654321012"
    bot.save({"offset": 7, "subscribers": {chat_id: {"prefs": PREFS.to_dict(), "since": TODAY}}}, path)
    # Encrypted text is random-looking, so check for things that can't show up by chance.
    stored = path.read_bytes()
    assert chat_id.encode() not in stored and b"subscribers" not in stored and b"undergrad" not in stored
    assert bot.load(path)["subscribers"][chat_id]["prefs"]["home"] == "SP"


def test_start_with_a_code_subscribes_and_explains():
    subscribers = {}
    chat, reply = bot.handle(message("/start " + encode_prefs(PREFS, SKILL_NAMES)), subscribers, TODAY)
    assert chat == "42" and subscribers["42"]["prefs"]["count"] == 3
    assert "até 3 vagas" in reply and "no meu estado (SP)" in reply and "2 habilidades" in reply


def test_a_new_code_updates_but_keeps_the_start_date():
    subscribers = {"42": {"prefs": PREFS.to_dict(), "since": "2026-10-01"}}
    bot.handle(message("/start " + encode_prefs(Prefs(count=10), SKILL_NAMES)), subscribers, TODAY)
    assert subscribers["42"] == {"prefs": Prefs(count=10).to_dict(), "since": "2026-10-01"}


@pytest.mark.parametrize("text", ["/parar", "/stop", "/sair"])
def test_stop_unsubscribes(text):
    subscribers = {"42": {"prefs": PREFS.to_dict(), "since": TODAY}}
    chat, reply = bot.handle(message(text), subscribers, TODAY)
    assert subscribers == {} and "não vai mais receber" in reply


def test_blocking_the_bot_unsubscribes():
    subscribers = {"42": {"prefs": PREFS.to_dict(), "since": TODAY}}
    update = {"update_id": 2, "my_chat_member": {"chat": {"id": 42}, "new_chat_member": {"status": "kicked"}}}
    assert bot.handle(update, subscribers, TODAY) is None and subscribers == {}


def test_bad_code_and_plain_start_point_to_the_site():
    subscribers = {}
    assert "não funcionou" in bot.handle(message("/start hello"), subscribers, TODAY)[1]
    assert "Destaques de hoje" in bot.handle(message("/start"), subscribers, TODAY)[1]
    assert "Today's highlights" in bot.handle(message("hi", lang="en"), subscribers, TODAY)[1]
    assert subscribers == {}


def test_groups_are_ignored():
    assert bot.handle(message("/start x", kind="group"), {}, TODAY) is None


def test_collect_reads_replies_and_saves(env, monkeypatch):
    path, sent = env
    calls = []

    def fake_call(method, **params):
        calls.append((method, params))
        return [message("/start " + encode_prefs(PREFS, SKILL_NAMES)) | {"update_id": 11}]

    monkeypatch.setattr(bot, "call", fake_call)
    assert bot.collect(path) == 1
    assert calls[0][1]["offset"] == 1 and len(sent) == 1
    state = bot.load(path)
    assert state["offset"] == 11 and "42" in state["subscribers"]


def test_daily_message_lists_the_picks(env):
    path, sent = env
    bot.save({"offset": 0, "subscribers": {"42": {"prefs": PREFS.to_dict(), "since": TODAY},
                                           "43": {"prefs": Prefs(areas=["quant"]).to_dict(), "since": TODAY}}}, path)
    items = [{"id": "a", "title": "Estágio em <Dados>", "org": "Org", "url": "https://x/a?b=1&c=2", "location": "Campinas, SP, Brazil",
              "added": TODAY, "source": "gupy", "area": "SWE", "regions": ["Brazil"], "states": ["SP"], "levels": [],
              "fields": ["engenharia"], "skills": ["Python"], "pay": "R$1,500/mo", "deadline": "2026-10-20"}]
    assert bot.send_daily(items, TODAY, path) == 1  # 43 wants quant: nothing new for them, no message
    chat, text = sent[0]
    assert chat == "42"
    assert '<a href="https://x/a?b=1&amp;c=2">Estágio em &lt;Dados&gt;</a>' in text
    assert "Campinas, SP · R$1,500/mo · prazo 20 out" in text


def test_nothing_happens_without_the_secrets(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DIGEST_KEY", raising=False)
    assert bot.collect(tmp_path / "s.enc") == 0 and bot.send_daily([], TODAY, tmp_path / "s.enc") == 0
