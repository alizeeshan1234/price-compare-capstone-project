"""Settings from environment / .env."""
import os
from dotenv import load_dotenv

load_dotenv()

MOCK_STORES: bool = os.getenv("MOCK_STORES", "0") == "1"
CACHE_TTL_MINUTES: int = int(os.getenv("CACHE_TTL_MINUTES", "180"))
RESULTS_PER_STORE: int = int(os.getenv("RESULTS_PER_STORE", "12"))
# On Vercel (and most serverless hosts) only /tmp is writable, so the cache lives there.
_default_db = "/tmp/pricecompare.db" if os.getenv("VERCEL") else "./pricecompare.db"
DATABASE_PATH: str = os.getenv("DATABASE_PATH", _default_db)
REQUEST_TIMEOUT: int = 15
MAX_RETRIES: int = 2

# Stores block datacenter IPs (Vercel, AWS...). A scraping proxy with residential IPs fixes
# that. Set one of these and HTML fetches for the store pages go through it:
#   SCRAPER_API_KEY   - key from scraperapi.com (free tier available); API mode
#   SCRAPER_PROXY_URL - any HTTP(S) proxy URL, e.g. http://user:pass@host:port
SCRAPER_API_KEY: str = os.getenv("SCRAPER_API_KEY", "").strip()
SCRAPER_PROXY_URL: str = os.getenv("SCRAPER_PROXY_URL", "").strip()
PROXY_TIMEOUT: int = int(os.getenv("PROXY_TIMEOUT", "60"))
PROXY_COUNTRY: str = os.getenv("PROXY_COUNTRY", "in")

HOSTED: bool = bool(os.getenv("VERCEL"))
APP_URL: str = os.getenv("APP_URL", "").rstrip("/") or (f"https://{os.getenv('VERCEL_PROJECT_PRODUCTION_URL')}" if os.getenv("VERCEL_PROJECT_PRODUCTION_URL") else "http://localhost:8000")

# Price-drop alerts. The checker runs via Vercel Cron (sends `Authorization: Bearer CRON_SECRET`),
# `make alerts`, or POST /api/alerts/run?token=CRON_SECRET from any scheduler.
CRON_SECRET: str = os.getenv("CRON_SECRET", "").strip()
# Email delivery for alerts. Leave SMTP_HOST empty to log instead of sending (demo mode).
SMTP_HOST: str = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_STARTTLS: bool = os.getenv("SMTP_STARTTLS", "1") == "1"
ALERT_FROM: str = os.getenv("ALERT_FROM", SMTP_USER or "pricecompare@example.com")
