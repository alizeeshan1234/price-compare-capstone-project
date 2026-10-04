import pytest
from fastapi.testclient import TestClient

from app import services
from app.scraper.base import ScrapeResult


@pytest.fixture
def client(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import database, main, scheduler

    engine = create_engine(f"sqlite:///{tmp_path}/t.db", connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    main.app.dependency_overrides[database.get_db] = override
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(services, "send_telegram", lambda text: True)
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_index_renders_empty(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Nothing tracked yet" in r.text


def test_add_view_delete_flow(client, monkeypatch):
    results = iter([ScrapeResult("Gizmo", 500.0), ScrapeResult("Gizmo", 450.0)])
    monkeypatch.setattr(services, "scrape", lambda url: next(results))

    r = client.post("/products", data={"url": "https://www.amazon.in/dp/G", "target_price": "400"}, follow_redirects=False)
    assert r.status_code == 303
    pid = int(r.headers["location"].rsplit("/", 1)[1])

    r = client.get(f"/products/{pid}")
    assert r.status_code == 200
    assert "Gizmo" in r.text and "500.00" in r.text

    r = client.post(f"/products/{pid}/check", follow_redirects=True)
    assert "450.00" in r.text

    api = client.get("/api/products").json()
    assert api[0]["current_price"] == 450.0
    assert len(client.get(f"/api/products/{pid}/history").json()) == 2

    r = client.post(f"/products/{pid}/delete", follow_redirects=True)
    assert "Nothing tracked yet" in r.text


def test_rejects_bad_input(client):
    r = client.post("/products", data={"url": "ftp://nope", "target_price": "10"}, follow_redirects=False)
    assert "URL+must+start" in r.headers["location"]
    r = client.post("/products", data={"url": "https://ok.example", "target_price": "-5"}, follow_redirects=False)
    assert "positive" in r.headers["location"]


def test_status_and_health(client):
    assert client.get("/status").status_code == 200
    h = client.get("/api/health").json()
    assert h["products"] == 0
