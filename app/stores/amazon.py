"""Amazon.in search results."""
from typing import List, Optional
from bs4 import BeautifulSoup

from .base import BaseStore, Offer, parse_price, parse_rating


class AmazonStore(BaseStore):
    name = "amazon"
    label = "Amazon"
    base_url = "https://www.amazon.in"

    def search_url(self, query: str) -> str:
        return f"{self.base_url}/s?k={self.q(query)}"

    @staticmethod
    def _title(item) -> Optional[str]:
        """Amazon moves the title around; try the stable sources in order."""
        h2 = item.select_one("h2")
        if h2 is not None:
            if h2.get("aria-label"):
                return h2["aria-label"].strip()
            text = h2.get_text(" ", strip=True)
            if len(text) > 12:  # a lone brand name ("Apple") is not the title
                return text
        img = item.select_one("img.s-image[alt]")
        if img and len(img["alt"].strip()) > 12:
            return img["alt"].strip()
        link = item.select_one("a.s-line-clamp-3, a.s-line-clamp-2, a.s-line-clamp-4")
        if link and link.get_text(strip=True):
            return link.get_text(" ", strip=True)
        return (h2.get_text(" ", strip=True) if h2 is not None else None) or None

    def parse(self, html: str) -> List[Offer]:
        soup = BeautifulSoup(html, "lxml")
        offers: List[Offer] = []
        for item in soup.select('div[data-component-type="s-search-result"]'):
            if item.select_one(".puis-sponsored-label-text, span.s-label-popover-default"):
                continue  # skip sponsored placements
            title = self._title(item)
            link = item.select_one('h2 a[href]') or item.select_one('a[href*="/dp/"]') or item.select_one("a.a-link-normal[href]")
            price_node = item.select_one("span.a-price span.a-offscreen")
            if not (title and link and price_node):
                continue
            price = parse_price(price_node.get_text())
            if not price:
                continue
            img = item.select_one("img.s-image")
            rating = item.select_one("span.a-icon-alt")
            offers.append(Offer(
                store=self.name,
                title=title,
                price=price,
                url=self.absolute(link["href"]),
                image=img["src"] if img and img.get("src") else None,
                rating=parse_rating(rating.get_text()) if rating else None,
            ))
        return offers
