"""Search service: cache -> stores -> grouping -> response.

Two entry points:
  run_search(query)             everything at once (API, server-rendered page)
  search_store(query, store)    one store, used by the progressive page which
                                fetches each store separately and then calls
                                build_response() with what came back.
"""
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from . import cache, config
from .matching import Group, group_offers
from .stores import Offer, StoreResult, active_stores, search_stores
from .stores.base import BaseStore
from .stores.registry import _search_one

HISTORY_DAYS = 30


@dataclass
class SearchResponse:
    query: str
    stores: Dict[str, StoreResult]
    groups: List[Group]
    offers: List[Offer] = field(default_factory=list)

    @property
    def cheapest(self) -> Optional[Offer]:
        """Cheapest offer among the best-matching, non-accessory products.

        Falls back to the cheapest of anything only when nothing matched well.
        """
        candidates = [g for g in self.groups if not g.accessory]
        if candidates:
            top = max(g.relevance for g in candidates)
            best = [g for g in candidates if g.relevance >= top - 1e-9]
            return min((g.cheapest for g in best), key=lambda o: o.price)
        return min(self.offers, key=lambda o: o.price) if self.offers else None

    @property
    def ok_stores(self) -> List[StoreResult]:
        return [r for r in self.stores.values() if r.ok]

    @property
    def failed_stores(self) -> List[StoreResult]:
        return [r for r in self.stores.values() if not r.ok]

    @property
    def tracked_groups(self) -> int:
        return sum(1 for g in self.groups if g.history_days > 1)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "stores": {name: store_result_dict(r) for name, r in self.stores.items()},
            "cheapest": self.cheapest.to_dict() if self.cheapest else None,
            "groups": [g.to_dict() for g in self.groups],
        }


def store_result_dict(r: StoreResult, with_offers: bool = False) -> dict:
    d = {"label": r.label, "ok": r.ok, "error": r.error, "count": len(r.offers),
         "duration_ms": r.duration_ms, "cached": r.cached}
    if with_offers:
        d["offers"] = [o.to_dict() for o in r.offers]
    return d


def store_result_from_dict(name: str, d: dict) -> StoreResult:
    """Inverse of store_result_dict(with_offers=True); used by the progressive page."""
    offers = []
    for o in d.get("offers") or []:
        try:
            offers.append(Offer(**{k: o.get(k) for k in ("store", "title", "price", "url", "currency", "image", "rating")
                                   if o.get(k) is not None}))
        except TypeError:
            continue
    error = d.get("error")
    return StoreResult(name, d.get("label") or name, offers, str(error) if error else None,
                       int(d.get("duration_ms") or 0), bool(d.get("cached")))


def _clean(query: str) -> str:
    return " ".join(query.split())


def _record(query: str, r: StoreResult) -> None:
    """Side effects of a live (non-cached) store result: log, cache, price history."""
    cache.log_search(query, r.store, r.ok, len(r.offers), r.duration_ms, r.error)
    if r.ok:
        cache.set_cached(query, r.store, [o.to_dict() for o in r.offers])
        cache.record_prices(r.offers)


def _store_by_name(name: str) -> Optional[BaseStore]:
    return next((s for s in active_stores() if s.name == name), None)


def search_store(query: str, name: str, refresh: bool = False) -> Optional[StoreResult]:
    """Search a single store (cache first). None if the store does not exist."""
    query = _clean(query)
    store = _store_by_name(name)
    if store is None:
        return None
    if not refresh:
        cached = cache.get_cached(query).get(name)
        if cached is not None:
            return StoreResult(name, store.label, [Offer(**d) for d in cached], None, 0, cached=True)
    r = _search_one(store, query, config.RESULTS_PER_STORE)
    _record(query, r)
    return r


def attach_history(groups: Iterable[Group], days: int = HISTORY_DAYS) -> None:
    """Fill Group.history / Group.low30 from the price-history table.

    A product's price on a day is the lowest price any of its listings had that day.
    """
    groups = list(groups)
    hist = cache.price_history([o.key for g in groups for o in g.offers], days=days)
    for g in groups:
        by_day: Dict[str, float] = {}
        for o in g.offers:
            for day, price in hist.get(o.key, []):
                by_day[day] = min(price, by_day.get(day, price))
        g.history = sorted(by_day.items())
        g.low30 = min((p for _, p in g.history), default=None)


def build_response(query: str, results: Dict[str, StoreResult]) -> SearchResponse:
    """Group a set of per-store results (in registry order) into a response."""
    query = _clean(query)
    order = [s.name for s in active_stores()]
    ordered = {n: results[n] for n in order if n in results}
    ordered.update({n: r for n, r in results.items() if n not in ordered})
    offers = [o for r in ordered.values() for o in r.offers]
    groups = group_offers(offers, query=query)
    attach_history(groups)
    return SearchResponse(query=query, stores=ordered, groups=groups, offers=offers)


def fully_cached(query: str) -> bool:
    """True when every active store has a fresh cache entry for the query."""
    cached = cache.get_cached(_clean(query))
    return all(s.name in cached for s in active_stores())


def run_search(query: str, refresh: bool = False) -> SearchResponse:
    query = _clean(query)
    stores = active_stores()
    cached = {} if refresh else cache.get_cached(query)

    results: Dict[str, StoreResult] = {}
    to_fetch = []
    for s in stores:
        if s.name in cached:
            offers = [Offer(**d) for d in cached[s.name]]
            results[s.name] = StoreResult(s.name, s.label, offers, None, 0, cached=True)
        else:
            to_fetch.append(s)

    if to_fetch:
        for name, r in search_stores(query, to_fetch, config.RESULTS_PER_STORE).items():
            results[name] = r
            _record(query, r)

    return build_response(query, results)
