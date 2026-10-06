"""PriceCompare: search once, compare prices across stores side by side."""
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import FastAPI, Form, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import cache, config
from .alerts import check_alerts
from .notifier import email_enabled
from .search import build_response, fully_cached, run_search, search_store, store_result_dict, store_result_from_dict
from .stores import STORES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    cache.init_db()
    yield


def _ensure_db() -> None:
    """Serverless hosts may skip lifespan events; make the tables exist regardless."""
    try:
        cache.init_db()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("could not initialise cache database")


_ensure_db()


app = FastAPI(title="PriceCompare", version="1.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def money(value: Optional[float], code: str = "INR") -> str:
    if value is None:
        return "—"
    return f"{SYMBOLS.get(code, code + ' ')}{value:,.0f}"


def sparkline(history: List[Tuple[str, float]], width: int = 84, height: int = 24) -> Markup:
    """Inline SVG line of daily prices; the last point is highlighted."""
    if len(history) < 2:
        return Markup("")
    prices = [p for _, p in history]
    lo, hi = min(prices), max(prices)
    span = (hi - lo) or 1.0
    pad = 3
    pts = []
    for i, p in enumerate(prices):
        x = pad + i * (width - 2 * pad) / (len(prices) - 1)
        y = pad + (hi - p) * (height - 2 * pad) / span
        pts.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = pts[-1].split(",")
    title = f"{history[0][0]} to {history[-1][0]}: low {lo:,.0f}, high {hi:,.0f}"
    trend = "down" if prices[-1] < prices[0] else ("up" if prices[-1] > prices[0] else "flat")
    return Markup(
        f'<svg class="spark {trend}" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{title}">'
        f'<title>{title}</title><polyline fill="none" stroke-width="1.5" points="{" ".join(pts)}"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.2"/></svg>'
    )


templates.env.filters["money"] = money
templates.env.globals["sparkline"] = sparkline
templates.env.globals["mock_mode"] = config.MOCK_STORES
templates.env.globals["proxy_mode"] = bool(config.SCRAPER_API_KEY or config.SCRAPER_PROXY_URL)
templates.env.globals["hosted"] = config.HOSTED
templates.env.globals["store_labels"] = {cls.name: cls.label for cls in STORES}
STORE_NAMES = [cls.name for cls in STORES]


def _page_context(request: Request, q: str, **extra) -> dict:
    return {"request": request, "q": q, "stores": STORE_NAMES, "recent": cache.recent_queries(),
            "health": cache.store_health(), "history_stats": cache.history_stats(), **extra}


# -------------------------------------------------------------------- pages

@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = Query("", max_length=120), refresh: int = 0, sync: int = 0):
    """Home and search page.

    With a query, the page normally renders a shell immediately and lets the
    browser fetch each store (progressive loading). When every store is already
    cached, or with ?sync=1, the full page is rendered server-side in one go.
    """
    q = q.strip()
    result = None
    progressive = False
    if len(q) >= 2:
        if sync or (not refresh and fully_cached(q)):
            result = run_search(q, refresh=bool(refresh))
        else:
            progressive = True
    return templates.TemplateResponse(request, "index.html", _page_context(
        request, q, result=result, progressive=progressive, refresh=bool(refresh)))


@app.get("/fragment/store/{store}")
def fragment_store(request: Request, store: str, q: str = Query(..., min_length=2, max_length=120), refresh: int = 0):
    """One store's results: rendered column HTML plus the raw result for /fragment/compare."""
    r = search_store(q, store, refresh=bool(refresh))
    if r is None:
        raise HTTPException(404, "unknown store")
    html = templates.get_template("_column.html").render(s=r)
    return JSONResponse({"html": html, "result": store_result_dict(r, with_offers=True)})


@app.post("/fragment/compare", response_class=HTMLResponse)
async def fragment_compare(request: Request):
    """Group per-store results (as returned by /fragment/store) into the comparison HTML."""
    try:
        body = await request.json()
        query = str(body["query"]).strip()
        stores = body["stores"]
        assert isinstance(stores, dict) and 2 <= len(query) <= 120
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "expected {query, stores: {name: result}}")
    results = {name: store_result_from_dict(name, d) for name, d in stores.items() if name in STORE_NAMES}
    result = build_response(query, results)
    return templates.TemplateResponse(request, "_results.html", {"request": request, "q": query, "result": result,
                                                                 "stores": STORE_NAMES})


# -------------------------------------------------------------------- alerts

def _alerts_page(request: Request, email: str, **extra):
    return templates.TemplateResponse(request, "alerts.html", {
        "request": request, "email": email, "alerts": cache.list_alerts(email) if email else [],
        "email_enabled": email_enabled(), "can_run": _cron_allowed(request, None), **extra})


def _cron_allowed(request: Request, token: Optional[str]) -> bool:
    """Vercel Cron sends `Authorization: Bearer $CRON_SECRET`; a ?token= works for manual runs.
    Without a secret configured, runs are allowed only off the public host."""
    if config.CRON_SECRET:
        auth = request.headers.get("authorization", "")
        return auth == f"Bearer {config.CRON_SECRET}" or token == config.CRON_SECRET
    return not config.HOSTED


@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, email: str = "", created: int = 0):
    return _alerts_page(request, email.strip().lower(), created=bool(created))


@app.post("/alerts")
def create_alert(email: str = Form(...), query: str = Form(...), title: str = Form(...), key: str = Form(...),
                 store: str = Form(...), url: str = Form(...), target_price: float = Form(...),
                 current_price: float = Form(...)):
    email = email.strip().lower()
    if "@" not in email or target_price <= 0:
        raise HTTPException(422, "a valid email and a positive target price are required")
    cache.add_alert(email, query, title[:200], key, store, url, target_price, current_price)
    return RedirectResponse(f"/alerts?email={email}&created=1", status_code=303)


@app.post("/alerts/{alert_id}/delete")
def remove_alert(alert_id: int, email: str = Form(...)):
    cache.delete_alert(alert_id, email)
    return RedirectResponse(f"/alerts?email={email.strip().lower()}", status_code=303)


@app.post("/alerts/run", response_class=HTMLResponse)
def run_alerts_page(request: Request, email: str = Form("")):
    if not _cron_allowed(request, None):
        raise HTTPException(403, "alert checks run on a schedule on the hosted copy")
    summary = check_alerts()
    return _alerts_page(request, email, run_summary=json.dumps(summary, indent=2))


@app.api_route("/api/alerts/run", methods=["GET", "POST"])
def api_run_alerts(request: Request, token: Optional[str] = None):
    """Scheduled entry point (Vercel Cron, `make alerts` or any external scheduler)."""
    if not _cron_allowed(request, token):
        raise HTTPException(403, "missing or wrong CRON_SECRET")
    return check_alerts()


# ----------------------------------------------------------------------- api

@app.get("/api/search")
def api_search(q: str = Query(..., min_length=2, max_length=120), refresh: int = 0):
    return JSONResponse(run_search(q, refresh=bool(refresh)).to_dict())


@app.get("/api/history")
def api_history(q: str = Query(..., min_length=2, max_length=120)):
    """30-day price history per matched product for a query (uses cached results when fresh)."""
    result = run_search(q)
    return {"query": result.query, "days": 30, "products": [
        {"title": g.title, "stores": g.store_count, "current": g.cheapest.price, "low30": g.low30, "at_low": g.at_low,
         "history": [{"day": d, "price": p} for d, p in g.history]}
        for g in result.groups]}


@app.get("/api/health")
def api_health():
    return {"stores": cache.store_health(), "mock": config.MOCK_STORES,
            "proxy": bool(config.SCRAPER_API_KEY or config.SCRAPER_PROXY_URL),
            "history": cache.history_stats(), "email": email_enabled()}
