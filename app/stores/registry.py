"""All stores, and a concurrent search across them."""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type

from .. import config
from .base import BaseStore, Offer, StoreError
from .amazon import AmazonStore
from .flipkart import FlipkartStore
from .snapdeal import SnapdealStore
from .vijaysales import VijaySalesStore
from .croma import CromaStore
from .reliancedigital import RelianceDigitalStore
from .mock import MockStore

STORES: List[Type[BaseStore]] = [AmazonStore, FlipkartStore, SnapdealStore, VijaySalesStore, CromaStore, RelianceDigitalStore]


def active_stores() -> List[BaseStore]:
    if config.MOCK_STORES:
        return [MockStore(cls.name, cls.label) for cls in STORES]
    return [cls() for cls in STORES]


@dataclass
class StoreResult:
    store: str
    label: str
    offers: List[Offer] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


def _search_one(store: BaseStore, query: str, limit: int) -> StoreResult:
    started = time.monotonic()
    try:
        offers = store.search(query, limit)
        return StoreResult(store.name, store.label, offers, None, int((time.monotonic() - started) * 1000))
    except StoreError as exc:
        return StoreResult(store.name, store.label, [], str(exc), int((time.monotonic() - started) * 1000))
    except Exception as exc:  # noqa: BLE001  - never let one store kill the search
        return StoreResult(store.name, store.label, [], f"{exc.__class__.__name__}: {exc}",
                           int((time.monotonic() - started) * 1000))


def search_stores(query: str, stores: Optional[List[BaseStore]] = None, limit: Optional[int] = None) -> Dict[str, StoreResult]:
    """Search every store in parallel. Returns {store_name: StoreResult}."""
    stores = stores if stores is not None else active_stores()
    limit = limit or config.RESULTS_PER_STORE
    if not stores:
        return {}
    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        results = list(pool.map(lambda s: _search_one(s, query, limit), stores))
    return {r.store: r for r in results}
