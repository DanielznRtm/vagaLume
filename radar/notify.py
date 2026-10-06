"""Optional notifications. Each channel is skipped quietly if its
environment variables are not set.

Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
Email:    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
          EMAIL_TO, EMAIL_FROM (defaults to SMTP_USER)
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

import requests

from .report import ReportData

log = logging.getLogger(__name__)

MAX_LINES = 25
REPORT_URL_ENV = "RADAR_REPORT_URL"  # optional link to the published report


def summary_text(data: ReportData) -> str:
    """A short plain-text digest: counts, deadlines soon, then new items."""
    lines = [
        f"vagaLume {data.today}: {data.new_total} new, "
        f"{len(data.soon)} deadlines in 14 days, {data.total_open} open.",
    ]
    failed = [h.name for h in data.health if h.status != "ok"]
    if failed:
        lines.append("Sources with problems: " + ", ".join(failed))
    if data.soon:
        lines.append("\nDeadlines soon:")
        lines += [f"- {o.deadline} {o.title} ({o.org}) {o.url}" for o in data.soon[:10]]
    if data.new:
        lines.append("\nNew:")
        lines += [f"- [{o.area}] {o.title} ({o.org}) {o.url}" for o in data.new[:MAX_LINES]]
        if len(data.new) > MAX_LINES:
            lines.append(f"... and {len(data.new) - MAX_LINES} more in the report.")
    if os.environ.get(REPORT_URL_ENV):
        lines.append(f"\nFull report: {os.environ[REPORT_URL_ENV]}")
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False
    # Telegram messages are limited to 4096 characters.
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()
    return True


def send_email(text: str, subject: str) -> bool:
    host, to = os.environ.get("SMTP_HOST"), os.environ.get("EMAIL_TO")
    user, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    if not (host and to):
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ.get("EMAIL_FROM") or user or to
    message["To"] = to
    message.set_content(text)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(message)
    return True


def notify(data: ReportData) -> None:
    """Send the digest on every configured channel; never crash the run."""
    text = summary_text(data)
    subject = f"vagaLume {data.today}: {data.new_total} new"
    for name, send in (("Telegram", lambda: send_telegram(text)), ("email", lambda: send_email(text, subject))):
        try:
            if send():
                log.info("Sent %s notification", name)
        except Exception as error:  # noqa: BLE001
            log.warning("%s notification failed: %s", name, error)
