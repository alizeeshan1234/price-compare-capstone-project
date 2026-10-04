"""PriceWatch web application."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends, Request, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from . import config, scheduler, analytics
from .database import init_db, get_db
from .models import Product, ScrapeLog
from .notifier import telegram_configured
from .scraper import SCRAPERS
from . import services

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="PriceWatch", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def currency_symbol(code: str) -> str:
    return {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(code or "", (code or "") + " ")


def money(value: Optional[float], code: str = "INR") -> str:
    if value is None:
        return "—"
    return f"{currency_symbol(code)}{value:,.2f}"


templates.env.filters["money"] = money
templates.env.globals["mock_mode"] = config.MOCK_SCRAPER
templates.env.globals["telegram_on"] = telegram_configured()


# --- pages -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db), error: Optional[str] = None):
    products = db.query(Product).order_by(Product.created_at.desc()).all()
    health = services.health_summary(db)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "products": products,
            "health": health,
            "savings": services.total_savings(db),
            "error": error,
            "next_run": scheduler.next_run_time(),
            "interval": config.CHECK_INTERVAL_MINUTES,
        },
    )


@app.post("/products")
def create_product(url: str = Form(...), target_price: float = Form(...), db: Session = Depends(get_db)):
    if not url.startswith(("http://", "https://")):
        return RedirectResponse("/?error=URL+must+start+with+http", status_code=303)
    if target_price <= 0:
        return RedirectResponse("/?error=Target+price+must+be+positive", status_code=303)
    try:
        product = services.add_product(db, url, target_price)
        db.commit()
    except services.ProductExists:
        return RedirectResponse("/?error=That+URL+is+already+being+tracked", status_code=303)
    return RedirectResponse(f"/products/{product.id}", status_code=303)


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_detail(product_id: int, request: Request, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    prices = [p.price for p in product.prices]
    logs = (
        db.query(ScrapeLog)
        .filter(ScrapeLog.product_id == product.id)
        .order_by(ScrapeLog.created_at.desc())
        .limit(10)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "labels": [p.checked_at.strftime("%d %b %H:%M") for p in product.prices],
            "series": prices,
            "recommendation": analytics.recommendation(prices),
            "change": analytics.change_pct(prices),
            "logs": logs,
        },
    )


@app.post("/products/{product_id}/check")
def check_now(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    services.check_product(db, product)
    db.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/target")
def update_target(product_id: int, target_price: float = Form(...), db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    if target_price > 0:
        product.target_price = target_price
        db.commit()
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.post("/products/{product_id}/delete")
def remove_product(product_id: int, db: Session = Depends(get_db)):
    services.delete_product(db, product_id)
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/check-all")
def check_all(background: BackgroundTasks):
    background.add_task(scheduler.run_now)
    return RedirectResponse("/status", status_code=303)


@app.get("/status", response_class=HTMLResponse)
def status_page(request: Request, db: Session = Depends(get_db)):
    products = db.query(Product).order_by(Product.last_error.desc().nullslast(), Product.title).all()
    recent_logs = db.query(ScrapeLog).order_by(ScrapeLog.created_at.desc()).limit(25).all()
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "products": products,
            "health": services.health_summary(db),
            "logs": recent_logs,
            "adapters": [cls.name for cls in SCRAPERS],
            "next_run": scheduler.next_run_time(),
            "interval": config.CHECK_INTERVAL_MINUTES,
        },
    )


# --- JSON API (for a future React / mobile frontend) ---------------------------

@app.get("/api/products")
def api_products(db: Session = Depends(get_db)):
    return [
        {
            "id": p.id,
            "title": p.title,
            "store": p.store,
            "url": p.url,
            "currency": p.currency,
            "target_price": p.target_price,
            "current_price": p.current_price,
            "lowest_price": p.lowest_price,
            "in_stock": p.in_stock,
            "last_checked_at": p.last_checked_at,
            "last_error": p.last_error,
        }
        for p in db.query(Product).all()
    ]


@app.get("/api/products/{product_id}/history")
def api_history(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return [{"price": p.price, "in_stock": p.in_stock, "checked_at": p.checked_at} for p in product.prices]


@app.get("/api/health")
def api_health(db: Session = Depends(get_db)):
    return JSONResponse(services.health_summary(db))
