import pytest
from fastapi.testclient import TestClient

ALL_STORES = {"amazon", "flipkart", "snapdeal", "vijaysales", "croma", "reliancedigital"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import config, cache, main
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "MOCK_STORES", True)
    monkeypatch.setattr(config, "HOSTED", False)
    monkeypatch.setattr(config, "CRON_SECRET", "")
    cache.init_db()
    with TestClient(main.app) as c:
        yield c


def test_home_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Find the best price" in r.text


def test_search_page_renders_server_side_with_sync(client):
    r = client.get("/?q=iphone+15&sync=1")
    assert r.status_code == 200
    assert "Side-by-side comparison" in r.text
    for label in ("Amazon", "Flipkart", "Snapdeal", "Vijay Sales", "Croma", "Reliance Digital"):
        assert label in r.text
    assert "lowest" in r.text
    assert "progress-bar" not in r.text


def test_search_page_is_progressive_until_cached(client):
    shell = client.get("/?q=iphone+15")
    assert shell.status_code == 200
    assert "progress-bar" in shell.text and "/fragment/store/" in shell.text
    assert "Side-by-side comparison" not in shell.text
    assert 'id="col-reliancedigital"' in shell.text

    # the browser fetches each store separately...
    results = {}
    for name in ALL_STORES:
        r = client.get(f"/fragment/store/{name}?q=iphone+15")
        assert r.status_code == 200
        data = r.json()
        assert "<h3>" in data["html"] and data["result"]["ok"] and data["result"]["offers"]
        results[name] = data["result"]

    # ...then asks for the comparison built from what came back
    compare = client.post("/fragment/compare", json={"query": "iphone 15", "stores": results})
    assert compare.status_code == 200
    assert "Side-by-side comparison" in compare.text and "You save" in compare.text
    assert "30-day trend" in compare.text

    # once every store is cached, the page renders in one go again
    full = client.get("/?q=iphone+15")
    assert "Side-by-side comparison" in full.text and "progress-bar" not in full.text
    assert "(cached)" in full.text
    # a refresh goes back to progressive loading
    assert "progress-bar" in client.get("/?q=iphone+15&refresh=1").text


def test_fragment_validation(client):
    assert client.get("/fragment/store/nope?q=iphone").status_code == 404
    assert client.get("/fragment/store/amazon?q=a").status_code == 422
    assert client.post("/fragment/compare", json={"query": "x"}).status_code == 400


def test_api_search_shape_and_cache(client):
    first = client.get("/api/search?q=iphone 15").json()
    assert first["query"] == "iphone 15"
    assert set(first["stores"]) == ALL_STORES
    assert all(s["ok"] and not s["cached"] for s in first["stores"].values())
    assert first["cheapest"]["price"] <= min(g["cheapest"]["price"] for g in first["groups"])
    g = first["groups"][0]
    assert g["stores"] >= 2 and set(g["by_store"]) <= set(first["stores"])
    assert "history" in g and g["low30"] == g["cheapest"]["price"] and g["at_low"] is True

    second = client.get("/api/search?q=IPHONE   15").json()  # same query, different spacing/case
    assert all(s["cached"] for s in second["stores"].values())

    third = client.get("/api/search?q=iphone 15&refresh=1").json()
    assert all(not s["cached"] for s in third["stores"].values())


def test_health_and_recent(client):
    client.get("/api/search?q=sony headphones")
    h = client.get("/api/health").json()
    assert h["mock"] is True
    assert {s["store"] for s in h["stores"]} == ALL_STORES
    assert all(s["success_rate"] == 100.0 for s in h["stores"])
    assert h["history"]["points"] > 0 and h["history"]["days"] == 1
    assert "sony headphones" in client.get("/").text


def test_failed_store_does_not_break_search(client, monkeypatch):
    from app.stores import registry
    from app.stores.base import StoreError

    class Broken(registry.MockStore):
        def search(self, query, limit):
            raise StoreError("HTTP 503 (blocked / rate limited)")

    good = registry.MockStore("flipkart", "Flipkart")
    monkeypatch.setattr("app.search.active_stores", lambda: [Broken("amazon", "Amazon"), good])
    data = client.get("/api/search?q=boat airdopes&refresh=1").json()
    assert data["stores"]["amazon"]["ok"] is False
    assert "blocked" in data["stores"]["amazon"]["error"]
    assert data["stores"]["flipkart"]["count"] > 0
    page = client.get("/?q=boat airdopes&sync=1")
    assert "could not be searched" in page.text
    # the progressive path reports the failure in the column and the comparison
    frag = client.get("/fragment/store/amazon?q=boat airdopes&refresh=1").json()
    assert frag["result"]["ok"] is False and "Unavailable" in frag["html"]


def test_query_validation(client):
    assert client.get("/api/search?q=a").status_code == 422
    assert "Side-by-side" not in client.get("/?q=a").text


def test_lowest_price_ignores_accessories(client, monkeypatch):
    from app.stores import registry
    from app.stores.base import Offer

    class Shop(registry.MockStore):
        def search(self, query, limit):
            return [Offer(self.name, "Sparkly Case Compatible with iPhone 15", 499.0, "https://x/case"),
                    Offer(self.name, "Apple iPhone 15 (128 GB) Black", 66999.0, "https://x/phone")]

    monkeypatch.setattr("app.search.active_stores", lambda: [Shop("vijaysales", "Vijay Sales")])
    data = client.get("/api/search?q=iphone 15&refresh=1").json()
    assert data["cheapest"]["price"] == 66999.0
    assert "Case" not in data["cheapest"]["title"]


# ------------------------------------------------------------------ price history

def test_price_history_tracks_daily_lows_and_sparkline(client, monkeypatch):
    from app import cache
    from app.stores.base import Offer

    # Seed three earlier days for the listing the mock store will return today.
    today = client.get("/api/search?q=pixel 9").json()
    offer = today["groups"][0]["cheapest"]
    key = Offer(**offer).key
    with cache.connect() as c:
        for day, price in (("2026-09-20", 52000.0), ("2026-09-25", 50500.0), ("2026-10-01", 51000.0)):
            c.execute("INSERT INTO price_history (key, store, title, price, url, day, seen_at) VALUES (?,?,?,?,?,?,?)",
                      (key, offer["store"], offer["title"], price, offer["url"], day, day + "T00:00:00"))
    hist = client.get("/api/history?q=pixel 9").json()
    product = hist["products"][0]
    assert [h["price"] for h in product["history"]][:3] == [52000.0, 50500.0, 51000.0]
    assert len(product["history"]) == 4 and product["low30"] == min(50500.0, offer["price"])
    page = client.get("/?q=pixel 9")  # fully cached -> server-rendered with sparkline
    assert '<svg class="spark' in page.text
    assert ("Lowest in 4 days" in page.text) == (offer["price"] <= 50500.0)
    # same day, lower price -> the day's point is updated, not duplicated
    cache.record_prices([Offer(**dict(offer, price=offer["price"] - 100))])
    stats = cache.history_stats()
    assert stats["listings"] >= 1
    assert cache.price_history([key])[key][-1][1] == offer["price"] - 100


def test_canonical_listing_keys():
    from app.stores.base import canonical_url
    assert canonical_url("https://www.amazon.in/Apple-iPhone-15/dp/B0CHX1W1XY/ref=sr_1_1?keywords=x") == "https://www.amazon.in/dp/B0CHX1W1XY"
    assert canonical_url("https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4?pid=MOBGTAGPTB3VS24W&lid=LSTM&marketplace=FLIPKART") == "https://www.flipkart.com/apple-iphone-15/p/itm6ac6485515ae4?pid=MOBGTAGPTB3VS24W"
    assert canonical_url("https://www.croma.com/apple-iphone-15/p/300680/?utm=x") == "https://www.croma.com/apple-iphone-15/p/300680"


# ------------------------------------------------------------------------ alerts

def test_alert_lifecycle(client, monkeypatch):
    from app import cache
    from app import alerts as alerts_mod

    data = client.get("/api/search?q=galaxy s24").json()
    best = data["groups"][0]["cheapest"]
    page = client.get("/?q=galaxy s24")
    assert "🔔 Alert" in page.text and 'name="target_price"' in page.text

    r = client.post("/alerts", data={"email": "Student@Example.com", "query": "galaxy s24", "title": data["groups"][0]["title"],
                                     "key": "{}:{}".format(best["store"], best["url"]), "store": best["store"], "url": best["url"],
                                     "target_price": best["price"] - 1, "current_price": best["price"]}, follow_redirects=False)
    assert r.status_code == 303 and "email=student%40example.com" in r.headers["location"].replace("@", "%40")
    listing = client.get("/alerts?email=student@example.com&created=1")
    assert "Alert saved" in listing.text and "Watching" in listing.text and "not configured" in listing.text

    # price unchanged -> still watching, last price recorded
    sent = []
    summary = alerts_mod.check_alerts(send=lambda a, p, s: sent.append((a["email"], p)) or "log")
    assert summary["checked"] == 1 and summary["triggered"] == 0 and not sent
    a = cache.list_alerts("student@example.com")[0]
    assert a["last_price"] == best["price"] and a["triggered_at"] is None

    # price drops below the target -> notified once, then no longer pending
    cheaper = client.get("/api/search?q=galaxy s24").json()
    from app.search import build_response, store_result_from_dict
    def cheaper_search(q):
        stores = {}
        for name, s in cheaper["stores"].items():
            s = dict(s, offers=[dict(o, price=o["price"] * 0.5) for g in cheaper["groups"] for o in g["offers"] if o["store"] == name])
            stores[name] = store_result_from_dict(name, s)
        return build_response(q, stores)
    summary = alerts_mod.check_alerts(send=lambda a, p, s: sent.append((a["email"], p)) or "log", search=cheaper_search)
    assert summary["triggered"] == 1 and sent and sent[0][0] == "student@example.com" and sent[0][1] < best["price"]
    assert cache.pending_alerts() == []
    done = client.get("/alerts?email=student@example.com")
    assert "Triggered at" in done.text

    # API runner is open locally, protected when a secret is set
    assert client.post("/api/alerts/run").json()["pending"] == 0
    from app import config
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    assert client.get("/api/alerts/run").status_code == 403
    assert client.get("/api/alerts/run", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/alerts/run?token=s3cret").status_code == 200

    # delete
    r = client.post(f"/alerts/{a['id']}/delete", data={"email": "student@example.com"}, follow_redirects=False)
    assert r.status_code == 303 and cache.list_alerts("student@example.com") == []


def test_alert_falls_back_to_same_product_in_another_store(client):
    from app import alerts as alerts_mod
    from app.search import run_search
    data = client.get("/api/search?q=oneplus 12").json()
    g = data["groups"][0]
    assert g["stores"] >= 2
    watched = g["cheapest"]
    alert = {"key": "flipkart:https://gone.example/listing", "title": watched["title"], "target_price": 1}
    found = alerts_mod.find_offer(alert, run_search("oneplus 12"))
    assert found is not None and found.price == watched["price"]
