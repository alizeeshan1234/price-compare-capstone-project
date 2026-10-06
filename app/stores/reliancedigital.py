"""Reliance Digital search results.

The site is a single-page storefront, but the server embeds the first page of
results in `window.__INITIAL_STATE__`, so one HTML fetch is enough.
"""
import json
from typing import List, Optional

from .base import BaseStore, Offer, StoreError

_MARKER = "window.__INITIAL_STATE__="


def _state(html: str) -> Optional[dict]:
    start = html.find(_MARKER)
    if start < 0:
        return None
    try:
        state, _ = json.JSONDecoder().raw_decode(html[start + len(_MARKER):])
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


class RelianceDigitalStore(BaseStore):
    name = "reliancedigital"
    label = "Reliance Digital"
    base_url = "https://www.reliancedigital.in"

    def search_url(self, query: str) -> str:
        return f"{self.base_url}/products?q={self.q(query)}"

    def parse(self, html: str) -> List[Offer]:
        state = _state(html)
        if state is None:
            if "reliancedigital" not in html.lower():
                raise StoreError("unexpected page (no product state)")
            return []
        items = (((state.get("productListingPage") or {}).get("productlists") or {}).get("items")) or []
        offers: List[Offer] = []
        for item in items:
            if not isinstance(item, dict) or item.get("sellable") is False:
                continue
            title = item.get("name")
            price = self._price(item)
            url = item.get("url") or (f"/product/{item['slug']}" if item.get("slug") else None)
            if not (title and price and url):
                continue
            url = url.split("?")[0]
            medias = item.get("medias") or []
            image = next((m.get("url") for m in medias if isinstance(m, dict) and m.get("url")), None)
            rating = item.get("rating")
            try:
                rating = float(rating) if rating else None
            except (TypeError, ValueError):
                rating = None
            offers.append(Offer(store=self.name, title=str(title).strip(), price=price,
                                url=self.absolute(url), image=image, rating=rating or None))
        return offers

    @staticmethod
    def _price(item: dict) -> Optional[float]:
        price = item.get("price") or {}
        for key in ("effective", "marked"):
            block = price.get(key) or {}
            value = block.get("min") or block.get("max")
            if value:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return None
