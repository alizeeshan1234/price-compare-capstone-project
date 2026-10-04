"""Flipkart adapter."""
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult, ScrapeError, parse_price


class FlipkartScraper(BaseScraper):
    name = "flipkart"
    domains = ("flipkart.com", "fkrt.it")

    TITLE_SELECTORS = ["span.VU-ZEz", "span.B_NuCI", "h1 span", "h1"]
    PRICE_SELECTORS = ["div.Nx9bqj", "div._30jeq3", "div._16Jk6d", "div[class*='price']"]
    OOS_MARKERS = ("sold out", "currently unavailable", "coming soon")

    def parse(self, html: str, url: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "lxml")

        title = None
        for sel in self.TITLE_SELECTORS:
            node = soup.select_one(sel)
            if node and node.get_text(strip=True):
                title = node.get_text(strip=True)
                break

        page_text = soup.get_text(" ", strip=True).lower()
        in_stock = not any(marker in page_text for marker in self.OOS_MARKERS)

        price_text = None
        for sel in self.PRICE_SELECTORS:
            node = soup.select_one(sel)
            if node and "₹" in node.get_text():
                price_text = node.get_text(strip=True)
                break

        if price_text is None:
            raise ScrapeError("price element not found (layout may have changed)")

        return ScrapeResult(
            title=title or "Flipkart product",
            price=parse_price(price_text),
            in_stock=in_stock,
            currency="INR",
        )
