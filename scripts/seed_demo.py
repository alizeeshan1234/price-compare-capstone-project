"""Populate the database with realistic-looking demo history.

Usage:  python scripts/seed_demo.py [--days 30]
Safe to run on an empty database before a presentation so charts have data.
"""
import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import init_db, session_scope  # noqa: E402
from app.models import Product, PriceHistory, ScrapeLog, Alert  # noqa: E402

DEMO = [
    ("https://www.amazon.in/dp/B09XS7JWHH", "Sony WH-1000XM5 Wireless Headphones", "amazon", 26990, 24000),
    ("https://www.flipkart.com/apple-iphone-15-black-128-gb/p/itm6ac6485515ae4", "Apple iPhone 15 (Black, 128 GB)", "flipkart", 69999, 62000),
    ("https://www.amazon.in/dp/B0C7BZ4V1R", "Logitech MX Master 3S Mouse", "amazon", 8495, 7000),
    ("https://www.flipkart.com/samsung-galaxy-watch6/p/itm1", "Samsung Galaxy Watch6 44mm", "flipkart", 24999, 20000),
    ("https://shop.example.com/keyboard-tkl", "Mechanical Keyboard TKL", "shop.example.com", 5499, 4500),
]


def main(days: int) -> None:
    init_db()
    rng = random.Random(42)
    now = datetime.utcnow()
    with session_scope() as db:
        if db.query(Product).count():
            print("Database already has products; refusing to seed. Delete pricewatch.db first.")
            return
        for url, title, store, start, target in DEMO:
            p = Product(url=url, title=title, store=store, target_price=target, currency="INR",
                        created_at=now - timedelta(days=days))
            db.add(p)
            db.flush()
            price = float(start)
            for i in range(days * 4):  # 4 checks per day
                ts = now - timedelta(days=days) + timedelta(hours=6 * i)
                # random walk with an occasional sale
                price *= rng.uniform(0.985, 1.012)
                if rng.random() < 0.04:
                    price *= rng.uniform(0.85, 0.95)
                price = max(price, start * 0.7)
                ok = rng.random() > 0.05
                db.add(ScrapeLog(product_id=p.id, success=ok, duration_ms=rng.randint(400, 2500),
                                 message=None if ok else "FetchError: HTTP 503", created_at=ts))
                if ok:
                    db.add(PriceHistory(product_id=p.id, price=round(price, 2), in_stock=rng.random() > 0.03, checked_at=ts))
                    if price <= target and rng.random() < 0.3:
                        db.add(Alert(product_id=p.id, price=round(price, 2), sent_at=ts, delivered=True))
            p.last_checked_at = now
        print(f"Seeded {len(DEMO)} products with ~{days * 4} points each.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    main(ap.parse_args().days)
