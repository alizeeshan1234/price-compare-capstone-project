# PriceCompare

Type a product name once. PriceCompare searches Amazon, Flipkart, Snapdeal and Vijay Sales at
the same time, works out which listings are the same product, and shows the prices side by
side with the cheapest highlighted and the amount you save.

```
iphone 15  ──►  Amazon   Flipkart   Snapdeal   Vijay Sales  You save
iPhone 15 128GB Black   ₹69,900   ₹66,999 ★   ₹68,490    ₹70,499     ₹3,500 (5%)
iPhone 15 256GB Blue    ₹79,900   ₹76,999 ★      —          —        ₹2,901 (4%)
```

## Run it

```bash
make install            # virtualenv + dependencies
make dev                # http://localhost:8000  (real scraping)
make demo               # simulated stores: works offline, good for presentations
make test               # offline tests against saved HTML pages
```

Optional: copy `.env.example` to `.env` to change the cache lifetime, results per store, or
switch demo mode on.

## How it works

1. **Parallel search.** Every store adapter fetches results (HTML for Amazon, Flipkart and
   Snapdeal; Vijay Sales exposes the JSON search API its own site uses), retries on transient
   errors, and parses listings into a common `Offer`
   (store, title, price, url, image, rating). A thread pool runs all stores at once, so a
   search takes as long as the slowest store, not the sum.
2. **Resilience.** A store that blocks, times out or changes its HTML fails on its own. Its
   column shows "failed" with the reason and the other stores still render.
3. **Matching and ranking.** Titles are normalised ("128 GB" becomes `128gb`, filler words removed) and
   compared with Jaccard similarity. Listings whose specs contradict each other (128GB vs
   256GB) are never merged. Greedy clustering, cheapest first, produces one row per product.
   Listings sharing fewer than half the query's words are dropped, accessories (cases,
   chargers) sink to the bottom, and rows are ranked by match quality, then by how many
   stores carry the product.
4. **Side-by-side table.** One column per store, the lowest price per row highlighted, plus
   the saving between the most and least expensive store.
5. **Cache and health.** Results are cached in SQLite for three hours so repeat searches are
   instant and the stores are not hammered. Every live search is logged, which powers the
   store-health table (success rate, average time, average results).

## Project layout

```
app/
  main.py          routes: /  /api/search  /api/health
  search.py        cache -> stores -> grouping
  matching.py      title normalisation + cross-store grouping
  cache.py         SQLite cache and search log
  config.py        environment settings
  stores/
    base.py        Offer, fetch_html, parse helpers, BaseStore
    amazon.py  flipkart.py  snapdeal.py  vijaysales.py
    mock.py        simulated stores for demos
    registry.py    STORES list + concurrent search
  templates/       Jinja2 pages        static/  CSS
tests/             pytest + fixtures/ (saved search pages)
```

## Adding a store

```python
# app/stores/croma.py
from bs4 import BeautifulSoup
from .base import BaseStore, Offer, parse_price

class CromaStore(BaseStore):
    name, label, base_url = "croma", "Croma", "https://www.croma.com"

    def search_url(self, query):
        return f"{self.base_url}/searchB?q={self.q(query)}"

    def parse(self, html):
        soup = BeautifulSoup(html, "lxml")
        out = []
        for item in soup.select(".product-item"):
            title, price, link = item.select_one(".product-title"), item.select_one(".amount"), item.select_one("a[href]")
            if title and price and link and parse_price(price.get_text()):
                out.append(Offer(self.name, title.get_text(strip=True), parse_price(price.get_text()), self.absolute(link["href"])))
        return out
```

Add the class to `STORES` in `registry.py`, save a search page to `tests/fixtures/`, write a
test. Nothing else changes.

## Known limits

- Amazon and Flipkart actively block scrapers. Expect occasional failures, which the UI
  shows honestly. Caching reduces how often they are hit. Swapping `fetch_html` for a
  Playwright-driven browser would raise the success rate at the cost of speed.
- Store HTML changes over time. The fixture tests make a selector fix a five-minute job.
- Prices exclude delivery charges and bank offers.
- Matching is heuristic. It is tuned for electronics with clear specs; vague titles
  (fashion, groceries) group less reliably.

## Ethics

Only public search pages are read, at a low rate, with a cache, and never past a CAPTCHA.
Check each store's terms before deploying publicly.

## Deploy

### Vercel (zero config)

The repo includes `main.py` and `vercel.json` so Vercel's FastAPI preset picks the app up
automatically. The SQLite cache lives in `/tmp` on Vercel, so it resets when the function is
recycled, which is fine for a demo.

```bash
vercel          # preview (requires Vercel login to view)
vercel --prod   # public URL
```

**Datacenter IPs get blocked.** Amazon, Flipkart and Snapdeal refuse requests from Vercel's
servers (HTTP 503 / 529 / 403). Vijay Sales' search API is not affected. The fix is a scraping
proxy with residential IPs:

```bash
# free key from https://www.scraperapi.com (about 1,000 credits/month on the free tier)
vercel env add SCRAPER_API_KEY production
vercel deploy --prod
```

With the key set, the three HTML stores are fetched through ScraperAPI and all four columns
fill in. Any other HTTP proxy works through `SCRAPER_PROXY_URL` instead. Without either, the
UI explains which stores failed and still shows the rest. `MOCK_STORES=1` gives a guaranteed
simulated demo.

### Docker

```bash
cp .env.example .env
docker compose up --build -d
```
