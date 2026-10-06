"""SQLite cache for search results plus a log used for store health stats."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

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
            CREATE TABLE IF NOT EXISTS price_history (
                key TEXT NOT NULL, store TEXT NOT NULL, title TEXT NOT NULL, price REAL NOT NULL,
                url TEXT NOT NULL, day TEXT NOT NULL, seen_at TEXT NOT NULL, PRIMARY KEY (key, day));
            CREATE INDEX IF NOT EXISTS price_history_day ON price_history (day);
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, query TEXT NOT NULL,
                title TEXT NOT NULL, key TEXT NOT NULL, store TEXT NOT NULL, url TEXT NOT NULL,
                target_price REAL NOT NULL, price_at_creation REAL NOT NULL, created_at TEXT NOT NULL,
                last_checked_at TEXT, last_price REAL, triggered_at TEXT, triggered_price REAL,
                notified_via TEXT);
            """
        )


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key(query: str) -> str:
    return " ".join(query.lower().split())


def get_cached(query: str) -> Dict[str, List[dict]]:
    """Return {store: [offer dicts]} for stores with a fresh cache entry."""
    cutoff = (_now() - timedelta(minutes=config.CACHE_TTL_MINUTES)).isoformat()
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
            (_key(query), store, json.dumps(offers), _now().isoformat()),
        )


def log_search(query: str, store: str, ok: bool, count: int, duration_ms: int, error: Optional[str]) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO search_log (query, store, ok, count, duration_ms, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_key(query), store, int(ok), count, duration_ms, error, _now().isoformat()),
        )


def recent_queries(limit: int = 8) -> List[str]:
    with connect() as c:
        rows = c.execute(
            "SELECT query, MAX(created_at) AS t FROM search_log GROUP BY query ORDER BY t DESC LIMIT ?", (limit,)
        ).fetchall()
    return [r["query"] for r in rows]


def store_health(days: int = 7) -> List[dict]:
    since = (_now() - timedelta(days=days)).isoformat()
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


# ---------------------------------------------------------------- price history

def record_prices(offers: Iterable) -> None:
    """Keep one price per listing per day (the lowest seen that day)."""
    now = _now()
    day = now.date().isoformat()
    with connect() as c:
        for o in offers:
            c.execute(
                """INSERT INTO price_history (key, store, title, price, url, day, seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key, day) DO UPDATE SET
                       price = MIN(price, excluded.price), title = excluded.title,
                       url = excluded.url, seen_at = excluded.seen_at""",
                (o.key, o.store, o.title, o.price, o.url, day, now.isoformat()),
            )


def price_history(keys: Iterable[str], days: int = 30) -> Dict[str, List[Tuple[str, float]]]:
    """{listing key: [(day, price), ...]} oldest first, for the last `days` days."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    since = (_now() - timedelta(days=days)).date().isoformat()
    out: Dict[str, List[Tuple[str, float]]] = {k: [] for k in keys}
    with connect() as c:
        for chunk in (keys[i:i + 500] for i in range(0, len(keys), 500)):
            marks = ",".join("?" * len(chunk))
            rows = c.execute(
                f"SELECT key, day, price FROM price_history WHERE key IN ({marks}) AND day >= ? ORDER BY day",
                (*chunk, since),
            ).fetchall()
            for r in rows:
                out[r["key"]].append((r["day"], r["price"]))
    return out


def history_stats(days: int = 30) -> dict:
    since = (_now() - timedelta(days=days)).date().isoformat()
    with connect() as c:
        r = c.execute(
            "SELECT COUNT(*) AS points, COUNT(DISTINCT key) AS listings, COUNT(DISTINCT day) AS days "
            "FROM price_history WHERE day >= ?", (since,)
        ).fetchone()
    return {"points": r["points"], "listings": r["listings"], "days": r["days"]}


# ---------------------------------------------------------------------- alerts

def add_alert(email: str, query: str, title: str, key: str, store: str, url: str,
              target_price: float, current_price: float) -> int:
    with connect() as c:
        cur = c.execute(
            """INSERT INTO alerts (email, query, title, key, store, url, target_price, price_at_creation, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (email.strip().lower(), _key(query), title, key, store, url, target_price, current_price,
             _now().isoformat()),
        )
        return int(cur.lastrowid)


def list_alerts(email: Optional[str] = None, limit: int = 100) -> List[dict]:
    with connect() as c:
        if email:
            rows = c.execute("SELECT * FROM alerts WHERE email = ? ORDER BY id DESC LIMIT ?",
                             (email.strip().lower(), limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def pending_alerts() -> List[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM alerts WHERE triggered_at IS NULL ORDER BY query, id").fetchall()
    return [dict(r) for r in rows]


def delete_alert(alert_id: int, email: Optional[str] = None) -> bool:
    with connect() as c:
        if email:
            cur = c.execute("DELETE FROM alerts WHERE id = ? AND email = ?", (alert_id, email.strip().lower()))
        else:
            cur = c.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        return cur.rowcount > 0


def alert_checked(alert_id: int, price: Optional[float]) -> None:
    with connect() as c:
        c.execute("UPDATE alerts SET last_checked_at = ?, last_price = ? WHERE id = ?",
                  (_now().isoformat(), price, alert_id))


def alert_triggered(alert_id: int, price: float, via: str) -> None:
    with connect() as c:
        c.execute(
            "UPDATE alerts SET triggered_at = ?, triggered_price = ?, notified_via = ?, "
            "last_checked_at = ?, last_price = ? WHERE id = ?",
            (_now().isoformat(), price, via, _now().isoformat(), price, alert_id),
        )
