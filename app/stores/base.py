"""Shared pieces for every store adapter."""
import re
import time
from dataclasses import dataclass, asdict
from typing import List, Optional
from urllib.parse import quote_plus

import requests

from .. import config


class StoreError(Exception):
    """Fetch failed or the page could not be parsed."""


@dataclass
class Offer:
    store: str
    title: str
    price: float
    url: str
    currency: str = "INR"
    image: Optional[str] = None
    rating: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def parse_price(text: Optional[str]) -> Optional[float]:
    """'₹1,29,900.00' -> 129900.0 ; returns None if no number."""
    if not text:
        return None
    m = _NUM.search(text)
    return float(m.group(0).replace(",", "")) if m else None


def parse_rating(text: Optional[str]) -> Optional[float]:
    """'4.3 out of 5 stars' -> 4.3"""
    if not text:
        return None
    m = re.search(r"(\d(?:\.\d)?)", text)
    return float(m.group(1)) if m else None


def proxy_mode() -> str:
    """'api' (ScraperAPI), 'proxy' (plain HTTP proxy) or '' (direct)."""
    if config.SCRAPER_API_KEY:
        return "api"
    if config.SCRAPER_PROXY_URL:
        return "proxy"
    return ""


def _get(url: str) -> requests.Response:
    """One HTTP GET, routed through the configured proxy if any."""
    mode = proxy_mode()
    if mode == "api":
        return requests.get(
            "https://api.scraperapi.com/",
            params={"api_key": config.SCRAPER_API_KEY, "url": url, "country_code": config.PROXY_COUNTRY},
            headers={"Accept-Language": HEADERS["Accept-Language"]},
            timeout=config.PROXY_TIMEOUT,
        )
    if mode == "proxy":
        proxies = {"http": config.SCRAPER_PROXY_URL, "https": config.SCRAPER_PROXY_URL}
        return requests.get(url, headers=HEADERS, proxies=proxies, timeout=config.PROXY_TIMEOUT)
    return requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT)


def fetch_html(url: str) -> str:
    last = None
    retries = 1 if proxy_mode() == "api" else config.MAX_RETRIES  # the API retries internally
    for attempt in range(retries + 1):
        try:
            r = _get(url)
            if r.status_code == 200:
                return r.text
            blocked = r.status_code in (403, 429, 500, 503, 529)
            last = StoreError(f"HTTP {r.status_code}" + (" (blocked / rate limited)" if blocked else ""))
        except requests.RequestException as exc:
            last = StoreError(f"network error: {exc.__class__.__name__}")
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last or StoreError("unknown error")


class BaseStore:
    """Subclass per store: set name/label/base_url and implement search_url + parse."""

    name: str = "base"
    label: str = "Base"
    base_url: str = ""

    def search_url(self, query: str) -> str:
        raise NotImplementedError

    def parse(self, html: str) -> List[Offer]:
        raise NotImplementedError

    def search(self, query: str, limit: int) -> List[Offer]:
        html = fetch_html(self.search_url(query))
        offers = self.parse(html)
        if not offers and self.looks_blocked(html):
            raise StoreError("blocked (CAPTCHA or bot check page)")
        return offers[:limit]

    def looks_blocked(self, html: str) -> bool:
        lower = html.lower()
        return "captcha" in lower or "robot check" in lower or "access denied" in lower

    def absolute(self, href: Optional[str]) -> str:
        if not href:
            return self.base_url
        if href.startswith("http"):
            return href
        return self.base_url.rstrip("/") + "/" + href.lstrip("/")

    @staticmethod
    def q(query: str) -> str:
        return quote_plus(query.strip())
