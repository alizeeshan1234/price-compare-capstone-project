"""SQLite cache for search results plus a log used for store health stats."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from . import config


@contextmanager
def connect():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS results_cache (
                query TEXT NOT NULL, store TEXT NOT NULL, payload TEXT NOT NULL,
                fetched_at TEXT NOT NULL, PRIMARY KEY (query, store));
            CREATE TABLE IF NOT EXISTS search_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, store TEXT NOT NULL,
                ok INTEGER NOT NULL, count INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
                error TEXT, created_at TEXT NOT NULL);
            """
        )


def _key(query: str) -> str:
    return " ".join(query.lower().split())


def get_cached(query: str) -> Dict[str, List[dict]]:
    """Return {store: [offer dicts]} for stores with a fresh cache entry."""
    cutoff = (datetime.utcnow() - timedelta(minutes=config.CACHE_TTL_MINUTES)).isoformat()
    with connect() as c:
        rows = c.execute(
            "SELECT store, payload FROM results_cache WHERE query = ? AND fetched_at >= ?",
            (_key(query), cutoff),
        ).fetchall()
    return {r["store"]: json.loads(r["payload"]) for r in rows}


def set_cached(query: str, store: str, offers: List[dict]) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR REPLACE INTO results_cache (query, store, payload, fetched_at) VALUES (?, ?, ?, ?)",
            (_key(query), store, json.dumps(offers), datetime.utcnow().isoformat()),
        )


def log_search(query: str, store: str, ok: bool, count: int, duration_ms: int, error: Optional[str]) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO search_log (query, store, ok, count, duration_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_key(query), store, int(ok), count, duration_ms, error, datetime.utcnow().isoformat()),
        )


def recent_queries(limit: int = 8) -> List[str]:
    with connect() as c:
        rows = c.execute(
            "SELECT query, MAX(created_at) AS t FROM search_log GROUP BY query ORDER BY t DESC LIMIT ?", (limit,)
        ).fetchall()
    return [r["query"] for r in rows]


def store_health(days: int = 7) -> List[dict]:
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with connect() as c:
        rows = c.execute(
            """SELECT store, COUNT(*) AS attempts, SUM(ok) AS successes,
                      AVG(CASE WHEN ok THEN duration_ms END) AS avg_ms, AVG(CASE WHEN ok THEN count END) AS avg_count
               FROM search_log WHERE created_at >= ? GROUP BY store ORDER BY store""",
            (since,),
        ).fetchall()
    return [
        {
            "store": r["store"],
            "attempts": r["attempts"],
            "success_rate": (r["successes"] or 0) / r["attempts"] * 100 if r["attempts"] else None,
            "avg_ms": int(r["avg_ms"]) if r["avg_ms"] else None,
            "avg_count": round(r["avg_count"], 1) if r["avg_count"] else None,
        }
        for r in rows
    ]
