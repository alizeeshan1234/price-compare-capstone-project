"""Simple price analytics used on the product page."""
from typing import List, Optional, Dict, Any


def percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def recommendation(prices: List[float]) -> Dict[str, Any]:
    """Classify the current price relative to its own history."""
    if len(prices) < 3:
        return {"verdict": "Not enough data", "detail": "Need at least 3 price points.", "level": "neutral"}
    current = prices[-1]
    lowest = min(prices)
    avg = sum(prices) / len(prices)
    p25 = percentile(prices, 0.25)

    if current <= lowest * 1.02:
        return {"verdict": "Buy now", "detail": "At or within 2% of the lowest price recorded.", "level": "good"}
    if p25 is not None and current <= p25:
        return {"verdict": "Good price", "detail": "In the cheapest quarter of its history.", "level": "good"}
    if current <= avg:
        return {"verdict": "Fair", "detail": "Below the average price.", "level": "neutral"}
    return {"verdict": "Wait", "detail": f"{(current / avg - 1) * 100:.0f}% above average.", "level": "bad"}


def change_pct(prices: List[float]) -> Optional[float]:
    """Percent change between the last two observations."""
    if len(prices) < 2 or prices[-2] == 0:
        return None
    return (prices[-1] - prices[-2]) / prices[-2] * 100
