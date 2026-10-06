"""PriceCompare: search once, compare prices across stores side by side."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import cache, config
from .search import run_search
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


app = FastAPI(title="PriceCompare", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def money(value: Optional[float], code: str = "INR") -> str:
    if value is None:
        return "—"
    return f"{SYMBOLS.get(code, code + ' ')}{value:,.0f}"


templates.env.filters["money"] = money
templates.env.globals["mock_mode"] = config.MOCK_STORES
templates.env.globals["proxy_mode"] = bool(config.SCRAPER_API_KEY or config.SCRAPER_PROXY_URL)
templates.env.globals["hosted"] = bool(os.getenv("VERCEL"))
templates.env.globals["store_labels"] = {cls.name: cls.label for cls in STORES}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = Query("", max_length=120), refresh: int = 0):
    q = q.strip()
    result = run_search(q, refresh=bool(refresh)) if len(q) >= 2 else None
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "q": q,
            "result": result,
            "stores": [cls.name for cls in STORES],
            "recent": cache.recent_queries(),
            "health": cache.store_health(),
        },
    )


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=2, max_length=120), refresh: int = 0):
    return JSONResponse(run_search(q, refresh=bool(refresh)).to_dict())


@app.get("/api/health")
def api_health():
    return {"stores": cache.store_health(), "mock": config.MOCK_STORES,
            "proxy": bool(config.SCRAPER_API_KEY or config.SCRAPER_PROXY_URL)}
