"""comparator.py — thin wrapper exposing compute_drift_score for testing.

The full compare_quarters() logic lives in analyzer.py because the spec
describes it as part of that service. This module re-exports the helper
so tests can target it directly without importing the Claude client.
"""
from __future__ import annotations

_SENTIMENT_ORDER = {"positive": 0, "neutral": 1, "cautious": 2, "negative": 3}


def compute_drift_score(diff: dict) -> float:
    """Recompute drift_score from a diff dict produced by compare_quarters().

    Useful in tests and as a standalone verification utility.

    Scoring rules (clamped to [0.0, 1.0]):
      - Each dropped topic:            weight * 0.8
      - Each new topic:                weight * 0.6
      - Each flagged matched topic:    abs(weight_delta) * 1.0
      - Each sentiment degradation:    + 0.08
    Calibrated so that 8+ matched topics with 3-4 dropped/new scores
    ~0.3-0.5; only majority-drop + multi-sentiment-collapse exceeds 0.7.
    """
    total = 0.0

    for entry in diff.get("dropped", []):
        total += entry["prev_weight"] * 0.8

    for entry in diff.get("new_topics", []):
        total += entry["curr_weight"] * 0.6

    for entry in diff.get("matched", []):
        if entry.get("flagged"):
            total += abs(entry["weight_delta"]) * 1.0
        if entry.get("sentiment_degraded"):
            total += 0.08

    return round(min(total, 1.0), 4)
