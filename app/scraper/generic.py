"""Fallback adapter for any store that publishes structured product data.

Tries, in order:
  1. JSON-LD  <script type="application/ld+json"> with @type Product / Offer
  2. Open Graph / product meta tags  (product:price:amount, og:price:amount)
  3. Microdata itemprop="price"
This covers a large share of e-commerce sites without site-specific selectors.
"""
import json
from typing import Any, Iterator, Optional

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeResult, ScrapeError, parse_price


def _walk(node: Any) -> Iterator[dict]:
    """Yield every dict inside a nested JSON structure."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


class GenericScraper(BaseScraper):
    name = "generic"
    domains = ()  # never auto-selected by domain; used as the fallback

    @classmethod
    def handles(cls, url: str) -> bool:
        return True

    def parse(self, html: str, url: str) -> ScrapeResult:
        soup = BeautifulSoup(html, "lxml")
        result = self._from_json_ld(soup) or self._from_meta(soup) or self._from_microdata(soup)
        if result is None:
            raise ScrapeError("no structured price data found on page")
        return result

    # --- strategies -------------------------------------------------------

    def _from_json_ld(self, soup: BeautifulSoup) -> Optional[ScrapeResult]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            product = None
            for d in _walk(data):
                t = d.get("@type")
                types = t if isinstance(t, list) else [t]
                if "Product" in types:
                    product = d
                    break
            if not product:
                continue
            offers = product.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = offers.get("price") or offers.get("lowPrice")
            if price is None:
                continue
            availability = str(offers.get("availability", "")).lower()
            in_stock = "outofstock" not in availability and "soldout" not in availability
            return ScrapeResult(
                title=str(product.get("name") or "Product").strip(),
                price=parse_price(str(price)),
                in_stock=in_stock,
                currency=str(offers.get("priceCurrency") or "INR"),
            )
        return None

    def _from_meta(self, soup: BeautifulSoup) -> Optional[ScrapeResult]:
        price_tag = soup.find("meta", property="product:price:amount") or soup.find(
            "meta", property="og:price:amount"
        )
        if not price_tag or not price_tag.get("content"):
            return None
        currency_tag = soup.find("meta", property="product:price:currency") or soup.find(
            "meta", property="og:price:currency"
        )
        title_tag = soup.find("meta", property="og:title")
        availability_tag = soup.find("meta", property="product:availability")
        in_stock = True
        if availability_tag and "out" in str(availability_tag.get("content", "")).lower():
            in_stock = False
        return ScrapeResult(
            title=(title_tag.get("content") if title_tag else None) or "Product",
            price=parse_price(price_tag["content"]),
            in_stock=in_stock,
            currency=(currency_tag.get("content") if currency_tag else None) or "INR",
        )

    def _from_microdata(self, soup: BeautifulSoup) -> Optional[ScrapeResult]:
        price_node = soup.find(attrs={"itemprop": "price"})
        if not price_node:
            return None
        price_text = price_node.get("content") or price_node.get_text(strip=True)
        name_node = soup.find(attrs={"itemprop": "name"})
        currency_node = soup.find(attrs={"itemprop": "priceCurrency"})
        return ScrapeResult(
            title=(name_node.get_text(strip=True) if name_node else None) or "Product",
            price=parse_price(price_text),
            in_stock=True,
            currency=(currency_node.get("content") if currency_node else None) or "INR",
        )
