import json
from typing import Any

import anthropic

from app.config import settings

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_SONNET_MODEL = "claude-sonnet-4-6"

_EXTRACT_SYSTEM = (
    "You are a financial analyst extracting structured topic data from earnings call "
    "transcripts. Always respond with valid JSON only. No preamble."
)

_EXTRACT_USER_TMPL = """Extract 8-12 primary topics from these prepared remarks for {ticker}.
For each topic return:
- label: normalized financial term (lowercase, consistent)
- weight: proportion of remarks devoted to it (float, all weights sum to 1.0)
- sentiment: one of [positive, neutral, cautious, negative]
- key_quote: single most representative verbatim quote (under 30 words)
- hedging_phrases: list of hedging/qualifier words used in this topic

Also include a top-level 'guidance_present' boolean: true if management gave \
explicit forward guidance, false if absent.

Respond ONLY as JSON:
{{
  "guidance_present": true,
  "topics": [
    {{
      "label": "...",
      "weight": 0.0,
      "sentiment": "...",
      "key_quote": "...",
      "hedging_phrases": []
    }}
  ]
}}

Prepared remarks:
{prepared_remarks}"""

_NARRATIVE_TMPL = """Write a 3-sentence analyst note for {ticker} summarizing the most significant \
quarter-over-quarter topic shifts. Be specific — name the actual topics. \
Focus on what was dropped, de-emphasized, or newly introduced. \
Drift score context: {drift_score} (0=no change, 1.0=major shift).

Diff data: {diff_json}"""


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def extract_topics(prepared_remarks: str, ticker: str) -> dict:
    """Call Haiku to extract structured topic data from prepared remarks.

    Returns the parsed JSON dict with keys: guidance_present, topics.
    """
    client = _get_client()
    response = client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=2048,
        system=_EXTRACT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": _EXTRACT_USER_TMPL.format(
                    ticker=ticker,
                    prepared_remarks=prepared_remarks,
                ),
            }
        ],
    )
    raw = response.content[0].text.strip()
    return json.loads(raw)


def compare_quarters(prev_topics: dict, curr_topics: dict, ticker: str) -> dict:
    """Pure-Python quarter-over-quarter topic diff. No Claude call.

    Args:
        prev_topics: dict returned by extract_topics() for the prior quarter.
        curr_topics: dict returned by extract_topics() for the current quarter.
        ticker: company ticker (used for labelling only).

    Returns a diff dict with keys:
        ticker, matched, dropped, new_topics, drift_score
    """
    _SENTIMENT_ORDER = {"positive": 0, "neutral": 1, "cautious": 2, "negative": 3}

    prev_map: dict[str, Any] = {t["label"]: t for t in prev_topics.get("topics", [])}
    curr_map: dict[str, Any] = {t["label"]: t for t in curr_topics.get("topics", [])}

    prev_labels = set(prev_map)
    curr_labels = set(curr_map)
    common_labels = prev_labels & curr_labels

    matched = []
    drift_accumulator = 0.0

    for label in common_labels:
        prev_t = prev_map[label]
        curr_t = curr_map[label]
        weight_delta = curr_t["weight"] - prev_t["weight"]
        prev_rank = _SENTIMENT_ORDER.get(prev_t["sentiment"], 1)
        curr_rank = _SENTIMENT_ORDER.get(curr_t["sentiment"], 1)
        sentiment_degraded = curr_rank > prev_rank

        flagged = abs(weight_delta) > 0.08 or sentiment_degraded

        if flagged:
            drift_accumulator += abs(weight_delta) * 1.0
        if sentiment_degraded:
            drift_accumulator += 0.15

        matched.append({
            "label": label,
            "prev_weight": prev_t["weight"],
            "curr_weight": curr_t["weight"],
            "weight_delta": round(weight_delta, 4),
            "prev_sentiment": prev_t["sentiment"],
            "curr_sentiment": curr_t["sentiment"],
            "sentiment_degraded": sentiment_degraded,
            "flagged": flagged,
        })

    dropped = []
    for label in prev_labels - curr_labels:
        w = prev_map[label]["weight"]
        drift_accumulator += w * 2.0
        dropped.append({"label": label, "prev_weight": w})

    new_topics = []
    for label in curr_labels - prev_labels:
        w = curr_map[label]["weight"]
        drift_accumulator += w * 1.5
        new_topics.append({"label": label, "curr_weight": w})

    drift_score = round(min(drift_accumulator, 1.0), 4)

    return {
        "ticker": ticker,
        "matched": matched,
        "dropped": dropped,
        "new_topics": new_topics,
        "drift_score": drift_score,
        "guidance_present_prev": prev_topics.get("guidance_present"),
        "guidance_present_curr": curr_topics.get("guidance_present"),
    }


def generate_narrative(diff: dict, ticker: str, drift_score: float) -> str:
    """Call Sonnet to produce a 3-sentence analyst note about QoQ topic shifts."""
    client = _get_client()
    prompt = _NARRATIVE_TMPL.format(
        ticker=ticker,
        drift_score=drift_score,
        diff_json=json.dumps(diff, indent=2),
    )
    response = client.messages.create(
        model=_SONNET_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()
