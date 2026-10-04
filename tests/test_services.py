from datetime import datetime, timedelta

import pytest

from app import services
from app.models import Product, PriceHistory, Alert, ScrapeLog
from app.scraper.base import ScrapeResult, ScrapeError
from app import analytics


class FakeScraper:
    """Replaces services.scrape with a controllable sequence of results."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def __call__(self, url):
        self.calls += 1
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(services, "send_telegram", lambda text: messages.append(text) or True)
    return messages


def test_add_product_scrapes_immediately(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(ScrapeResult("Widget", 1000.0)))
    p = services.add_product(db, "https://www.amazon.in/dp/W", target_price=800)
    db.commit()
    assert p.title == "Widget"
    assert p.store == "amazon"
    assert p.current_price == 1000.0
    assert db.query(ScrapeLog).count() == 1
    assert sent == []  # 1000 > 800, no alert


def test_duplicate_url_rejected(db, monkeypatch):
    monkeypatch.setattr(services, "scrape", FakeScraper(ScrapeResult("W", 1.0), ScrapeResult("W", 1.0)))
    services.add_product(db, "https://x.example/a", 5)
    with pytest.raises(services.ProductExists):
        services.add_product(db, "https://x.example/a", 5)


def test_alert_fires_when_below_target(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(ScrapeResult("Widget", 1000.0), ScrapeResult("Widget", 750.0)))
    p = services.add_product(db, "https://x.example/w", target_price=800)
    services.check_product(db, p)
    db.commit()
    assert len(sent) == 1
    assert "750" in sent[0]
    assert db.query(Alert).count() == 1
    assert db.query(Alert).first().delivered is True


def test_alert_not_repeated_within_cooldown(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(
        ScrapeResult("W", 700.0), ScrapeResult("W", 700.0), ScrapeResult("W", 720.0)))
    p = services.add_product(db, "https://x.example/w", target_price=800)
    services.check_product(db, p)
    services.check_product(db, p)
    assert len(sent) == 1


def test_alert_repeats_if_price_drops_further(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(ScrapeResult("W", 700.0), ScrapeResult("W", 600.0)))
    p = services.add_product(db, "https://x.example/w", target_price=800)
    services.check_product(db, p)
    assert len(sent) == 2


def test_alert_repeats_after_cooldown(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(ScrapeResult("W", 700.0), ScrapeResult("W", 700.0)))
    p = services.add_product(db, "https://x.example/w", target_price=800)
    db.flush()
    db.query(Alert).first().sent_at = datetime.utcnow() - timedelta(hours=48)
    services.check_product(db, p)
    assert len(sent) == 2


def test_failed_scrape_is_logged_not_fatal(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(
        ScrapeResult("W", 1000.0), ScrapeError("layout changed"), ScrapeResult("W", 990.0)))
    p = services.add_product(db, "https://x.example/w", target_price=10)
    assert services.check_product(db, p) is None
    assert "layout changed" in p.last_error
    assert db.query(ScrapeLog).filter_by(success=False).count() == 1
    # recovers on the next run
    assert services.check_product(db, p) is not None
    assert p.last_error is None
    assert len(p.prices) == 2


def test_health_summary(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(
        ScrapeResult("A", 100.0), ScrapeResult("B", 200.0), ScrapeError("boom")))
    a = services.add_product(db, "https://x.example/a", 50)
    services.add_product(db, "https://x.example/b", 50)
    services.check_product(db, a)
    db.commit()
    h = services.health_summary(db)
    assert h["products"] == 2
    assert h["attempts"] == 3
    assert h["successes"] == 2
    assert round(h["success_rate"], 1) == 66.7
    assert h["failing_products"] == 1


def test_total_savings(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(ScrapeResult("A", 1000.0), ScrapeResult("A", 800.0), ScrapeResult("A", 900.0)))
    a = services.add_product(db, "https://x.example/a", 1)
    services.check_product(db, a)
    services.check_product(db, a)
    assert services.total_savings(db) == 200.0


def test_check_all_products(db, monkeypatch, sent):
    monkeypatch.setattr(services, "scrape", FakeScraper(
        ScrapeResult("A", 1.0), ScrapeResult("B", 1.0), ScrapeResult("A", 1.0), ScrapeError("x")))
    monkeypatch.setattr(services.config, "SCRAPE_DELAY_SECONDS", 0)
    services.add_product(db, "https://x.example/a", 1)
    services.add_product(db, "https://x.example/b", 1)
    summary = services.check_all_products(db)
    assert summary == {"ok": 1, "failed": 1, "total": 2}


# --- analytics ---------------------------------------------------------------

def test_recommendation_levels():
    assert analytics.recommendation([100.0])["verdict"] == "Not enough data"
    assert analytics.recommendation([100, 120, 110, 100])["verdict"] == "Buy now"
    assert analytics.recommendation([100, 110, 120, 130, 140, 150, 160, 170, 105])["verdict"] == "Good price"
    assert analytics.recommendation([100, 200, 300, 190])["verdict"] == "Fair"
    assert analytics.recommendation([100, 100, 100, 150])["verdict"] == "Wait"


def test_change_pct():
    assert analytics.change_pct([100.0, 90.0]) == -10.0
    assert analytics.change_pct([100.0]) is None
