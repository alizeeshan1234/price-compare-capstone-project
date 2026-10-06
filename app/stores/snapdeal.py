"""Snapdeal search results (server-rendered, scraper friendly)."""
import re
from typing import List
from bs4 import BeautifulSoup

from .base import BaseStore, Offer, parse_price


class SnapdealStore(BaseStore):
    name = "snapdeal"
    label = "Snapdeal"
    base_url = "https://www.snapdeal.com"

    def search_url(self, query: str) -> str:
        return f"{self.base_url}/search?keyword={self.q(query)}&sort=rlvncy"

    def parse(self, html: str) -> List[Offer]:
        soup = BeautifulSoup(html, "lxml")
        offers: List[Offer] = []
        for item in soup.select("div.product-tuple-listing"):
            title_node = item.select_one("p.product-title")
            price_node = item.select_one("span.product-price")
            link = item.select_one("a.dp-widget-link[href]") or item.select_one("a[href]")
            if not (title_node and price_node and link):
                continue
            price = parse_price(price_node.get("data-price") or price_node.get_text())
            if not price:
                continue
            img = item.select_one("img.product-image")
            rating = None
            stars = item.select_one("div.filled-stars")
            if stars and stars.get("style"):
                m = re.search(r"width:\s*([\d.]+)%", stars["style"])
                if m:
                    rating = round(float(m.group(1)) / 20, 1)
            offers.append(Offer(
                store=self.name,
                title=title_node.get("title") or title_node.get_text(" ", strip=True),
                price=price,
                url=self.absolute(link["href"]),
                image=(img.get("src") or img.get("data-src")) if img else None,
                rating=rating,
            ))
        return offers
