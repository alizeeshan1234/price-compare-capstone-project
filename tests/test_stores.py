import pytest

from app.stores.base import parse_price, parse_rating
from app.stores.amazon import AmazonStore
from app.stores.flipkart import FlipkartStore
from app.stores.snapdeal import SnapdealStore
from app.stores.vijaysales import VijaySalesStore
import json
from app.stores.mock import MockStore
from tests.conftest import load


@pytest.mark.parametrize("text,expected", [
    ("₹69,900", 69900.0), ("₹1,29,900.00", 129900.0), ("Rs. 68,490", 68490.0), ("$1,299", 1299.0), ("no price", None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_parse_rating():
    assert parse_rating("4.5 out of 5 stars") == 4.5
    assert parse_rating("4.6") == 4.6
    assert parse_rating(None) is None


def test_amazon_skips_sponsored_and_priceless():
    offers = AmazonStore().parse(load("amazon_search.html"))
    assert [o.price for o in offers] == [69900.0, 79900.0, 68499.0]
    newest = offers[2]
    assert newest.title.startswith("iPhone 16 128 GB")  # brand-only span must not win
    assert "/dp/B0DGJ7TGDR" in newest.url and newest.rating == 4.4
    first = offers[0]
    assert first.title == "Apple iPhone 15 (128 GB) - Black"
    assert first.url.startswith("https://www.amazon.in/Apple-iPhone-15")
    assert first.rating == 4.5
    assert first.image.endswith(".jpg")


def test_amazon_blocked_page_raises(monkeypatch):
    from app.stores import base
    monkeypatch.setattr(base, "fetch_html", lambda url: load("amazon_captcha.html"))
    monkeypatch.setattr("app.stores.base.fetch_html", lambda url: load("amazon_captcha.html"))
    import app.stores.base as b
    store = AmazonStore()
    with pytest.raises(b.StoreError, match="blocked"):
        store.search("iphone", 5)


def test_flipkart_parses_products_only():
    offers = FlipkartStore().parse(load("flipkart_search.html"))
    assert len(offers) == 2
    assert offers[0].title == "APPLE iPhone 15 (Black, 128 GB)"
    assert offers[0].price == 66999.0
    assert offers[0].rating == 4.6
    assert offers[0].url.startswith("https://www.flipkart.com/apple-iphone-15-black")
    assert offers[1].rating is None


def test_flipkart_prefers_embedded_json_state():
    store = FlipkartStore()
    html = load("flipkart_state.html")
    assert not store.looks_blocked(html)  # "captcha" inside JS must not trip the block detector
    offers = store.parse(html)
    assert [o.price for o in offers] == [67999.0, 69900.0]  # strike-through MRP ignored, no-price item skipped
    first = offers[0]
    assert first.title == "Apple iPhone 15 (Blue, 128 GB)"
    assert first.url == "https://www.flipkart.com/apple-iphone-15-blue-128-gb/p/itm387c20f1f5347?pid=MOBHQV9YZGYG64U7"
    assert first.rating == 4.6
    assert first.image == "https://rukmini1.flixcart.com/image/312/312/xif0q/mobile/z/h/l/img.jpeg?q=70"


def test_flipkart_block_detection_only_for_empty_small_pages():
    store = FlipkartStore()
    assert store.looks_blocked("<html><body>Please verify captcha</body></html>")
    assert not store.looks_blocked(load("flipkart_search.html"))


def test_snapdeal_uses_data_price_and_star_width():
    offers = SnapdealStore().parse(load("snapdeal_search.html"))
    assert offers[0].price == 68490.0
    assert offers[0].rating == 4.3
    assert offers[1].price == 199.0
    assert offers[1].url == "https://www.snapdeal.com/product/iphone-15-cover/999"


def test_vijaysales_parses_api_json_and_prefers_selling_price():
    data = json.loads(load("vijaysales_search.json"))
    offers = VijaySalesStore().parse_json(data)
    assert len(offers) == 2  # the case has no price
    blue, black = offers
    assert blue.price == 58990.0  # lowest city selling price beats list price
    assert blue.url.startswith("https://www.vijaysales.com/p/P220946/220949")
    assert blue.image.endswith("220949-image1_2.jpg")
    assert black.price == 57900.0  # explicit sellingPrice wins
    assert black.url == "https://www.vijaysales.com/p/P220946/220946/apple-iphone-15-128gb-storage-black"


def test_vijaysales_search_uses_api(monkeypatch):
    data = json.loads(load("vijaysales_search.json"))
    calls = []
    monkeypatch.setattr(VijaySalesStore, "_call", lambda self, q, limit, keys: calls.append((q, limit)) or data)
    offers = VijaySalesStore().search("iphone 15", 1)
    assert calls == [("iphone 15", 1)] and len(offers) == 1


def test_search_urls_encode_query():
    assert AmazonStore().search_url("iphone 15") == "https://www.amazon.in/s?k=iphone+15"
    assert FlipkartStore().search_url("iphone 15") == "https://www.flipkart.com/search?q=iphone+15"
    assert "keyword=iphone+15" in SnapdealStore().search_url("iphone 15")
    assert VijaySalesStore().search_url("iphone 15") == "https://www.vijaysales.com/search/iphone-15"


def test_mock_store_is_deterministic():
    a = MockStore("amazon", "Amazon").search("iphone 15", 8)
    b = MockStore("amazon", "Amazon").search("iphone 15", 8)
    assert [o.price for o in a] == [o.price for o in b]
    assert all(o.store == "amazon" for o in a)


def test_fetch_html_routes_through_scraperapi_when_key_set(monkeypatch):
    from app.stores import base
    from app import config
    monkeypatch.setattr(config, "SCRAPER_API_KEY", "k123")
    seen = {}

    class R:
        status_code = 200
        text = "<html>ok</html>"

    def fake_get(url, **kw):
        seen["url"] = url; seen["params"] = kw.get("params"); return R()

    monkeypatch.setattr(base.requests, "get", fake_get)
    assert base.fetch_html("https://www.amazon.in/s?k=tv") == "<html>ok</html>"
    assert seen["url"] == "https://api.scraperapi.com/"
    assert seen["params"]["api_key"] == "k123" and seen["params"]["url"] == "https://www.amazon.in/s?k=tv"
    assert seen["params"]["country_code"] == "in"


def test_fetch_html_direct_when_no_proxy(monkeypatch):
    from app.stores import base
    from app import config
    monkeypatch.setattr(config, "SCRAPER_API_KEY", "")
    monkeypatch.setattr(config, "SCRAPER_PROXY_URL", "")

    class R:
        status_code = 200
        text = "direct"

    monkeypatch.setattr(base.requests, "get", lambda url, **kw: R() if "proxies" not in kw else None)
    assert base.fetch_html("https://www.snapdeal.com/search?keyword=tv") == "direct"


def test_fetch_html_reports_block(monkeypatch):
    from app.stores import base
    from app import config
    monkeypatch.setattr(config, "SCRAPER_API_KEY", "")
    monkeypatch.setattr(config, "MAX_RETRIES", 0)

    class R:
        status_code = 529
        text = ""

    monkeypatch.setattr(base.requests, "get", lambda url, **kw: R())
    with pytest.raises(base.StoreError, match="529.*blocked"):
        base.fetch_html("https://www.flipkart.com/search?q=tv")
