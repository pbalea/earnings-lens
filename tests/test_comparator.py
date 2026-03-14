import pytest
from app.services.comparator import compute_drift_score


def _make_diff(dropped=None, new_topics=None, matched=None):
    return {
        "dropped": dropped or [],
        "new_topics": new_topics or [],
        "matched": matched or [],
    }


class TestComputeDriftScore:
    def test_zero_drift_no_changes(self):
        diff = _make_diff()
        assert compute_drift_score(diff) == 0.0

    def test_dropped_topic_contributes_weight_times_0_8(self):
        # 0.10 * 0.8 = 0.08
        diff = _make_diff(dropped=[{"prev_weight": 0.10}])
        assert compute_drift_score(diff) == pytest.approx(0.08, abs=1e-4)

    def test_new_topic_contributes_weight_times_0_6(self):
        # 0.10 * 0.6 = 0.06
        diff = _make_diff(new_topics=[{"curr_weight": 0.10}])
        assert compute_drift_score(diff) == pytest.approx(0.06, abs=1e-4)

    def test_flagged_matched_topic_contributes_abs_delta(self):
        # flagged multiplier is unchanged at 1.0
        matched = [{
            "weight_delta": 0.12,
            "flagged": True,
            "sentiment_degraded": False,
        }]
        diff = _make_diff(matched=matched)
        assert compute_drift_score(diff) == pytest.approx(0.12, abs=1e-4)

    def test_sentiment_degradation_adds_0_08(self):
        matched = [{
            "weight_delta": 0.00,
            "flagged": False,
            "sentiment_degraded": True,
        }]
        diff = _make_diff(matched=matched)
        assert compute_drift_score(diff) == pytest.approx(0.08, abs=1e-4)

    def test_clamped_to_1_0(self):
        # Need large weights to exceed 1.0 with new multipliers:
        # 0.70*0.8 + 0.70*0.8 = 1.12 → clamped
        diff = _make_diff(
            dropped=[{"prev_weight": 0.70}, {"prev_weight": 0.70}]
        )
        assert compute_drift_score(diff) == 1.0

    def test_combined_signals(self):
        # dropped 0.10  → 0.10 * 0.8  = 0.08
        # new 0.10      → 0.10 * 0.6  = 0.06
        # matched flagged delta 0.09  → 0.09 * 1.0 = 0.09
        # sentiment degraded          → +0.08
        # total = 0.31
        matched = [{
            "weight_delta": 0.09,
            "flagged": True,
            "sentiment_degraded": True,
        }]
        diff = _make_diff(
            dropped=[{"prev_weight": 0.10}],
            new_topics=[{"curr_weight": 0.10}],
            matched=matched,
        )
        assert compute_drift_score(diff) == pytest.approx(0.31, abs=1e-4)

    def test_unflagged_matched_does_not_contribute(self):
        matched = [{
            "weight_delta": 0.05,
            "flagged": False,
            "sentiment_degraded": False,
        }]
        diff = _make_diff(matched=matched)
        assert compute_drift_score(diff) == 0.0

    def test_multiple_dropped_topics_accumulated(self):
        # 0.05*0.8 + 0.10*0.8 = 0.04 + 0.08 = 0.12
        diff = _make_diff(
            dropped=[{"prev_weight": 0.05}, {"prev_weight": 0.10}]
        )
        assert compute_drift_score(diff) == pytest.approx(0.12, abs=1e-4)

    def test_aapl_scenario_scores_in_range(self):
        # Mirrors the real AAPL Q4-2025 vs Q1-2026 diff:
        # 4 dropped (0.08+0.07+0.03+0.10), 2 new (0.08+0.08),
        # 1 flagged weight-delta (0.09), 1 sentiment-degraded
        matched = [
            {"weight_delta": 0.09, "flagged": True,  "sentiment_degraded": False},
            {"weight_delta": 0.01, "flagged": True,  "sentiment_degraded": True},
        ]
        diff = _make_diff(
            dropped=[
                {"prev_weight": 0.08}, {"prev_weight": 0.07},
                {"prev_weight": 0.03}, {"prev_weight": 0.10},
            ],
            new_topics=[{"curr_weight": 0.08}, {"curr_weight": 0.08}],
            matched=matched,
        )
        score = compute_drift_score(diff)
        assert 0.3 <= score <= 0.6, f"Expected 0.3-0.6, got {score}"
