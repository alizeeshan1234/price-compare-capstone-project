"""Simulated store used when MOCK_STORES=1.

Produces believable, deterministic results for any query so the app can be
demonstrated offline. Titles are formatted differently per store on purpose, to
exercise the cross-store matching logic.
"""
import hashlib
import random
from typing import List

from .base import BaseStore, Offer

VARIANTS = [("128GB", "Black"), ("256GB", "Blue"), ("128GB", "White"), ("512GB", "Green")]
MULTIPLIER = {"amazon": 1.00, "flipkart": 0.97, "snapdeal": 1.04, "vijaysales": 0.94, "croma": 0.99, "reliancedigital": 0.96}

FORMATS = {
    "amazon": "{brand} {q} ({color}, {storage} Storage)",
    "flipkart": "{BRAND} {q} ({color}, {storage})",
    "snapdeal": "{q} {storage} {color} Smartphone",
    "vijaysales": "{brand} {q} ({storage} Storage, {color})",
    "croma": "{brand} {q} {storage} {color}",
    "reliancedigital": "{brand} {q} {storage}, {color}",
}


class MockStore(BaseStore):
    def __init__(self, name: str, label: str):
        self.name = name
        self.label = label
        self.base_url = f"https://www.{name}.example"

    def search_url(self, query: str) -> str:
        return f"{self.base_url}/search?q={self.q(query)}"

    def search(self, query: str, limit: int) -> List[Offer]:
        q = query.strip().title()
        seed = int(hashlib.md5(q.lower().encode()).hexdigest(), 16)
        rng = random.Random(seed ^ hash(self.name) & 0xFFFF)
        brand = ["Apple", "Samsung", "Sony", "OnePlus", "Boat"][seed % 5]
        base_price = 3000 + (seed % 90000)
        offers: List[Offer] = []
        fmt = FORMATS.get(self.name, "{brand} {q} {storage} {color}")
        for i, (storage, color) in enumerate(VARIANTS):
            if rng.random() < 0.25:
                continue  # each store misses some variants
            price = base_price * (1 + 0.18 * i) * MULTIPLIER.get(self.name, 1.0) * rng.uniform(0.98, 1.03)
            offers.append(Offer(
                store=self.name,
                title=fmt.format(brand=brand, BRAND=brand.upper(), q=q, color=color, storage=storage),
                price=round(price / 10) * 10 - 1,
                url=f"{self.base_url}/p/{q.lower().replace(' ', '-')}-{storage.lower()}-{color.lower()}",
                image=None,
                rating=round(rng.uniform(3.6, 4.8), 1),
            ))
        return offers[:limit]
