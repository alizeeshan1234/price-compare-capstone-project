"""Business logic: adding products, recording prices, firing alerts, health stats."""
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import config
from .models import Product, PriceHistory, Alert, ScrapeLog
from .notifier import send_telegram, format_alert
from .scraper import scrape, store_name, ScrapeError, FetchError

log = logging.getLogger(__name__)


class ProductExists(Exception):
    pass


def add_product(db: Session, url: str, target_price: float) -> Product:
    """Create a product and scrape it immediately so the user sees a price."""
    url = url.strip()
    if db.query(Product).filter(Product.url == url).first():
        raise ProductExists(url)
    product = Product(url=url, store=store_name(url), target_price=target_price)
    db.add(product)
    db.flush()
    check_product(db, product)
    return product


def delete_product(db: Session, product_id: int) -> bool:
    product = db.get(Product, product_id)
    if not product:
        return False
    db.delete(product)
    return True


def check_product(db: Session, product: Product) -> Optional[PriceHistory]:
    """Scrape one product, store the result, log the attempt, and maybe alert."""
    started = time.monotonic()
    try:
        result = scrape(product.url)
    except (ScrapeError, FetchError, Exception) as exc:  # noqa: BLE001
        duration = int((time.monotonic() - started) * 1000)
        product.last_checked_at = datetime.utcnow()
        product.last_error = f"{type(exc).__name__}: {exc}"
        db.add(ScrapeLog(product_id=product.id, success=False, message=product.last_error, duration_ms=duration))
        log.warning("scrape failed for %s: %s", product.url, exc)
        return None

    duration = int((time.monotonic() - started) * 1000)
    if result.title and (product.title == "Untitled product" or not product.title):
        product.title = result.title[:512]
    product.currency = result.currency or product.currency
    product.last_checked_at = datetime.utcnow()
    product.last_error = None

    entry = PriceHistory(product_id=product.id, price=result.price, in_stock=result.in_stock)
    db.add(entry)
    db.add(ScrapeLog(product_id=product.id, success=True, duration_ms=duration))

    maybe_alert(db, product, result.price)
    return entry


def maybe_alert(db: Session, product: Product, price: float) -> Optional[Alert]:
    """Send an alert if price <= target and we haven't alerted recently."""
    if price > product.target_price:
        return None
    cutoff = datetime.utcnow() - timedelta(hours=config.ALERT_COOLDOWN_HOURS)
    recent = (
        db.query(Alert)
        .filter(Alert.product_id == product.id, Alert.sent_at >= cutoff)
        .order_by(Alert.sent_at.desc())
        .first()
    )
    # Re-alert inside the cooldown only if the price dropped further.
    if recent and price >= recent.price:
        return None
    text = format_alert(product.title, price, product.target_price, product.currency, product.url)
    delivered = send_telegram(text)
    alert = Alert(product_id=product.id, price=price, delivered=delivered)
    db.add(alert)
    log.info("alert for %s at %s (delivered=%s)", product.title, price, delivered)
    return alert


def check_all_products(db: Session) -> Dict[str, int]:
    """Scheduled job body. Returns a small summary for logging."""
    products = db.query(Product).all()
    ok = fail = 0
    for i, product in enumerate(products):
        if check_product(db, product) is not None:
            ok += 1
        else:
            fail += 1
        db.commit()
        if i < len(products) - 1 and not config.MOCK_SCRAPER:
            time.sleep(config.SCRAPE_DELAY_SECONDS)
    return {"ok": ok, "failed": fail, "total": len(products)}


# --- health / metrics ---------------------------------------------------------

def health_summary(db: Session, days: int = 7) -> Dict[str, Any]:
    since = datetime.utcnow() - timedelta(days=days)
    total = db.query(func.count(ScrapeLog.id)).filter(ScrapeLog.created_at >= since).scalar() or 0
    success = (
        db.query(func.count(ScrapeLog.id))
        .filter(ScrapeLog.created_at >= since, ScrapeLog.success.is_(True))
        .scalar()
        or 0
    )
    avg_ms = (
        db.query(func.avg(ScrapeLog.duration_ms))
        .filter(ScrapeLog.created_at >= since, ScrapeLog.success.is_(True))
        .scalar()
    )
    alerts = db.query(func.count(Alert.id)).filter(Alert.sent_at >= since).scalar() or 0
    products = db.query(func.count(Product.id)).scalar() or 0
    failing = db.query(func.count(Product.id)).filter(Product.last_error.isnot(None)).scalar() or 0
    return {
        "days": days,
        "products": products,
        "failing_products": failing,
        "attempts": total,
        "successes": success,
        "success_rate": (success / total * 100) if total else None,
        "avg_duration_ms": int(avg_ms) if avg_ms else None,
        "alerts": alerts,
    }


def total_savings(db: Session) -> float:
    """Sum over products of (first observed price - lowest observed price)."""
    savings = 0.0
    for product in db.query(Product).all():
        if len(product.prices) >= 2:
            savings += max(0.0, product.prices[0].price - product.lowest_price)
    return savings
