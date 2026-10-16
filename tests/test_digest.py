"""The public digest: Telegram channel post and Atom feeds."""

import xml.etree.ElementTree as ET

from radar import db, digest
from radar.labels import apply_rules
from radar.models import Opportunity

TODAY = "2026-10-09"


def make(title, url, location, first_seen=TODAY, **kwargs):
    opp = apply_rules(Opportunity(title=title, org="Org & Co", source="greenhouse", url=url, location=location, **kwargs))
    return opp, first_seen


def stored(pairs):
    conn = db.connect(":memory:")
    for opp, first_seen in pairs:
        db.upsert(conn, opp, first_seen)
    return db.load_all(conn)


def sample():
    return stored([
        make("Estágio em Dados", "https://e.com/br1", "São Paulo, SP, Brazil", pay="R$2,000/mo"),
        make("Estágio em Automação", "https://e.com/br2", "Campinas, Brazil", deadline="2026-10-15"),
        make("Software Engineering Intern", "https://e.com/us1", "New York, NY"),  # US work auth warning
        make("Research Intern", "https://e.com/eu1", "Zurich, Switzerland"),
        make("Old Brazilian Intern", "https://e.com/old", "Recife, Brazil", first_seen="2026-09-01"),
    ])


def test_channel_post_puts_brazil_first_and_skips_flagged_roles_abroad():
    text = digest.telegram_text(sample(), TODAY, {"language": "pt"})
    assert text.startswith("<b>vagaLume · 9 out</b>")
    assert "4 vagas novas hoje (2 no Brasil ou remotas)" in text
    assert text.index("Estágio em Dados") < text.index("Research Intern")
    assert "Software Engineering Intern" not in text  # needs US work authorization
    assert "Org &amp; Co" in text  # Telegram HTML is escaped
    assert "⏰" in text and "15 out" in text  # the Campinas role closes in 6 days
    assert text.endswith(digest.SITE_URL)


def test_channel_post_stays_within_telegram_limit():
    many = stored([make(f"Estágio {n} " + "x" * 80, f"https://e.com/{n}", "Rio de Janeiro, Brazil") for n in range(400)])
    text = digest.telegram_text(many, TODAY, {"max_roles": 400})
    assert len(text) <= digest.TELEGRAM_LIMIT
    assert text.endswith(digest.SITE_URL)


def test_post_does_nothing_without_a_channel(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    digest.post(sample(), TODAY, {"telegram_channel": ""})  # conftest fails the test if it tried to send


def test_feeds_are_valid_atom(tmp_path):
    paths = digest.write_feeds(sample(), TODAY, {}, tmp_path)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    everything = ET.parse(paths[0]).getroot()
    brazil = ET.parse(paths[1]).getroot()
    titles = [e.find("a:title", ns).text for e in everything.findall("a:entry", ns)]
    assert len(titles) == 4  # the September role is too old for the feed
    assert all(" — Org & Co" in t for t in titles)
    assert len(brazil.findall("a:entry", ns)) == 2


def test_subscribe_links():
    links = digest.subscribe_links({"telegram_channel": "@vagalume_vagas"})
    assert links["telegram"] == "https://t.me/vagalume_vagas"
    assert links["feedBrasil"] == "feed-brasil.xml"


def test_each_field_of_study_has_its_own_brazil_feed(tmp_path):
    pairs = [make("Estágio Jurídico Tributário", "https://e.com/law", "São Paulo, SP, Brazil"),
             make("Estágio em Enfermagem", "https://e.com/nurse", "Recife, PE, Brazil"),
             make("Legal Intern", "https://e.com/law-us", "New York, NY")]
    paths = digest.write_feeds(stored(pairs), TODAY, {"language": "pt"}, tmp_path)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    law = ET.parse(tmp_path / "feeds" / "direito.xml").getroot()
    assert law.find("a:title", ns).text == "vagaLume: Direito, vagas novas no Brasil e remotas"
    assert [e.find("a:link", ns).get("href") for e in law.findall("a:entry", ns)] == ["https://e.com/law"]
    assert len(ET.parse(tmp_path / "feeds" / "saude.xml").getroot().findall("a:entry", ns)) == 1
    assert len(paths) == 2 + len(digest.FIELD_NAMES["pt"])


def test_e_mail_goes_through_a_feed_to_e_mail_service():
    links = digest.subscribe_links({"email_service": "https://feedrabbit.com/?url={feed}"})
    assert links["email"] == "" and "{feed}" in links["emailService"]
