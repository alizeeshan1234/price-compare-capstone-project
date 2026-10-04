import pytest

from app.scraper.base import parse_price, detect_currency, ScrapeError
from app.scraper.amazon import AmazonScraper
from app.scraper.flipkart import FlipkartScraper
from app.scraper.generic import GenericScraper
from app.scraper.registry import get_scraper, store_name
from tests.conftest import load


# --- helpers -----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("₹26,990.00", 26990.0),
    ("₹1,23,456", 123456.0),
    ("$1,299", 1299.0),
    ("5499.00", 5499.0),
    ("Price: Rs. 999 only", 999.0),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_parse_price_rejects_garbage():
    with pytest.raises(ScrapeError):
        parse_price("no numbers here")


def test_detect_currency():
    assert detect_currency("₹100") == "INR"
    assert detect_currency("$100") == "USD"
    assert detect_currency("€100") == "EUR"
    assert detect_currency("100") == "INR"


# --- amazon ------------------------------------------------------------------

def test_amazon_parses_title_and_price():
    r = AmazonScraper().parse(load("amazon_sample.html"), "https://www.amazon.in/dp/X")
    assert r.title.startswith("Sony WH-1000XM5")
    assert r.price == 26990.0
    assert r.in_stock is True
    assert r.currency == "INR"


def test_amazon_unavailable_raises_clear_error():
    with pytest.raises(ScrapeError, match="unavailable"):
        AmazonScraper().parse(load("amazon_unavailable.html"), "https://www.amazon.in/dp/X")


def test_amazon_captcha_detected():
    with pytest.raises(ScrapeError, match="CAPTCHA"):
        AmazonScraper().parse(load("amazon_captcha.html"), "https://www.amazon.in/dp/X")


# --- flipkart ----------------------------------------------------------------

def test_flipkart_parses():
    r = FlipkartScraper().parse(load("flipkart_sample.html"), "https://www.flipkart.com/p/x")
    assert r.title == "Apple iPhone 15 (Black, 128 GB)"
    assert r.price == 69999.0
    assert r.in_stock is True


def test_flipkart_sold_out_detected():
    r = FlipkartScraper().parse(load("flipkart_sold_out.html"), "https://www.flipkart.com/p/x")
    assert r.price == 4499.0
    assert r.in_stock is False


# --- generic -----------------------------------------------------------------

def test_generic_json_ld():
    r = GenericScraper().parse(load("generic_jsonld.html"), "https://shop.example/kb")
    assert r.title == "Mechanical Keyboard TKL"
    assert r.price == 5499.0
    assert r.currency == "INR"
    assert r.in_stock is True


def test_generic_meta_tags():
    r = GenericScraper().parse(load("generic_meta.html"), "https://shop.example/shoes")
    assert r.title == "Trail Running Shoes"
    assert r.price == 89.99
    assert r.currency == "USD"
    assert r.in_stock is False


def test_generic_no_data_raises():
    with pytest.raises(ScrapeError):
        GenericScraper().parse(load("generic_none.html"), "https://blog.example/post")


# --- registry ----------------------------------------------------------------

@pytest.mark.parametrize("url,cls,name", [
    ("https://www.amazon.in/dp/B0BXYZ", AmazonScraper, "amazon"),
    ("https://amzn.in/d/abc", AmazonScraper, "amazon"),
    ("https://www.flipkart.com/apple-iphone/p/itm", FlipkartScraper, "flipkart"),
    ("https://shop.example.com/item/1", GenericScraper, "shop.example.com"),
])
def test_registry_dispatch(url, cls, name):
    assert isinstance(get_scraper(url), cls)
    assert store_name(url) == name
