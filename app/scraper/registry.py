"""Chooses the right adapter for a URL. Adding a store = add a class here."""
from typing import List, Type
from urllib.parse import urlparse

from .. import config
from .base import BaseScraper, ScrapeResult
from .amazon import AmazonScraper
from .flipkart import FlipkartScraper
from .generic import GenericScraper
from .mock import MockScraper

# Order matters: first adapter whose `handles()` returns True wins.
SCRAPERS: List[Type[BaseScraper]] = [
    AmazonScraper,
    FlipkartScraper,
    GenericScraper,  # must stay last: it accepts everything
]


def get_scraper(url: str) -> BaseScraper:
    if config.MOCK_SCRAPER:
        return MockScraper()
    for cls in SCRAPERS:
        if cls.handles(url):
            return cls()
    return GenericScraper()


def store_name(url: str) -> str:
    """Human-readable store label for display."""
    if config.MOCK_SCRAPER:
        return "mock"
    for cls in SCRAPERS[:-1]:
        if cls.handles(url):
            return cls.name
    host = urlparse(url).netloc.lower()
    return host.replace("www.", "") or "unknown"


def scrape(url: str) -> ScrapeResult:
    return get_scraper(url).scrape(url)
