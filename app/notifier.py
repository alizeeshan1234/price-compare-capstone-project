"""Telegram notifications."""
import logging
import requests

from . import config

log = logging.getLogger(__name__)


def telegram_configured() -> bool:
    return bool(config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID)


def send_telegram(text: str) -> bool:
    """Send a message. Returns True on success. Never raises."""
    if not telegram_configured():
        log.info("Telegram not configured; would have sent: %s", text)
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": False},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        log.warning("Telegram API error %s: %s", resp.status_code, resp.text[:200])
    except requests.RequestException as exc:
        log.warning("Telegram request failed: %s", exc)
    return False


def format_alert(title: str, price: float, target: float, currency: str, url: str) -> str:
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(currency, currency + " ")
    return (
        f"🔔 Price drop!\n\n"
        f"{title}\n"
        f"Now: {symbol}{price:,.2f}  (target {symbol}{target:,.2f})\n\n"
        f"{url}"
    )
