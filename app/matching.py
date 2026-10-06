"""Group the same product across stores even though every store titles it differently.

Approach (deliberately simple and explainable):
  1. normalise titles -> set of tokens, with "128 GB" style specs fused into "128gb"
  2. drop marketing / filler words
  3. two offers match when their token sets are similar enough (Jaccard) AND
     their spec tokens (storage, RAM, size...) do not contradict each other
  4. greedy clustering, cheapest offers first
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .stores.base import Offer

try:  # character-level similarity, used only as a tiebreaker (see fuzzy())
    from rapidfuzz import fuzz as _fuzz

    def _ratio(a: str, b: str) -> float:
        return _fuzz.ratio(a, b) / 100.0
except ImportError:  # pragma: no cover - rapidfuzz is in requirements.txt
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

STOPWORDS = {
    "with", "and", "for", "the", "new", "latest", "best", "original", "genuine", "pack", "of",
    "free", "delivery", "offer", "sale", "online", "buy", "price", "india", "smartphone", "mobile",
    "phone", "storage", "ram", "colour", "color", "edition", "model", "inch", "inches", "cm",
}
# Fused into one token so "15.40 cm" cannot leak a stray "15" into matching. The decimal
# point becomes "d" ("15d40cm") so the size can still be read back for comparison.
BARE_DECIMAL = re.compile(r"\b\d+\.\d+\b")  # "15.6 FHD", "Bluetooth 5.3": not a model number
SPEC = re.compile(r"\b(\d+(?:\.\d+)?)\s*(gb|tb|mah|mm|cm|hz|w|mp|kg|g|ml|l|inches|inch|in)\b", re.I)
# Only these units must agree between two listings. Screen sizes (cm/inch) are
# compared separately with a tolerance because stores round them differently.
SPEC_UNITS = {"gb", "tb", "mah", "hz", "w", "mp", "kg", "g", "ml", "l", "mm"}
SCREEN_UNITS = {"cm", "inch", "in"}
SCREEN_TOLERANCE_INCH = 1.5
TOKEN = re.compile(r"[a-z0-9]+")
# "wh-1000xm5" / "mx-master" style codes stay one token so WH-1000XM5 != WF-1000XM5.
HYPHEN_CODE = re.compile(r"\b([a-z0-9]+)-([a-z0-9]+)\b")
# Model variants: two listings are the same product only if they agree on these.
VARIANT = {"pro", "max", "plus", "mini", "ultra", "lite", "air", "fe", "neo", "prime", "edge", "fold", "flip"}
# Short model numbers such as "6", "15", "17e", "s24", "a16", "2331": listings must share at least one.
MODEL_TOKEN = re.compile(r"^(?:[a-z]?\d{1,4}[a-z]?)$")
YEAR = re.compile(r"^(?:19|20)\d{2}$")  # "2024 model" is not a model number
NOT_MODEL = {"4k", "8k", "2k", "5g", "4g", "3d", "1x", "2x", "3x"}  # resolutions / network, not models
# Phrases where a variant word means something else ("Ultra HD" is a resolution, not a model).
# "Pro+" / "Note 13 Pro+" is spelled out so the plus sign survives tokenising.
PHRASES = [(re.compile(r"\bultra\s*hd\b"), "ultrahd"), (re.compile(r"\bfull\s*hd\b"), "fullhd"),
           (re.compile(r"\bmini\s*led\b"), "miniled"), (re.compile(r"\bpro\s*max\b"), "pro max"),
           (re.compile(r"(?<=[a-z0-9])\+(?=\s|$|[,)])"), " plus")]
# Fuzzy tiebreaker: a pair whose word overlap falls just short of the threshold is
# still merged when the normalised titles are nearly the same string. Catches
# "Air dopes" / "Airdopes", "Smart Watch" / "Smartwatch", hyphenated brand names.
FUZZY_RESCUE = True
FUZZY_BAND = 0.15      # how far below the Jaccard threshold the rescue reaches
FUZZY_ACCEPT = 0.80    # minimum character similarity of the sorted-token strings
# Unit families that must agree with each other (1 TB vs 256 GB is a different product).
UNIT_FAMILIES = [("gb", "tb"), ("mah",), ("hz",), ("w",), ("mp",), ("kg", "g"), ("ml", "l"), ("mm",)]
# Words that signal an add-on rather than the product itself.
ACCESSORY = {
    "case", "cases", "cover", "covers", "protector", "protectors", "tempered", "charger",
    "cable", "adapter", "skin", "pouch", "strap", "holder", "stand", "mount", "guard",
    "sticker", "bag", "sleeve",
}
# Words that only mean "accessory" in a phrase ("track on glass" is a mouse feature).
ACCESSORY_WORDS = re.compile(r"\b(?:tempered\s+glass|screen\s+(?:guard|protector)|glass\s+(?:guard|protector)|lens\s+protector|camera\s+protector)\b")
# "with MagSafe Case" (earbuds), "Aluminium Case" (watch) describe the product, not an add-on.
INCLUDED_CASE = re.compile(r"\b(?:with|charging|magsafe|aluminium|aluminum|titanium|steel)\s+(?:magsafe\s+|charging\s+|smart\s+)?case\b")
# "Compatible for iPhone 15" is an accessory; "compatible with Mac" on a mouse is not.
ACCESSORY_PHRASE = re.compile(r"\bcompatible\s+(?:for|with)\s+(?:apple|samsung|iphone|galaxy|oneplus|pixel|redmi|realme|vivo|oppo|motorola|nothing)\b")


def normalize(title: str) -> Set[str]:
    text = title.lower().replace("'", "")
    for pattern, repl in PHRASES:
        text = pattern.sub(repl, text)
    while HYPHEN_CODE.search(text):
        text = HYPHEN_CODE.sub(lambda m: m.group(1) + m.group(2), text, count=1)
    # "15.40 cm" -> "15d40cm": one token, and the decimal survives for size comparison.
    text = SPEC.sub(lambda m: f" {m.group(1).replace('.', 'd')}{_unit(m.group(2))} ", text)
    text = BARE_DECIMAL.sub(" ", text)
    tokens = set(TOKEN.findall(text))
    # Single digits are kept only when numeric ("Flip 6", "Series 9" are model numbers).
    return {t for t in tokens if t not in STOPWORDS and (len(t) > 1 or t.isdigit())}


def _unit(u: str) -> str:
    u = u.lower()
    return "inch" if u in ("inches", "in") else u


def spec_tokens(tokens: Set[str]) -> Set[str]:
    return {t for t in tokens if re.fullmatch(r"\d+(?:d\d+)?(%s)" % "|".join(SPEC_UNITS | SCREEN_UNITS), t)}


def coverage(title_tokens: Set[str], query_tokens: Set[str]) -> float:
    """Share of the query's words that appear in the title (0..1). Used to filter.

    A bare number such as "15" is too weak to count on its own: if the query has any
    alphabetic words, at least one of them must appear or the score is 0.
    """
    if not query_tokens:
        return 1.0
    words = {t for t in query_tokens if not t.isdigit()}
    if words and not (title_tokens & words):
        return 0.0
    return len(title_tokens & query_tokens) / len(query_tokens)


def relevance(title_tokens: Set[str], query_tokens: Set[str]) -> float:
    """Coverage with a small penalty per variant word the user did not ask for, so
    "iphone 18" lists the plain model above "iphone 18 pro". Used to rank."""
    score = coverage(title_tokens, query_tokens)
    extra_variants = variants_of(title_tokens) - query_tokens
    return score * (0.9 ** len(extra_variants))


def min_relevance_for(query_tokens: Set[str]) -> float:
    """Short queries must match completely; longer ones at least half."""
    return 1.0 if len(query_tokens) <= 2 else 0.5


def is_accessory(title_tokens: Set[str], query_tokens: Set[str], title: str = "") -> bool:
    """Accessory words in the title that the user did not ask for."""
    if query_tokens & (ACCESSORY | {"glass", "screen", "protector"}):
        return False  # the user is shopping for accessories; nothing gets demoted
    hits = (title_tokens & ACCESSORY) - query_tokens
    low = title.lower()
    if hits == {"case"} and INCLUDED_CASE.search(low):
        hits = set()
    if hits:
        return True
    if not title:
        return False
    if ACCESSORY_WORDS.search(low) and not ({"glass", "protector", "guard"} & query_tokens):
        return True
    return bool(ACCESSORY_PHRASE.search(low)) and not ({"case", "cover"} & query_tokens)


def similarity(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def fuzzy(a: Set[str], b: Set[str]) -> float:
    """Character-level similarity (0..1) of the two token sets written out in sorted order.

    Unlike Jaccard, this gives partial credit when a word is split or spelled
    slightly differently ("airdopes" vs "air dopes", "fireboltt" vs "fire boltt").
    """
    a, b = a - spec_tokens(a), b - spec_tokens(b)  # specs are checked exactly, elsewhere
    if not a or not b:
        return 0.0
    return _ratio(" ".join(sorted(a)), " ".join(sorted(b)))


def _with_units(tokens: Set[str], units) -> Set[str]:
    return {t for t in tokens if any(t.endswith(u) and t[: -len(u)].replace("d", "").isdigit() for u in units)}


def _inches(tokens: Set[str]) -> Set[float]:
    """Screen sizes in inches from "15d40cm" / "6d1inch" / "43inch" tokens."""
    out = set()
    for t in tokens:
        for u, factor in (("inch", 1.0), ("cm", 1 / 2.54)):
            n = t[: -len(u)] if t.endswith(u) else ""
            if n and n.replace("d", "").isdigit():
                out.add(round(float(n.replace("d", ".")) * factor, 1))
    return out


def specs_compatible(a: Set[str], b: Set[str]) -> bool:
    """If both mention the same kind of spec (e.g. storage), they must agree on it.

    Within a family the listing with fewer values must be a subset of the other:
    "8GB RAM, 256GB" matches "256GB" (RAM omitted) but not "16GB RAM, 256GB".
    Screen sizes must be within 1.5 inches of each other (stores round cm/inch).
    """
    for family in UNIT_FAMILIES:
        sa, sb = _with_units(a, family), _with_units(b, family)
        if sa and sb and not (sa <= sb or sb <= sa):
            return False
    ia, ib = _inches(a), _inches(b)
    if ia and ib and not any(abs(x - y) <= SCREEN_TOLERANCE_INCH for x in ia for y in ib):
        return False
    return True


def variants_of(tokens: Set[str]) -> Set[str]:
    return tokens & VARIANT


def model_tokens(tokens: Set[str]) -> Set[str]:
    return {t for t in tokens if MODEL_TOKEN.match(t) and any(c.isdigit() for c in t)
            and t not in NOT_MODEL and not YEAR.match(t)}


def model_codes(tokens: Set[str]) -> Set[str]:
    """Distinctive alphanumeric codes such as "1000xm5", "wf1000xm5", "mx3s", "g502".

    Two listings sharing one are the same product line even when the rest of the
    title differs completely, so they bypass the word-overlap threshold.
    """
    return {
        t for t in tokens
        if len(t) >= 4 and any(c.isdigit() for c in t) and any(c.isalpha() for c in t)
        and not any(t.endswith(u) and t[: -len(u)].replace("d", "").isdigit() for u in SPEC_UNITS | SCREEN_UNITS)
        and t not in NOT_MODEL
    }


def same_product_family(a: Set[str], b: Set[str]) -> bool:
    """Pro vs Pro Max vs base, and 17 vs 17e, are different products."""
    if variants_of(a) != variants_of(b):
        return False
    ma, mb = model_tokens(a), model_tokens(b)
    if ma and mb and not (ma & mb):
        return False
    ca, cb = model_codes(a), model_codes(b)
    if ca and cb and not (ca & cb):
        return False
    return True


@dataclass
class Group:
    title: str
    offers: List[Offer] = field(default_factory=list)
    tokens: Set[str] = field(default_factory=set)
    relevance: float = 1.0
    accessory: bool = False
    members: List[Set[str]] = field(default_factory=list)  # token set of every offer
    # Filled in by the search service from the price-history table.
    history: List[Tuple[str, float]] = field(default_factory=list)  # (day, lowest price that day)
    low30: Optional[float] = None  # lowest price seen in the last 30 days

    @property
    def by_store(self) -> Dict[str, Offer]:
        """Cheapest offer per store."""
        best: Dict[str, Offer] = {}
        for o in self.offers:
            if o.store not in best or o.price < best[o.store].price:
                best[o.store] = o
        return best

    @property
    def cheapest(self) -> Offer:
        return min(self.offers, key=lambda o: o.price)

    @property
    def priciest(self) -> Offer:
        """Most expensive store's best offer (so savings compare stores, not listings)."""
        return max(self.by_store.values(), key=lambda o: o.price)

    @property
    def savings(self) -> float:
        return self.priciest.price - self.cheapest.price if self.store_count > 1 else 0.0

    @property
    def savings_pct(self) -> float:
        hi = self.priciest.price
        return (self.savings / hi * 100) if hi else 0.0

    @property
    def store_count(self) -> int:
        return len({o.store for o in self.offers})

    @property
    def at_low(self) -> bool:
        """Today's cheapest price is the lowest in the tracked window."""
        return self.low30 is not None and self.cheapest.price <= self.low30 + 1e-9

    @property
    def history_days(self) -> int:
        return len(self.history)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "stores": self.store_count,
            "relevance": round(self.relevance, 2),
            "accessory": self.accessory,
            "cheapest": self.cheapest.to_dict(),
            "savings": round(self.savings, 2),
            "savings_pct": round(self.savings_pct, 1),
            "by_store": {s: o.to_dict() for s, o in self.by_store.items()},
            "offers": [o.to_dict() for o in self.offers],
            "history": [{"day": d, "price": p} for d, p in self.history],
            "low30": self.low30,
            "at_low": self.at_low,
        }


def group_offers(offers: List[Offer], query: str = "", threshold: float = 0.45, min_relevance: float = 0.5) -> List[Group]:
    """Cluster offers into products. With a query, drop clearly unrelated listings and
    rank the most relevant, most widely available products first."""
    qtokens = normalize(query) if query else set()
    groups: List[Group] = []
    for offer in sorted(offers, key=lambda o: o.price):
        tokens = normalize(offer.title)
        if qtokens and coverage(tokens, qtokens) < max(min_relevance, min_relevance_for(qtokens)):
            continue
        rel = relevance(tokens, qtokens)
        specs = spec_tokens(tokens)
        acc = is_accessory(tokens, qtokens, offer.title)
        best: Optional[Group] = None
        best_score = 0.0
        best_fuzzy = 0.0
        for g in groups:
            if g.accessory != acc:
                continue  # a case never shares a row with the phone
            # Must be compatible with every member, and similar enough to at least one.
            if not all(specs_compatible(specs, spec_tokens(m)) and same_product_family(tokens, m) for m in g.members):
                continue
            score = max(similarity(tokens, m) for m in g.members)
            fz = max(fuzzy(tokens, m) for m in g.members)
            if model_codes(tokens) & set().union(*(model_codes(m) for m in g.members)):
                score = max(score, threshold)  # shared model code: strong enough on its own
            elif model_tokens(tokens) & set().union(*(model_tokens(m) for m in g.members)) and score >= threshold * 0.5:
                score = threshold  # same short model number ("3s", "15", "141") plus fair overlap
            elif FUZZY_RESCUE and threshold - FUZZY_BAND <= score < threshold and fz >= FUZZY_ACCEPT:
                score = threshold  # nearly the same string once sorted: spelling / spacing differences
            # Fuzzy similarity breaks ties between equally good groups.
            if score >= threshold and (score > best_score or (score == best_score and fz > best_fuzzy)):
                best, best_score, best_fuzzy = g, score, fz
        if best is None:
            groups.append(Group(title=offer.title, offers=[offer], tokens=set(tokens), members=[set(tokens)],
                                relevance=rel, accessory=acc))
        else:
            best.offers.append(offer)
            best.members.append(set(tokens))
            best.relevance = max(best.relevance, rel)
            if len(offer.title) < len(best.title):
                best.title = offer.title
    # Real products before accessories; closest match to the query first, then the
    # products more stores carry, then cheaper.
    groups.sort(key=lambda g: (g.accessory, -round(g.relevance, 1), -g.store_count, g.cheapest.price))
    return groups
