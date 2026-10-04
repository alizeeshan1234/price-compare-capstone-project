"""Amazon (.in / .com) adapter."""
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult, ScrapeError, parse_price, detect_currency


class AmazonScraper(BaseScraper):
    name = "amazon"
    domains = ("amazon.in", "amazon.com", "amzn.in", "amzn.to")

    TITLE_SELECTORS = ["#productTitle", "h1#title", "h1 span"]
    PRICE_SELECTORS = [
        "#corePriceDisplay_desktop_feature_div span.a-price span.a-offscreen",
        "#corePrice_feature_div span.a-price span.a-offscreen",
        "span.a-price span.a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#price_inside_buybox",
    ]

    def parse(self, html: str, url: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "lxml")

        if soup.select_one("form[action*='validateCaptcha']"):
            raise ScrapeError("Amazon returned a CAPTCHA page")

        title = None
        for sel in self.TITLE_SELECTORS:
            node = soup.select_one(sel)
            if node and node.get_text(strip=True):
                title = node.get_text(strip=True)
                break

        in_stock = True
        availability = soup.select_one("#availability")
        if availability and "unavailable" in availability.get_text(" ", strip=True).lower():
            in_stock = False

        price_text = None
        for sel in self.PRICE_SELECTORS:
            node = soup.select_one(sel)
            if node and node.get_text(strip=True):
                price_text = node.get_text(strip=True)
                break

        if price_text is None:
            if not in_stock:
                # Unavailable items have no price; keep last known price via caller.
                raise ScrapeError("product currently unavailable, no price shown")
            raise ScrapeError("price element not found (layout may have changed)")

        return ScrapeResult(
            title=title or "Amazon product",
            price=parse_price(price_text),
            in_stock=in_stock,
            currency=detect_currency(price_text),
        )
