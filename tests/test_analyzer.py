import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.analyzer import extract_topics, compare_quarters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(payload: dict):
    """Build a mock anthropic Messages response containing JSON payload."""
    content_block = MagicMock()
    content_block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [content_block]
    return response


_SAMPLE_EXTRACTION = {
    "guidance_present": True,
    "topics": [
        {
            "label": "revenue growth",
            "weight": 0.25,
            "sentiment": "positive",
            "key_quote": "Revenue grew 18% year over year.",
            "hedging_phrases": [],
        },
        {
            "label": "operating margins",
            "weight": 0.20,
            "sentiment": "positive",
            "key_quote": "Operating margin expanded 200bps.",
            "hedging_phrases": ["expect"],
        },
        {
            "label": "supply chain",
            "weight": 0.15,
            "sentiment": "cautious",
            "key_quote": "We continue to monitor supply chain risks.",
            "hedging_phrases": ["continue to monitor", "risks"],
        },
        {
            "label": "product innovation",
            "weight": 0.15,
            "sentiment": "positive",
            "key_quote": "New product launches exceeded expectations.",
            "hedging_phrases": [],
        },
        {
            "label": "international expansion",
            "weight": 0.10,
            "sentiment": "neutral",
            "key_quote": "We are exploring new international markets.",
            "hedging_phrases": ["exploring"],
        },
        {
            "label": "cost management",
            "weight": 0.08,
            "sentiment": "positive",
            "key_quote": "Operating expenses declined 5% sequentially.",
            "hedging_phrases": [],
        },
        {
            "label": "capital allocation",
            "weight": 0.04,
            "sentiment": "neutral",
            "key_quote": "We repurchased $500M in shares.",
            "hedging_phrases": [],
        },
        {
            "label": "regulatory environment",
            "weight": 0.03,
            "sentiment": "cautious",
            "key_quote": "Regulatory changes may impact our business.",
            "hedging_phrases": ["may"],
        },
    ],
}


# ---------------------------------------------------------------------------
# extract_topics tests
# ---------------------------------------------------------------------------

class TestExtractTopics:
    @patch("app.services.analyzer._get_client")
    def test_returns_parsed_dict(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_SAMPLE_EXTRACTION)

        result = extract_topics("Some prepared remarks.", "AAPL")

        assert isinstance(result, dict)
        assert "topics" in result
        assert "guidance_present" in result

    @patch("app.services.analyzer._get_client")
    def test_guidance_present_field_is_bool(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_SAMPLE_EXTRACTION)

        result = extract_topics("Some prepared remarks.", "AAPL")
        assert isinstance(result["guidance_present"], bool)

    @patch("app.services.analyzer._get_client")
    def test_topics_is_list(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_SAMPLE_EXTRACTION)

        result = extract_topics("Some prepared remarks.", "AAPL")
        assert isinstance(result["topics"], list)
        assert len(result["topics"]) == 8

    @patch("app.services.analyzer._get_client")
    def test_each_topic_has_required_keys(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_SAMPLE_EXTRACTION)

        result = extract_topics("Some remarks.", "MSFT")
        for topic in result["topics"]:
            assert "label" in topic
            assert "weight" in topic
            assert "sentiment" in topic
            assert "key_quote" in topic
            assert "hedging_phrases" in topic

    @patch("app.services.analyzer._get_client")
    def test_uses_haiku_model(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_SAMPLE_EXTRACTION)

        extract_topics("Some remarks.", "GOOG")

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == "claude-haiku-4-5-20251001"

    @patch("app.services.analyzer._get_client")
    def test_ticker_in_user_prompt(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.messages.create.return_value = _mock_response(_SAMPLE_EXTRACTION)

        extract_topics("Remarks here.", "TSLA")

        call_kwargs = mock_client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "TSLA" in user_content


# ---------------------------------------------------------------------------
# compare_quarters tests
# ---------------------------------------------------------------------------

_PREV = {
    "guidance_present": True,
    "topics": [
        {"label": "revenue growth", "weight": 0.30, "sentiment": "positive"},
        {"label": "supply chain", "weight": 0.20, "sentiment": "neutral"},
        {"label": "cost management", "weight": 0.15, "sentiment": "positive"},
        {"label": "old topic", "weight": 0.10, "sentiment": "positive"},
    ],
}

_CURR = {
    "guidance_present": True,
    "topics": [
        {"label": "revenue growth", "weight": 0.20, "sentiment": "cautious"},  # degraded
        {"label": "supply chain", "weight": 0.25, "sentiment": "neutral"},    # delta 0.05
        {"label": "cost management", "weight": 0.05, "sentiment": "positive"},  # delta -0.10 → flagged
        {"label": "new topic", "weight": 0.12, "sentiment": "positive"},       # new
    ],
}


class TestCompareQuarters:
    def test_returns_diff_dict(self):
        result = compare_quarters(_PREV, _CURR, "AAPL")
        assert isinstance(result, dict)

    def test_identifies_dropped_topic(self):
        result = compare_quarters(_PREV, _CURR, "AAPL")
        dropped_labels = [t["label"] for t in result["dropped"]]
        assert "old topic" in dropped_labels

    def test_identifies_new_topic(self):
        result = compare_quarters(_PREV, _CURR, "AAPL")
        new_labels = [t["label"] for t in result["new_topics"]]
        assert "new topic" in new_labels

    def test_drift_score_is_float_in_range(self):
        result = compare_quarters(_PREV, _CURR, "AAPL")
        assert isinstance(result["drift_score"], float)
        assert 0.0 <= result["drift_score"] <= 1.0

    def test_flagged_large_weight_delta(self):
        result = compare_quarters(_PREV, _CURR, "AAPL")
        cost_entry = next(
            (m for m in result["matched"] if m["label"] == "cost management"), None
        )
        assert cost_entry is not None
        assert cost_entry["flagged"] is True  # delta = -0.10 > 0.08 threshold

    def test_sentiment_degradation_detected(self):
        result = compare_quarters(_PREV, _CURR, "AAPL")
        rev_entry = next(
            (m for m in result["matched"] if m["label"] == "revenue growth"), None
        )
        assert rev_entry is not None
        assert rev_entry["sentiment_degraded"] is True  # positive → cautious

    def test_ticker_in_result(self):
        result = compare_quarters(_PREV, _CURR, "AAPL")
        assert result["ticker"] == "AAPL"
