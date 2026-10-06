"""Price-drop alerts: re-search watched products and notify when a target is hit.

Run from the command line (`python -m app.alerts`), from `make alerts`, or by the
scheduler via POST /api/alerts/run (Vercel Cron calls it once a day).
"""
import logging
from collections import defaultdict
from typing import Callable, Dict, List, Optional

from . import cache
from .matching import normalize, similarity, specs_compatible, spec_tokens
from .notifier import send_price_drop
from .search import run_search, SearchResponse
from .stores import STORES, Offer

log = logging.getLogger(__name__)
LABELS = {cls.name: cls.label for cls in STORES}


def find_offer(alert: dict, response: SearchResponse) -> Optional[Offer]:
    """The exact listing that was watched, else the cheapest listing of the same product."""
    for o in response.offers:
        if o.key == alert["key"]:
            return o
    want = normalize(alert["title"])
    want_specs = spec_tokens(want)
    best, best_score = None, 0.0
    for g in response.groups:
        if g.accessory:
            continue
        for o in g.offers:
            have = normalize(o.title)
            if not specs_compatible(want_specs, spec_tokens(have)):
                continue
            score = similarity(want, have)
            if score >= 0.5 and (score > best_score or (score == best_score and best and o.price < best.price)):
                best, best_score = o, score
    return best


def check_alerts(send: Callable[[dict, float, str], str] = send_price_drop,
                 search: Callable[[str], SearchResponse] = lambda q: run_search(q, refresh=True)) -> dict:
    pending = cache.pending_alerts()
    by_query: Dict[str, List[dict]] = defaultdict(list)
    for a in pending:
        by_query[a["query"]].append(a)
    summary = {"pending": len(pending), "queries": len(by_query), "checked": 0, "triggered": 0,
               "missing": 0, "errors": 0, "details": []}
    for query, alerts in by_query.items():
        try:
            response = search(query)
        except Exception as exc:  # noqa: BLE001 - one bad query must not stop the rest
            log.exception("alert check failed for %r", query)
            summary["errors"] += 1
            summary["details"].append({"query": query, "error": str(exc)})
            continue
        for a in alerts:
            offer = find_offer(a, response)
            summary["checked"] += 1
            if offer is None:
                cache.alert_checked(a["id"], None)
                summary["missing"] += 1
                summary["details"].append({"id": a["id"], "title": a["title"], "status": "not listed"})
                continue
            if offer.price <= a["target_price"]:
                via = send(a, offer.price, LABELS.get(offer.store, offer.store))
                cache.alert_triggered(a["id"], offer.price, via)
                summary["triggered"] += 1
                summary["details"].append({"id": a["id"], "title": a["title"], "status": "triggered",
                                           "price": offer.price, "store": offer.store, "via": via})
            else:
                cache.alert_checked(a["id"], offer.price)
                summary["details"].append({"id": a["id"], "title": a["title"], "status": "watching",
                                           "price": offer.price, "target": a["target_price"]})
    return summary


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cache.init_db()
    print(json.dumps(check_alerts(), indent=2))
