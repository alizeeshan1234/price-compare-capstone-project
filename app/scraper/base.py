"""Common scraper interface and helpers shared by all store adapters."""
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests

from .. import config


class ScrapeError(Exception):
    """Raised when a page could be fetched but the price could not be extracted."""


class FetchError(Exception):
    """Raised when the page could not be fetched at all."""


@dataclass
class ScrapeResult:
    title: str
    price: float
    in_stock: bool = True
    currency: str = "INR"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml",
}

_PRICE_RE = re.compile(r"[\d][\d,]*(?:\.\d+)?")


def parse_price(text: str) -> float:
    """Turn strings like '₹1,23,456.00' or '$1,299' into a float."""
    if text is None:
        raise ScrapeError("empty price text")
    match = _PRICE_RE.search(text)
    if not match:
        raise ScrapeError(f"no number found in price text: {text!r}")
    return float(match.group(0).replace(",", ""))


def detect_currency(text: str, default: str = "INR") -> str:
    if not text:
        return default
    if "₹" in text or "Rs" in text or "INR" in text:
        return "INR"
    if "$" in text or "USD" in text:
        return "USD"
    if "€" in text or "EUR" in text:
        return "EUR"
    if "£" in text or "GBP" in text:
        return "GBP"
    return default


def fetch_html(url: str, retries: Optional[int] = None) -> str:
    """GET a page with retries and exponential backoff."""
    retries = config.MAX_RETRIES if retries is None else retries
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT_SECONDS)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (429, 503):
                last_exc = FetchError(f"rate limited or blocked (HTTP {resp.status_code})")
            else:
                raise FetchError(f"HTTP {resp.status_code}")
        except requests.RequestException as exc:
            last_exc = FetchError(str(exc))
        time.sleep(2 ** attempt)
    raise last_exc or FetchError("unknown fetch error")


class BaseScraper:
    """Every store adapter subclasses this and implements `parse`."""

    name: str = "base"
    domains: tuple = ()

    @classmethod
    def handles(cls, url: str) -> bool:
        return any(d in url for d in cls.domains)

    def parse(self, html: str, url: str) -> ScrapeResult:
        raise NotImplementedError

    def scrape(self, url: str) -> ScrapeResult:
        html = fetch_html(url)
        return self.parse(html, url)
