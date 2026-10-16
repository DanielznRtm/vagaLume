"""The vagaLume Telegram bot: each student gets their own daily highlights.

How someone subscribes: on the website, in "Destaques de hoje", they pick how
many roles a day and which areas, and tap "Receber no Telegram". That opens
t.me/<bot>?start=<code>, where the code packs their preferences (level, field,
where they'd work, areas, the skills from their résumé; see radar/picks.py).
Telegram then sends the bot "/start <code>".

Two jobs use this module:
- `python -m radar.telegram_bot collect` (.github/workflows/telegram.yml,
  every 30 minutes) reads new messages: /start <code> subscribes or updates,
  /parar (or /stop, or blocking the bot) unsubscribes. It replies right away
  and is the only job that writes the subscriber list.
- The daily run (radar/main.py) sends each subscriber the same picks the
  website shows them (radar/picks.py).

The subscriber list is data/subscribers.enc: Telegram chat ids and
preferences, encrypted with the DIGEST_KEY secret, so the public repository
shows nothing. Without TELEGRAM_BOT_TOKEN and DIGEST_KEY everything here is
skipped. `python -m radar.telegram_bot keygen` prints a new DIGEST_KEY.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

from .config import ROOT
from .picks import Prefs, decode_prefs, pick_today
from .skills import NAMES as SKILL_NAMES

log = logging.getLogger(__name__)

STORE = ROOT / "data" / "subscribers.enc"
SITE_URL = "https://pedrocamargolince.github.io/vagaLume/"
API = "https://api.telegram.org/bot{token}/{method}"

NAMES = {
    "pt": {
        "undergrad": "Graduação", "masters": "Mestrado", "phd": "Doutorado",
        "engenharia": "Engenharia", "computacao": "Computação", "exatas": "Exatas", "negocios": "Negócios",
        "direito": "Direito", "saude": "Saúde", "biologicas": "Biológicas", "comunicacao": "Comunicação",
        "humanas": "Humanas", "arquitetura": "Arquitetura", "outra": "Outra",
        "Brazil": "todo o Brasil", "LatAm": "América Latina", "US/Canada": "EUA e Canadá", "Europe": "Europa",
        "Asia/ME": "Ásia e Oriente Médio", "any": "qualquer lugar",
        "ML": "ML", "research": "Pesquisa", "SWE": "Software", "data": "Dados", "quant": "Quant",
        "hardware": "Hardware", "other": "Outras",
    },
    "en": {
        "undergrad": "Undergrad", "masters": "Master's", "phd": "PhD",
        "engenharia": "Engineering", "computacao": "Computing", "exatas": "Math/Physics", "negocios": "Business",
        "direito": "Law", "saude": "Health", "biologicas": "Biology", "comunicacao": "Communication",
        "humanas": "Humanities", "arquitetura": "Architecture", "outra": "Other",
        "Brazil": "all of Brazil", "LatAm": "Latin America", "US/Canada": "US and Canada", "Europe": "Europe",
        "Asia/ME": "Asia and Middle East", "any": "anywhere",
        "ML": "ML", "research": "Research", "SWE": "Software", "data": "Data", "quant": "Quant",
        "hardware": "Hardware", "other": "Other",
    },
}


def sub_names(lang: str) -> dict[str, str]:
    """Sub-area names ("tributario" -> "Tributário"), read from the site's strings ("sub.<key>": [en, pt])."""
    page = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    pairs = re.findall(r'"sub\.(\w+)": \["([^"]*)", "([^"]*)"\]', page)
    return {key: (en if lang == "en" else pt) for key, en, pt in pairs}


TEXT = {
    "pt": {
        "welcome": "✅ Pronto! Todo dia você vai receber até {count} vagas novas escolhidas para você.\n\n{summary}\n\n"
                   "Para mudar, gere um novo link em Destaques de hoje no site. Para parar, envie /parar.",
        "summary": "Nível: {levels}\nÁrea de estudo: {fields}\nOnde: {where}\nÁreas: {areas}\nCurrículo: {skills}",
        "skills": "{n} habilidades", "no_skills": "não enviado (as vagas vêm sem ordem de match)",
        "all_areas": "todas", "my_state": "no meu estado ({uf})",
        "hello": "Olá! Para receber vagas escolhidas para você, abra o vagaLume, vá em Destaques de hoje e toque em "
                 "Receber no Telegram:\n{site}",
        "bye": "Pronto, você não vai mais receber mensagens. Para voltar, gere um novo link no site:\n{site}",
        "bad": "Esse link não funcionou. Gere um novo em Destaques de hoje no site:\n{site}",
        "daily": "<b>Seus destaques de hoje · {day}</b>",
        "deadline": "prazo {day}",
        "pay_text": "* valor lido do texto da vaga: confira na página.",
        "footer": "Todas as vagas: {site}\n/parar para cancelar",
        "months": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    },
    "en": {
        "welcome": "✅ Done! Every day you'll get up to {count} new roles picked for you.\n\n{summary}\n\n"
                   "To change this, make a new link in Today's highlights on the site. To stop, send /stop.",
        "summary": "Level: {levels}\nField: {fields}\nWhere: {where}\nAreas: {areas}\nRésumé: {skills}",
        "skills": "{n} skills", "no_skills": "not sent (roles aren't sorted by match)",
        "all_areas": "all", "my_state": "in my state ({uf})",
        "hello": "Hi! To get roles picked for you, open vagaLume, go to Today's highlights and tap Get it on Telegram:\n{site}",
        "bye": "Done, you won't get any more messages. To come back, make a new link on the site:\n{site}",
        "bad": "That link didn't work. Make a new one in Today's highlights on the site:\n{site}",
        "daily": "<b>Your highlights today · {day}</b>",
        "deadline": "deadline {day}",
        "pay_text": "* pay read from the posting's text: check it on the page.",
        "footer": "Every role: {site}\n/stop to unsubscribe",
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    },
}


# --- the encrypted subscriber list ---------------------------------------------
def _fernet(key: str | None = None) -> Any:
    from cryptography.fernet import Fernet

    return Fernet((key or os.environ["DIGEST_KEY"]).encode())


def load(path: Path = STORE, key: str | None = None) -> dict[str, Any]:
    """{"offset": last Telegram update read, "subscribers": {chat id: {"prefs": ..., "since": date}}}"""
    if not path.exists():
        return {"offset": 0, "subscribers": {}}
    return json.loads(_fernet(key).decrypt(path.read_bytes()))


def save(state: dict[str, Any], path: Path = STORE, key: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_fernet(key).encrypt(json.dumps(state, sort_keys=True).encode()))


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("DIGEST_KEY"))


# --- talking to Telegram ---------------------------------------------------------
def call(method: str, **params: Any) -> Any:
    response = requests.post(API.format(token=os.environ["TELEGRAM_BOT_TOKEN"], method=method), json=params, timeout=30)
    if response.status_code == 403:
        raise PermissionError("the person blocked the bot")
    response.raise_for_status()
    return response.json()["result"]


def send(chat_id: str, text: str, html: bool = False) -> None:
    params: dict[str, Any] = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
    if html:
        params["parse_mode"] = "HTML"
    call("sendMessage", **params)


def describe(prefs: Prefs) -> str:
    """The summary in the welcome message."""
    words, names, subs = TEXT[prefs.lang], NAMES[prefs.lang], sub_names(prefs.lang)
    join = lambda items: ", ".join(names.get(i, i) for i in items) or "-"  # noqa: E731
    where = [words["my_state"].format(uf=prefs.home) if w == "state" else names.get(w, w) for w in prefs.work]
    return words["summary"].format(
        levels=join(prefs.levels), fields=join(prefs.fields), where=", ".join(where),
        areas=", ".join([names.get(a, a) for a in prefs.areas] + [subs.get(k, k) for k in prefs.subs]) or words["all_areas"],
        skills=words["skills"].format(n=len(prefs.skills)) if prefs.skills else words["no_skills"],
    )


def handle(update: dict[str, Any], subscribers: dict[str, Any], today: str) -> tuple[str, str] | None:
    """Apply one Telegram update to the list. Returns (chat id, reply) or None."""
    member = update.get("my_chat_member")
    if member and member.get("new_chat_member", {}).get("status") == "kicked":
        subscribers.pop(str(member["chat"]["id"]), None)  # blocked the bot
        return None
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    text = str(message.get("text") or "").strip()
    if chat.get("type") != "private" or not text:
        return None
    chat_id = str(chat["id"])
    lang = "en" if str((message.get("from") or {}).get("language_code", "")).startswith("en") else "pt"
    command, _, code = text.partition(" ")
    command = command.split("@")[0].lower()
    if command == "/start" and code:
        try:
            prefs = decode_prefs(code.strip(), SKILL_NAMES)
        except ValueError:
            return chat_id, TEXT[lang]["bad"].format(site=SITE_URL)
        subscribers[chat_id] = {"prefs": prefs.to_dict(), "since": subscribers.get(chat_id, {}).get("since", today)}
        return chat_id, TEXT[prefs.lang]["welcome"].format(count=prefs.count, summary=describe(prefs))
    if command in ("/stop", "/parar", "/sair"):
        old = subscribers.pop(chat_id, None)
        return chat_id, TEXT[old["prefs"]["lang"] if old else lang]["bye"].format(site=SITE_URL)
    return chat_id, TEXT[lang]["hello"].format(site=SITE_URL + "#tab=picks")


def collect(path: Path = STORE) -> int:
    """Read new messages, update the list, reply. Returns how many messages were handled."""
    if not configured():
        log.info("Telegram bot not configured (TELEGRAM_BOT_TOKEN, DIGEST_KEY): skipped")
        return 0
    state = load(path)
    updates = call("getUpdates", offset=state["offset"] + 1, timeout=0, allowed_updates=["message", "my_chat_member"])
    today = date.today().isoformat()
    for update in updates:
        state["offset"] = max(state["offset"], update["update_id"])
        reply = handle(update, state["subscribers"], today)
        if reply:
            try:
                send(*reply)
            except Exception as error:  # noqa: BLE001 - one failed reply must not lose the others
                log.warning("Reply to a subscriber failed: %s", error)
    if updates:
        save(state, path)
    log.info("Telegram: %d messages, %d subscribers", len(updates), len(state["subscribers"]))
    return len(updates)


# --- the daily message -------------------------------------------------------------
def _day(iso: str, words: dict[str, Any]) -> str:
    day = date.fromisoformat(iso[:10])
    return f"{day.day} {words['months'][day.month - 1]}"


def daily_text(picks: list[dict[str, Any]], prefs: Prefs, today: str) -> str:
    from html import escape

    words = TEXT[prefs.lang]
    lines = [words["daily"].format(day=_day(today, words)), ""]
    for n, item in enumerate(picks, 1):
        place = item["location"].split(" / ")[0].replace(", Brazil", "")
        details = [escape(item["org"]), escape(place)]
        if item.get("pay"):  # "*": read from the description, check it on the page (as on the site)
            details.append(escape(item["pay"]) + ("*" if item.get("pay_text") else ""))
        if item.get("deadline"):
            details.append(words["deadline"].format(day=_day(item["deadline"], words)))
        lines.append(f'{n}. <a href="{escape(item["url"], quote=True)}">{escape(item["title"])}</a>')
        lines.append("   " + " · ".join(details))
    if any(item.get("pay") and item.get("pay_text") for item in picks):
        lines += ["", words["pay_text"]]
    lines += ["", words["footer"].format(site=SITE_URL + "#tab=picks")]
    return "\n".join(lines)


def send_daily(items: list[dict[str, Any]], today: str, path: Path = STORE) -> int:
    """Send each subscriber their picks for today. Reads the list, never writes it."""
    if not configured() or not path.exists():
        return 0
    sent = 0
    for chat_id, entry in load(path)["subscribers"].items():
        prefs = Prefs.from_dict(entry["prefs"])
        picks = pick_today(items, prefs, today)
        if not picks:
            continue  # nothing new for this person today: no message
        try:
            send(chat_id, daily_text(picks, prefs, today), html=True)
            sent += 1
        except Exception as error:  # noqa: BLE001
            log.warning("Daily message to a subscriber failed: %s", error)
        time.sleep(0.05)  # Telegram allows about 30 messages a second
    log.info("Telegram: sent %d daily messages", sent)
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "collect":
        collect()
    elif command == "keygen":
        from cryptography.fernet import Fernet

        print(Fernet.generate_key().decode())
    else:
        sys.exit("usage: python -m radar.telegram_bot collect | keygen")
