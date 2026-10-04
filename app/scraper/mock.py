"""Mock adapter used when MOCK_SCRAPER=1.

Generates a stable-but-noisy price per URL so demos work offline and
development never hits real sites.
"""
import hashlib
import random
from urllib.parse import urlparse

from .base import BaseScraper, ScrapeResult


class MockScraper(BaseScraper):
    name = "mock"
    domains = ()

    @classmethod
    def handles(cls, url: str) -> bool:
        return True

    def scrape(self, url: str) -> ScrapeResult:
        seed = int(hashlib.md5(url.encode()).hexdigest(), 16)
        base = 500 + (seed % 50000)
        rng = random.Random()
        price = round(base * rng.uniform(0.85, 1.10), 2)
        parts = [seg for seg in urlparse(url).path.split("/") if seg and seg.lower() not in ("dp", "p", "product", "item")]
        slug = parts[0] if parts else "demo-product"
        return ScrapeResult(
            title=f"Demo: {slug.replace('-', ' ').title()}",
            price=price,
            in_stock=rng.random() > 0.05,
            currency="INR",
        )
