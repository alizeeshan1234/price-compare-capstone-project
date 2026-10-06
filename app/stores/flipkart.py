"""Flipkart search results.

Flipkart ships the product list twice: as HTML with hashed, frequently-changing
class names, and as JSON inside `window.__INITIAL_STATE__`. The JSON is far more
stable, so it is the primary source; the HTML selectors are a fallback.
"""
import json
import re
from typing import Any, Iterator, List, Optional

from bs4 import BeautifulSoup

from .base import BaseStore, Offer, parse_price, parse_rating

_STATE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});\s*</script>", re.S)


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


class FlipkartStore(BaseStore):
    name = "flipkart"
    label = "Flipkart"
    base_url = "https://www.flipkart.com"

    TITLE = ["div.RG5Slk", "div.KzDlHZ", "a.wjcEIp", "a.WKTcLC", "div._4rR01T", "a.s1Q9rs", "a.IRpwTa"]
    PRICE = ["div.hZ3P6w", "div.Nx9bqj", "div._30jeq3", "div._1_WHN1"]
    RATING = ["div.XQDdHH", "div._3LWZlK"]

    def search_url(self, query: str) -> str:
        return f"{self.base_url}/search?q={self.q(query)}"

    def looks_blocked(self, html: str) -> bool:
        # Flipkart's JS bundles contain the word "captcha" on normal pages, so only
        # treat a page as blocked when it is small and has no product data at all.
        return len(html) < 60_000 and "__INITIAL_STATE__" not in html and "data-id" not in html

    def parse(self, html: str) -> List[Offer]:
        return self._from_state(html) or self._from_html(html)

    # --- primary: embedded JSON ------------------------------------------------

    def _from_state(self, html: str) -> List[Offer]:
        m = _STATE.search(html)
        if not m:
            return []
        try:
            state = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
        offers: List[Offer] = []
        seen = set()
        for d in _walk(state):
            if not ("titles" in d and "pricing" in d and "baseUrl" in d):
                continue
            pid = d.get("id") or d.get("listingId") or d["baseUrl"]
            if pid in seen:
                continue
            seen.add(pid)
            price = self._final_price(d.get("pricing") or {})
            title = (d["titles"] or {}).get("title") or (d["titles"] or {}).get("newTitle")
            if not (price and title):
                continue
            rating = (d.get("rating") or {}).get("average")
            image = None
            images = (d.get("media") or {}).get("images") or []
            if images and images[0].get("url"):
                image = (images[0]["url"].replace("{@width}", "312").replace("{@height}", "312")
                         .replace("{@quality}", "70").replace("http://", "https://"))
            offers.append(Offer(
                store=self.name, title=title, price=float(price), url=self.absolute(d["baseUrl"]),
                image=image, rating=float(rating) if rating else None,
            ))
        return offers

    @staticmethod
    def _final_price(pricing: dict) -> Optional[float]:
        if pricing.get("finalPrice") and isinstance(pricing["finalPrice"], dict):
            v = pricing["finalPrice"].get("value")
            if v:
                return float(v)
        prices = pricing.get("prices") or []
        live = [p.get("value") for p in prices if p.get("value") and not p.get("strikeOff")]
        if live:
            return float(min(live))
        anyp = [p.get("value") for p in prices if p.get("value")]
        return float(min(anyp)) if anyp else None

    # --- fallback: HTML --------------------------------------------------------

    def _first(self, node, selectors):
        for sel in selectors:
            found = node.select_one(sel)
            if found:
                return found
        return None

    def _from_html(self, html: str) -> List[Offer]:
        soup = BeautifulSoup(html, "lxml")
        offers: List[Offer] = []
        for item in soup.select("div[data-id]"):
            title_node = self._first(item, self.TITLE)
            price_node = self._first(item, self.PRICE)
            link = item.select_one('a[href*="/p/"]')
            if not (title_node and price_node and link):
                continue
            price = parse_price(price_node.get_text())
            if not price:
                continue
            img = item.select_one("img[src]")
            rating = self._first(item, self.RATING)
            offers.append(Offer(
                store=self.name,
                title=title_node.get("title") or title_node.get_text(" ", strip=True),
                price=price,
                url=self.absolute(link["href"]),
                image=img["src"] if img else None,
                rating=parse_rating(rating.get_text()) if rating else None,
            ))
        return offers
