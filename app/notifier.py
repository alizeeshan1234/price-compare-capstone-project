"""Send price-drop emails. Falls back to logging when SMTP is not configured."""
import logging
import smtplib
from email.message import EmailMessage

from . import config

log = logging.getLogger(__name__)


def email_enabled() -> bool:
    return bool(config.SMTP_HOST)


def price_drop_message(alert: dict, price: float, store_label: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Price drop: {alert['title'][:60]} is now ₹{price:,.0f}"
    msg["From"] = config.ALERT_FROM
    msg["To"] = alert["email"]
    msg.set_content(
        f"Good news!\n\n{alert['title']}\n"
        f"is now ₹{price:,.0f} at {store_label}, below your target of ₹{alert['target_price']:,.0f}.\n"
        f"(It was ₹{alert['price_at_creation']:,.0f} when you set the alert.)\n\n"
        f"Buy it here: {alert['url']}\n"
        f"Compare all stores: {config.APP_URL}/?q={alert['query']}\n\n"
        "-- PriceCompare"
    )
    return msg


def send_price_drop(alert: dict, price: float, store_label: str) -> str:
    """Returns how the user was notified: 'email' or 'log'."""
    msg = price_drop_message(alert, price, store_label)
    if not email_enabled():
        log.info("ALERT (email not configured) to %s: %s", alert["email"], msg["Subject"])
        return "log"
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
        smtp.ehlo()
        if config.SMTP_STARTTLS:
            smtp.starttls()
        if config.SMTP_USER:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(msg)
    log.info("alert emailed to %s: %s", alert["email"], msg["Subject"])
    return "email"
