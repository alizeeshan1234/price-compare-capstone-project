"""Search service: cache -> stores -> grouping -> response."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import cache, config
from .matching import Group, group_offers
from .stores import Offer, StoreResult, active_stores, search_stores


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

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "stores": {
                name: {"label": r.label, "ok": r.ok, "error": r.error, "count": len(r.offers),
                       "duration_ms": r.duration_ms, "cached": r.cached}
                for name, r in self.stores.items()
            },
            "cheapest": self.cheapest.to_dict() if self.cheapest else None,
            "groups": [g.to_dict() for g in self.groups],
        }


def run_search(query: str, refresh: bool = False) -> SearchResponse:
    query = " ".join(query.split())
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
        live = search_stores(query, to_fetch, config.RESULTS_PER_STORE)
        for name, r in live.items():
            results[name] = r
            cache.log_search(query, name, r.ok, len(r.offers), r.duration_ms, r.error)
            if r.ok:
                cache.set_cached(query, name, [o.to_dict() for o in r.offers])

    ordered = {s.name: results[s.name] for s in stores}
    offers = [o for r in ordered.values() for o in r.offers]
    return SearchResponse(query=query, stores=ordered, groups=group_offers(offers, query=query), offers=offers)
