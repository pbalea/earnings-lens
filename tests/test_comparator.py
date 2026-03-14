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

    def test_dropped_topic_contributes_weight_times_two(self):
        diff = _make_diff(dropped=[{"prev_weight": 0.10}])
        assert compute_drift_score(diff) == pytest.approx(0.20, abs=1e-4)

    def test_new_topic_contributes_weight_times_one_point_five(self):
        diff = _make_diff(new_topics=[{"curr_weight": 0.10}])
        assert compute_drift_score(diff) == pytest.approx(0.15, abs=1e-4)

    def test_flagged_matched_topic_contributes_abs_delta(self):
        matched = [{
            "weight_delta": 0.12,
            "flagged": True,
            "sentiment_degraded": False,
        }]
        diff = _make_diff(matched=matched)
        assert compute_drift_score(diff) == pytest.approx(0.12, abs=1e-4)

    def test_sentiment_degradation_adds_fixed_0_15(self):
        matched = [{
            "weight_delta": 0.00,
            "flagged": False,
            "sentiment_degraded": True,
        }]
        diff = _make_diff(matched=matched)
        assert compute_drift_score(diff) == pytest.approx(0.15, abs=1e-4)

    def test_clamped_to_1_0(self):
        # Two large dropped topics would exceed 1.0
        diff = _make_diff(
            dropped=[{"prev_weight": 0.50}, {"prev_weight": 0.50}]
        )
        assert compute_drift_score(diff) == 1.0

    def test_combined_signals(self):
        # dropped 0.10 → +0.20
        # new 0.10     → +0.15
        # matched flagged delta 0.09 → +0.09
        # sentiment degraded        → +0.15
        # total = 0.59
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
        assert compute_drift_score(diff) == pytest.approx(0.59, abs=1e-4)

    def test_unflagged_matched_does_not_contribute(self):
        matched = [{
            "weight_delta": 0.05,
            "flagged": False,
            "sentiment_degraded": False,
        }]
        diff = _make_diff(matched=matched)
        assert compute_drift_score(diff) == 0.0

    def test_multiple_dropped_topics_accumulated(self):
        diff = _make_diff(
            dropped=[{"prev_weight": 0.05}, {"prev_weight": 0.10}]
        )
        # 0.05*2 + 0.10*2 = 0.30
        assert compute_drift_score(diff) == pytest.approx(0.30, abs=1e-4)
