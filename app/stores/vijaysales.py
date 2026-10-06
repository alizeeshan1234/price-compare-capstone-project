"""Vijay Sales search results.

The website renders its product grid in the browser from the Unbxd search service.
We call the same JSON endpoint the site's own frontend uses. The site key and API
key are published in the page's hidden inputs; they are embedded here as defaults
and re-read from the homepage if the service ever rejects them.
"""
import re
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

from .. import config
from .base import BaseStore, Offer, StoreError, HEADERS

DEFAULT_KEYS = ("bb8ef7667d38c04e8a81c80f4a43a998", "ss-unbxd-aapac-prod-vijaysales-magento33881704883825")
_keys: Optional[Tuple[str, str]] = None


def _discover_keys() -> Tuple[str, str]:
    """Read the Unbxd keys from the homepage's hidden inputs."""
    html = requests.get("https://www.vijaysales.com/", headers=HEADERS, timeout=config.REQUEST_TIMEOUT).text
    soup = BeautifulSoup(html, "lxml")
    api = soup.find("input", id="unbxd-apiKey")
    site = soup.find("input", id="unbxd-siteKey")
    if not (api and site and api.get("value") and site.get("value")):
        raise StoreError("could not find search keys on vijaysales.com")
    return api["value"], site["value"]


class VijaySalesStore(BaseStore):
    name = "vijaysales"
    label = "Vijay Sales"
    base_url = "https://www.vijaysales.com"

    def search_url(self, query: str) -> str:
        return f"{self.base_url}/search/{self.q(query).replace('+', '-')}"

    def api_url(self, keys: Tuple[str, str]) -> str:
        return f"https://search.unbxd.io/{keys[0]}/{keys[1]}/search"

    def search(self, query: str, limit: int) -> List[Offer]:
        global _keys
        keys = _keys or DEFAULT_KEYS
        data = self._call(query, limit, keys)
        if data is None:  # keys rejected: rediscover once
            _keys = _discover_keys()
            data = self._call(query, limit, _keys)
            if data is None:
                raise StoreError("search service rejected the request")
        return self.parse_json(data)[:limit]

    def _call(self, query: str, limit: int, keys: Tuple[str, str]) -> Optional[dict]:
        headers = dict(HEADERS, Accept="application/json", Origin=self.base_url, Referer=self.base_url + "/")
        try:
            r = requests.get(self.api_url(keys), params={"q": query, "rows": limit, "page": 1},
                             headers=headers, timeout=config.REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise StoreError(f"network error: {exc.__class__.__name__}")
        if r.status_code in (401, 403):
            return None
        if r.status_code != 200:
            raise StoreError(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise StoreError("search service returned non-JSON")

    def parse(self, html: str) -> List[Offer]:  # HTML path is unused for this store
        return []

    def parse_json(self, data: dict) -> List[Offer]:
        offers: List[Offer] = []
        for p in (data.get("response") or {}).get("products") or []:
            title = p.get("title") or p.get("name")
            url = p.get("productUrl")
            price = self._price(p)
            if not (title and url and price):
                continue
            images = p.get("imageUrl")
            image = images[0] if isinstance(images, list) and images else (images if isinstance(images, str) else None)
            rating = p.get("rating") or p.get("averageRating")
            offers.append(Offer(
                store=self.name, title=str(title).strip(), price=price, url=self.absolute(url),
                image=image, rating=float(rating) if rating else None,
            ))
        return offers

    @staticmethod
    def _price(p: dict) -> Optional[float]:
        """Prefer a selling/offer price, otherwise the list price."""
        for key in ("sellingPrice", "specialPrice", "finalPrice", "offerPrice"):
            v = p.get(key)
            if v not in (None, "", 0, "0"):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        # City-specific selling prices (cityId_<n>_sellingPrice_unx_d): take the lowest.
        city = [float(v) for k, v in p.items() if re.fullmatch(r"cityId_\d+_sellingPrice_unx_d", k) and v]
        if city:
            return min(city)
        try:
            return float(p.get("price")) if p.get("price") else None
        except (TypeError, ValueError):
            return None
