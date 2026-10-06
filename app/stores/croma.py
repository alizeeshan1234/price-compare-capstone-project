"""Croma search results.

Croma's product grid is rendered in the browser from a JSON search service, so we
call that service directly. It sits behind Akamai, which rejects most datacenter
and some home IPs; the shared proxy setting (SCRAPER_API_KEY) applies here too.
"""
import json
from typing import Any, List, Optional

from .base import BaseStore, Offer, StoreError, parse_price


class CromaStore(BaseStore):
    name = "croma"
    label = "Croma"
    base_url = "https://www.croma.com"
    api_url = "https://api.croma.com/searchservices/v1/search"
    headers = {"Accept": "application/json, text/plain, */*", "Origin": "https://www.croma.com",
               "Referer": "https://www.croma.com/"}

    def search_url(self, query: str) -> str:
        # channelCode is the web storefront's numeric id (the site sends 160047 / 400049).
        return (f"{self.api_url}?currentPage=0&query={self.q_pct(query)}%3Arelevance"
                f"&fields=FULL&channel=WEB&channelCode=160047&spellOpt=DEFAULT&pageSize=12")

    def looks_blocked(self, html: str) -> bool:
        return "access denied" in html.lower() or super().looks_blocked(html)

    def parse(self, html: str) -> List[Offer]:
        try:
            data = json.loads(html)
        except ValueError:
            if self.looks_blocked(html):
                raise StoreError("blocked (Akamai access denied)")
            raise StoreError("search service returned non-JSON")
        products = data.get("products") if isinstance(data, dict) else None
        offers: List[Offer] = []
        for p in products or []:
            if not isinstance(p, dict):
                continue
            title = p.get("name") or p.get("title")
            url = p.get("url")
            price = self._price(p)
            if not (title and url and price):
                continue
            rating = p.get("averageRating") or p.get("rating")
            try:
                rating = round(float(rating), 1) if rating else None
            except (TypeError, ValueError):
                rating = None
            offers.append(Offer(store=self.name, title=str(title).strip(), price=price,
                                url=self.absolute(url), image=self._image(p), rating=rating))
        return offers

    @staticmethod
    def _price(p: dict) -> Optional[float]:
        for key in ("price", "sellingPrice", "finalPrice", "mrp"):
            block: Any = p.get(key)
            if isinstance(block, dict):
                value = block.get("value") or parse_price(block.get("formattedValue"))
            else:
                value = parse_price(str(block)) if block else None
            if value:
                return float(value)
        return None

    @staticmethod
    def _image(p: dict) -> Optional[str]:
        img = p.get("plpImage") or p.get("image")
        if isinstance(img, str) and img:
            return img
        images = p.get("images")
        if isinstance(images, list):
            for i in images:
                if isinstance(i, dict) and i.get("url"):
                    return i["url"]
        return None
