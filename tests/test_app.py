import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import config, cache, main
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "MOCK_STORES", True)
    cache.init_db()
    with TestClient(main.app) as c:
        yield c


def test_home_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Find the best price" in r.text


def test_search_page_shows_comparison(client):
    r = client.get("/?q=iphone+15")
    assert r.status_code == 200
    assert "Side-by-side comparison" in r.text
    assert "Amazon" in r.text and "Flipkart" in r.text and "Snapdeal" in r.text and "Vijay Sales" in r.text
    assert "lowest" in r.text


def test_api_search_shape_and_cache(client):
    first = client.get("/api/search?q=iphone 15").json()
    assert first["query"] == "iphone 15"
    assert set(first["stores"]) == {"amazon", "flipkart", "snapdeal", "vijaysales"}
    assert all(s["ok"] and not s["cached"] for s in first["stores"].values())
    assert first["cheapest"]["price"] <= min(g["cheapest"]["price"] for g in first["groups"])
    g = first["groups"][0]
    assert g["stores"] >= 2 and set(g["by_store"]) <= set(first["stores"])

    second = client.get("/api/search?q=IPHONE   15").json()  # same query, different spacing/case
    assert all(s["cached"] for s in second["stores"].values())

    third = client.get("/api/search?q=iphone 15&refresh=1").json()
    assert all(not s["cached"] for s in third["stores"].values())


def test_health_and_recent(client):
    client.get("/api/search?q=sony headphones")
    h = client.get("/api/health").json()
    assert h["mock"] is True
    assert {s["store"] for s in h["stores"]} == {"amazon", "flipkart", "snapdeal", "vijaysales"}
    assert all(s["success_rate"] == 100.0 for s in h["stores"])
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
    page = client.get("/?q=boat airdopes")
    assert "could not be searched" in page.text


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
