"""Regression guard: the matcher must stay above the accuracy reported in the README."""
from evaluation.evaluate import evaluate, load_pairs


def test_matcher_quality_on_labelled_pairs():
    pairs = load_pairs()
    assert len(pairs) >= 60
    r = evaluate(pairs, fuzzy=True)
    assert r["precision"] >= 0.90, r["mistakes"]
    assert r["recall"] >= 0.90, r["mistakes"]
    assert r["f1"] >= 0.90


def test_fuzzy_tiebreaker_does_not_hurt():
    pairs = load_pairs()
    assert evaluate(pairs, fuzzy=True)["f1"] >= evaluate(pairs, fuzzy=False)["f1"]
