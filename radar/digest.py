"""The public daily digest: a Telegram channel post and Atom feeds.

Students subscribe without giving vagaLume anything: they join a Telegram
channel, or follow docs/feed.xml / docs/feed-brasil.xml in a feed reader or
an RSS-to-email service. vagaLume never stores names or addresses.

Settings live in config/digest.yaml. The channel post needs the secret
TELEGRAM_BOT_TOKEN, and the bot must be an admin of the channel.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import requests

from .db import StoredOpportunity
from .models import strip_tracking

log = logging.getLogger(__name__)

SITE_URL = "https://pedrocamargolince.github.io/vagaLume/"
TELEGRAM_LIMIT = 4096
FEED_DAYS = 3  # a feed keeps the roles found in the last few days
FEED_MAX = 60  # small, so the daily commit stays small; a reader that checks daily misses nothing
SOON_DAYS = 14
# Regions that count as "for students in Brazil" in the Brazil feed and the digest.
HOME_REGIONS = {"Brazil", "remote"}

TEXT = {
    "pt": {
        "title": "vagaLume · {date}",
        "counts": "{new} vagas novas hoje ({home} no Brasil ou remotas) · {soon} fecham em até 14 dias",
        "home": "🇧🇷 Novas no Brasil e remotas",
        "abroad": "🌍 Destaques no exterior",
        "soon": "⏰ Fecham em breve",
        "more": "… e mais {n}",
        "footer": "Todas as vagas, filtros e o match com o seu currículo:",
        "months": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
        "feed_title": "vagaLume: vagas novas para estudantes",
        "feed_title_br": "vagaLume: vagas novas no Brasil e remotas",
        "deadline": "prazo",
    },
    "en": {
        "title": "vagaLume · {date}",
        "counts": "{new} new roles today ({home} in Brazil or remote) · {soon} close within 14 days",
        "home": "🇧🇷 New in Brazil and remote",
        "abroad": "🌍 Highlights abroad",
        "soon": "⏰ Closing soon",
        "more": "… and {n} more",
        "footer": "Every role, filters and the résumé match:",
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "feed_title": "vagaLume: new student opportunities",
        "feed_title_br": "vagaLume: new roles in Brazil and remote",
        "deadline": "deadline",
    },
}


def _text(settings: dict[str, Any]) -> dict[str, Any]:
    return TEXT.get(str(settings.get("language") or "pt"), TEXT["pt"])


def _short_date(iso: str, words: dict[str, Any]) -> str:
    day = date.fromisoformat(iso)
    return f"{day.day} {words['months'][day.month - 1]}"


def _is_home(opp: StoredOpportunity) -> bool:
    return bool(HOME_REGIONS & set(opp.regions))


def _days_left(opp: StoredOpportunity, today: date) -> int | None:
    if not opp.deadline[:1].isdigit():
        return None
    try:
        return (date.fromisoformat(opp.deadline) - today).days
    except ValueError:
        return None


def _place(opp: StoredOpportunity) -> str:
    first = opp.location.split(" / ")[0].strip()
    return first.replace(", Brazil", "").replace(" (on-site)", "").strip()


# ---------------------------------------------------------------------------
# Choosing what to show
# ---------------------------------------------------------------------------
def _varied(items: list[StoredOpportunity], limit: int, per_org: int = 2) -> list[StoredOpportunity]:
    """The first `limit` items, with at most `per_org` from the same company."""
    chosen: list[StoredOpportunity] = []
    count: dict[str, int] = {}
    for opp in items:
        if count.get(opp.org, 0) < per_org:
            chosen.append(opp)
            count[opp.org] = count.get(opp.org, 0) + 1
        if len(chosen) == limit:
            break
    return chosen


def pick(opportunities: list[StoredOpportunity], today_iso: str, max_roles: int = 12) -> dict[str, list[StoredOpportunity]]:
    """The roles the digest shows: new at home, highlights abroad, closing soon."""
    today = date.fromisoformat(today_iso)
    open_items = [o for o in opportunities if o.is_open and o.status != "ignored"]
    new = [o for o in open_items if o.first_seen == today_iso and o.source != "programs"]

    def rank(o: StoredOpportunity) -> tuple[int, int, int, int, str]:
        # Tech and research areas first, then fewer warnings, stated pay, closer deadline.
        left = _days_left(o, today)
        return (o.area == "other", len(o.warnings), 0 if o.pay else 1, left if left is not None and left >= 0 else 999, o.title.lower())

    home_all = sorted((o for o in new if _is_home(o)), key=rank)
    # Abroad: only roles with nothing flagged (no visa, PhD or graduation-year warning).
    abroad_all = sorted((o for o in new if not _is_home(o) and not o.warnings), key=rank)
    soon_all = sorted(
        (o for o in open_items if (d := _days_left(o, today)) is not None and 0 <= d <= SOON_DAYS),
        key=lambda o: (o.deadline, rank(o)),
    )
    home_n = max(1, round(max_roles * 0.5))
    rest = max_roles - home_n
    return {
        "new": new,
        "home": _varied(home_all, home_n),
        "home_total": home_all,
        "abroad": _varied([o for o in abroad_all if o.area != "other"], (rest + 1) // 2),
        "soon": _varied([o for o in soon_all if _is_home(o)], rest // 2, per_org=1),
        "soon_total": soon_all,
    }


# ---------------------------------------------------------------------------
# The Telegram post
# ---------------------------------------------------------------------------
def _line(opp: StoredOpportunity, words: dict[str, Any], with_deadline: bool = False) -> str:
    link = f'<a href="{escape(strip_tracking(opp.url))}">{escape(opp.title)}</a>'
    parts = [escape(opp.org)]
    place = _place(opp)
    if place:
        parts.append(escape(place))
    if opp.pay:
        parts.append(escape(opp.pay))
    if with_deadline:
        return f"• {_short_date(opp.deadline, words)} · {link} · {' · '.join(parts)}"
    return f"• {link} · {' · '.join(parts)}"


def telegram_text(opportunities: list[StoredOpportunity], today_iso: str, settings: dict[str, Any]) -> str:
    """The channel post, in Telegram's HTML format and within its length limit."""
    words = _text(settings)
    chosen = pick(opportunities, today_iso, int(settings.get("max_roles") or 12))
    header = [
        f"<b>{escape(words['title'].format(date=_short_date(today_iso, words)))}</b>",
        escape(words["counts"].format(new=len(chosen["new"]), home=len(chosen["home_total"]), soon=len(chosen["soon_total"]))),
    ]
    sections: list[list[str]] = []
    if chosen["home"]:
        lines = [f"<b>{words['home']}</b>"] + [_line(o, words) for o in chosen["home"]]
        extra = len(chosen["home_total"]) - len(chosen["home"])  # the rest are on the site
        if extra > 0:
            lines.append(escape(words["more"].format(n=extra)))
        sections.append(lines)
    if chosen["abroad"]:
        sections.append([f"<b>{words['abroad']}</b>"] + [_line(o, words) for o in chosen["abroad"]])
    if chosen["soon"]:
        sections.append([f"<b>{words['soon']}</b>"] + [_line(o, words, with_deadline=True) for o in chosen["soon"]])
    footer = f"{escape(words['footer'])}\n{SITE_URL}"

    text = "\n".join(header)
    for lines in sections:
        block = "\n".join(lines)
        if len(text) + len(block) + len(footer) + 4 > TELEGRAM_LIMIT:
            break  # drop whole sections rather than cutting a link in half
        text += "\n\n" + block
    return text + "\n\n" + footer


def send_to_channel(text: str, settings: dict[str, Any]) -> bool:
    """Post to the public channel. Skipped quietly when not configured."""
    channel, token = str(settings.get("telegram_channel") or ""), os.environ.get("TELEGRAM_BOT_TOKEN")
    if not (channel and token):
        return False
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": channel, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()
    return True


def post(opportunities: list[StoredOpportunity], today_iso: str, settings: dict[str, Any]) -> None:
    """Send the public digest if there is something new; never crash the run."""
    try:
        if not any(o.first_seen == today_iso and o.is_open and o.source != "programs" for o in opportunities):
            log.info("Public digest: nothing new today, not posting")
            return
        if send_to_channel(telegram_text(opportunities, today_iso, settings), settings):
            log.info("Posted the public digest to %s", settings.get("telegram_channel"))
    except Exception as error:  # noqa: BLE001
        log.warning("Public digest failed: %s", error)


# ---------------------------------------------------------------------------
# Atom feeds
# ---------------------------------------------------------------------------
def _entry(opp: StoredOpportunity, words: dict[str, Any]) -> str:
    url = strip_tracking(opp.url)
    facts = [opp.org, opp.location.split(" / ")[0], opp.pay]
    if opp.deadline[:1].isdigit():
        facts.append(f"{words['deadline']} {opp.deadline}")
    summary = " · ".join(f for f in facts if f)
    return (
        "  <entry>\n"
        f"    <title>{xml_escape(opp.title)} — {xml_escape(opp.org)}</title>\n"
        f'    <link href="{xml_escape(url)}"/>\n'
        f"    <id>urn:vagalume:{opp.id}</id>\n"
        f"    <updated>{opp.first_seen}T12:00:00Z</updated>\n"
        f"    <summary>{xml_escape(summary)}</summary>\n"
        "  </entry>\n"
    )


def feed_xml(items: list[StoredOpportunity], title: str, self_url: str, today_iso: str, words: dict[str, Any]) -> str:
    entries = "".join(_entry(o, words) for o in items)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <title>{xml_escape(title)}</title>\n"
        f'  <link href="{SITE_URL}"/>\n'
        f'  <link rel="self" href="{self_url}"/>\n'
        f"  <id>{self_url}</id>\n"
        f"  <updated>{today_iso}T12:00:00Z</updated>\n"
        "  <author><name>vagaLume</name></author>\n"
        f"{entries}"
        "</feed>\n"
    )


def _sample(items: list[StoredOpportunity], limit: int) -> list[StoredOpportunity]:
    """Each day brings hundreds of roles: when there are too many, prefer variety
    (at most 2 per company first), then fill the rest in order."""
    if len(items) <= limit:
        return items
    chosen = _varied(items, limit)
    picked = {o.id for o in chosen}
    chosen += [o for o in items if o.id not in picked][: limit - len(chosen)]
    return chosen


def write_feeds(opportunities: list[StoredOpportunity], today_iso: str, settings: dict[str, Any], out_dir: str | Path) -> list[Path]:
    """docs/feed.xml (everything new) and docs/feed-brasil.xml (Brazil and remote)."""
    words = _text(settings)
    since = (date.fromisoformat(today_iso) - timedelta(days=FEED_DAYS - 1)).isoformat()
    recent = sorted(
        (o for o in opportunities if o.is_open and o.status != "ignored" and o.first_seen >= since and o.source != "programs"),
        key=lambda o: (o.first_seen, o.title.lower()),
        reverse=True,
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, title, items in (
        ("feed.xml", words["feed_title"], recent),
        ("feed-brasil.xml", words["feed_title_br"], [o for o in recent if _is_home(o)]),
    ):
        path = out / name
        path.write_text(feed_xml(_sample(items, FEED_MAX), title, SITE_URL + name, today_iso, words), encoding="utf-8")
        paths.append(path)
    return paths


def subscribe_links(settings: dict[str, Any]) -> dict[str, str]:
    """What the website's "daily updates" panel offers."""
    channel = str(settings.get("telegram_channel") or "")
    return {
        "telegram": f"https://t.me/{channel.lstrip('@')}" if channel.startswith("@") else "",
        "email": str(settings.get("email_signup_url") or ""),
        "feed": "feed.xml",
        "feedBrasil": "feed-brasil.xml",
    }
