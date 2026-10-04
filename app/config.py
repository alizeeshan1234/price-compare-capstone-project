"""Application settings loaded from environment variables / .env file."""
import os
from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./pricewatch.db")
CHECK_INTERVAL_MINUTES: int = _int("CHECK_INTERVAL_MINUTES", 360)
SCRAPE_DELAY_SECONDS: int = _int("SCRAPE_DELAY_SECONDS", 3)
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
MOCK_SCRAPER: bool = os.getenv("MOCK_SCRAPER", "0") == "1"

# Do not re-send an alert for the same product within this window.
ALERT_COOLDOWN_HOURS: int = _int("ALERT_COOLDOWN_HOURS", 24)

REQUEST_TIMEOUT_SECONDS: int = 15
MAX_RETRIES: int = 3
