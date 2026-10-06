"""Measure the cross-store matcher against a hand-labelled set of title pairs.

    python -m evaluation.evaluate            # table + mistakes
    python -m evaluation.evaluate --json     # machine-readable

Each row of pairs.csv is two listing titles from different stores and whether
they are the same product (same spec tier; colour is ignored). A pair is
predicted "same" when group_offers() puts the two listings in one row.
"""
import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

from app import matching
from app.matching import group_offers
from app.stores.base import Offer

PAIRS = Path(__file__).with_name("pairs.csv")


@dataclass
class Pair:
    a: str
    b: str
    same: bool
    note: str = ""


def load_pairs(path: Path = PAIRS) -> List[Pair]:
    with path.open(encoding="utf-8") as f:
        return [Pair(r["title_a"], r["title_b"], r["same"].strip() == "1", r.get("note") or "") for r in csv.DictReader(f)]


def predict(a: str, b: str) -> bool:
    offers = [Offer("storea", a, 1000.0, "https://a.example/x"), Offer("storeb", b, 1000.0, "https://b.example/y")]
    return len(group_offers(offers)) == 1


def evaluate(pairs: List[Pair], fuzzy: bool = True) -> dict:
    old = matching.FUZZY_RESCUE
    matching.FUZZY_RESCUE = fuzzy
    try:
        tp = fp = fn = tn = 0
        mistakes = []
        for p in pairs:
            got = predict(p.a, p.b)
            if got and p.same:
                tp += 1
            elif got and not p.same:
                fp += 1
                mistakes.append({"type": "false merge", "a": p.a, "b": p.b, "note": p.note})
            elif not got and p.same:
                fn += 1
                mistakes.append({"type": "missed match", "a": p.a, "b": p.b, "note": p.note})
            else:
                tn += 1
    finally:
        matching.FUZZY_RESCUE = old
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"pairs": len(pairs), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall,
            "f1": f1, "accuracy": (tp + tn) / len(pairs) if pairs else 0.0, "mistakes": mistakes}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--pairs", type=Path, default=PAIRS)
    args = ap.parse_args()
    pairs = load_pairs(args.pairs)
    with_fuzzy = evaluate(pairs, fuzzy=True)
    without = evaluate(pairs, fuzzy=False)
    if args.json:
        print(json.dumps({"with_fuzzy": with_fuzzy, "jaccard_only": without}, indent=2))
        return
    print(f"{len(pairs)} labelled pairs ({sum(p.same for p in pairs)} same, {sum(not p.same for p in pairs)} different)\n")
    print(f"{'':22}{'precision':>10}{'recall':>8}{'F1':>8}{'accuracy':>10}{'false merges':>14}{'missed':>8}")
    for name, r in (("Jaccard + spec guards", without), ("+ fuzzy tiebreaker", with_fuzzy)):
        print(f"{name:22}{r['precision']:10.1%}{r['recall']:8.1%}{r['f1']:8.1%}{r['accuracy']:10.1%}{r['fp']:14d}{r['fn']:8d}")
    if with_fuzzy["mistakes"]:
        print("\nMistakes (with fuzzy tiebreaker):")
        for m in with_fuzzy["mistakes"]:
            print(f"  [{m['type']}] {m['a']}\n     vs {m['b']}" + (f"   ({m['note']})" if m["note"] else ""))


if __name__ == "__main__":
    main()
