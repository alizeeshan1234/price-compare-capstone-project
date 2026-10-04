# PriceWatch

A self-hosted, multi-store price tracker with Telegram alerts. Paste a product URL and a
target price; PriceWatch checks the page on a schedule, keeps the full price history, charts
it, tells you whether now is a good time to buy, and messages you the moment the price drops
below your target.

Built as a college capstone project to show a small but complete production-style system:
pluggable scrapers, scheduled jobs, persistence, alerting, a dashboard, health monitoring,
tests, and containerised deployment.

## Features

- **Multi-store scraping** via a plugin architecture. Dedicated adapters for Amazon and
  Flipkart, plus a generic adapter that reads JSON-LD, Open Graph and microdata, so most
  other stores work with zero extra code. Adding a store is one small class.
- **Scheduled checks** with APScheduler, polite delays between requests, retries with
  exponential backoff, and CAPTCHA / rate-limit detection.
- **Price history and analytics**: current, lowest, highest, average, last change, and a
  Buy now / Good price / Fair / Wait recommendation based on the product's own history.
- **Telegram alerts** when the price reaches the target, with a cooldown so you are not
  spammed, and re-alerting if the price keeps falling.
- **Health monitoring**: per-product status, success rate, average fetch time, recent scrape
  log, and a scheduler view. Broken scrapers are visible instead of silently failing.
- **Dashboard** with Chart.js price charts, dark-mode support, and a JSON API for a future
  mobile or React frontend.
- **Mock mode** for demos and development that never touches real sites.
- **Tests** that run offline against saved HTML fixtures.
- **Docker** image and compose file for one-command deployment.

## Quick start

```bash
git clone <this repo> && cd price-tracker
make install                 # creates .venv and installs requirements
cp .env.example .env         # optional: add Telegram token + chat id
make dev                     # http://localhost:8000
```

Demo with 30 days of generated history and simulated prices:

```bash
make demo
```

Run the tests:

```bash
make test
```

## Telegram setup

1. Message `@BotFather` on Telegram, send `/newbot`, copy the token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
4. Put both values in `.env` as `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`.

Without these set, alerts are still recorded in the database and shown in the UI; they are
just not delivered.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pricewatch.db` | Any SQLAlchemy URL; use PostgreSQL in production |
| `CHECK_INTERVAL_MINUTES` | `360` | How often every product is re-checked |
| `SCRAPE_DELAY_SECONDS` | `3` | Pause between products in a scheduled run |
| `ALERT_COOLDOWN_HOURS` | `24` | Minimum gap between alerts for the same product |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Alert delivery |
| `MOCK_SCRAPER` | `0` | `1` returns simulated prices |

## Architecture

```
                 +-----------------+
   browser  <--> |  FastAPI (app)  | <--> SQLite / PostgreSQL
                 +--------+--------+        products, price_history,
                          |                 alerts, scrape_logs
            +-------------+--------------+
            |                            |
   +--------v--------+        +----------v---------+
   |  APScheduler    |        |   services.py      |
   |  every N mins   | -----> |  check_product()   |
   +-----------------+        |  maybe_alert()     |
                              +----------+---------+
                                         |
                      +------------------+------------------+
                      |                                     |
            +---------v----------+                +---------v---------+
            | scraper/registry   |                |  notifier.py      |
            | amazon | flipkart  |                |  Telegram Bot API |
            | generic | mock     |                +-------------------+
            +--------------------+
```

- `app/scraper/base.py` defines the adapter interface, HTTP fetching with retries, and
  price parsing helpers.
- `app/scraper/registry.py` picks an adapter from the URL. Adding a store means adding a
  class with a `domains` tuple and a `parse(html, url)` method, then listing it here.
- `app/services.py` is the only place business rules live: adding products, recording
  prices, logging attempts, and deciding when to alert.
- `app/scheduler.py` runs `check_all_products` on an interval.
- `app/main.py` holds the web routes and JSON API.

## Project layout

```
app/
  main.py          routes and JSON API
  config.py        settings from environment
  database.py      SQLAlchemy engine/session
  models.py        Product, PriceHistory, Alert, ScrapeLog
  services.py      business logic
  scheduler.py     background job
  notifier.py      Telegram
  analytics.py     recommendation / percentiles
  scraper/         adapters + registry
  templates/       Jinja2 pages
  static/          CSS
tests/             pytest suite + HTML fixtures
scripts/           seed_demo.py
```

## Adding a store

```python
# app/scraper/mystore.py
from bs4 import BeautifulSoup
from .base import BaseScraper, ScrapeResult, ScrapeError, parse_price

class MyStoreScraper(BaseScraper):
    name = "mystore"
    domains = ("mystore.com",)

    def parse(self, html, url):
        soup = BeautifulSoup(html, "lxml")
        price = soup.select_one(".price")
        if not price:
            raise ScrapeError("price not found")
        return ScrapeResult(title=soup.select_one("h1").get_text(strip=True),
                            price=parse_price(price.get_text()))
```

Then add `MyStoreScraper` to `SCRAPERS` in `registry.py` before `GenericScraper`, save a
sample page to `tests/fixtures/`, and write a test.

## Deployment

```bash
cp .env.example .env   # fill in values
docker compose up --build -d
```

The compose file persists the SQLite database in a named volume. For a public deployment,
point `DATABASE_URL` at PostgreSQL and put the app behind a reverse proxy with HTTPS.

## Ethics and limits

- Check each site's `robots.txt` and terms before tracking it. Keep the interval generous.
- The scraper identifies itself with a normal browser user agent and never bypasses
  CAPTCHAs; when one is detected the check is logged as a failure.
- Store selectors change over time. The status page makes this visible, and the fixture
  tests make the fix a five-minute job.

## Metrics to report

PriceWatch records everything needed for an evaluation section:

- Scraper success rate per store (`/status`, `/api/health`)
- Average fetch latency
- Number of alerts fired and delivered
- Savings found: first observed price minus lowest observed price, summed across products
