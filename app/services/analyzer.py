import json
import re
import sys
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

_ALIGN_USER_TMPL = """These are topic labels extracted from two consecutive earnings call transcripts for {ticker}.
Some topics cover the same business subject but were phrased differently across quarters.

Prior quarter labels:
{prev_labels}

Current quarter labels:
{curr_labels}

Map each prior-quarter label to the most semantically equivalent current-quarter label.
Only create a mapping when you are confident they refer to the same underlying business topic.
Do not force mappings for topics that are genuinely different subjects.

Respond ONLY as a flat JSON object — prior label as key, matching current label as value:
{{"prior label here": "current label here"}}

If no prior label has a clear semantic match, respond with: {{}}"""

_NARRATIVE_TMPL = """Write a 3-sentence analyst note for {ticker} summarizing the most significant \
quarter-over-quarter topic shifts. Be specific — name the actual topics. \
Focus on what was dropped, de-emphasized, or newly introduced. \
Drift score context: {drift_score} (0=no change, 1.0=major shift).

Diff data: {diff_json}"""


_DEFAULT_TOPICS = {
    "guidance_present": False,
    "topics": [],
    "_parse_error": True,
}


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that Claude sometimes adds despite instructions."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _get_client() -> anthropic.Anthropic:
    key = settings.anthropic_api_key
    masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "(empty)"
    print(f"[analyzer] anthropic_api_key loaded: {masked}", file=sys.stderr)
    return anthropic.Anthropic(api_key=key)


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
    print(f"[analyzer] stop_reason={response.stop_reason}", file=sys.stderr)
    print(f"[analyzer] raw response ({len(raw)} chars):\n{raw[:500]}", file=sys.stderr)

    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(
            f"[analyzer] JSON parse failed for {ticker}: {exc}\n"
            f"Full raw response:\n{raw}",
            file=sys.stderr,
        )
        return {**_DEFAULT_TOPICS, "_raw_response": raw}


def align_topic_labels(
    prev_labels: list[str],
    curr_labels: list[str],
    ticker: str,
) -> dict[str, str]:
    """Ask Haiku to map semantically equivalent topic labels across quarters.

    Returns a dict {prev_label: curr_label} for topics that refer to the same
    subject despite different phrasing. Labels with no confident match are
    omitted. Falls back to {} on any error so the diff can still proceed.
    """
    if not prev_labels or not curr_labels:
        return {}

    client = _get_client()
    prompt = _ALIGN_USER_TMPL.format(
        ticker=ticker,
        prev_labels="\n".join(f"- {l}" for l in prev_labels),
        curr_labels="\n".join(f"- {l}" for l in curr_labels),
    )
    try:
        response = client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=512,
            system="You are a financial analyst. Respond with valid JSON only. No preamble.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        print(f"[analyzer] align_topic_labels raw: {raw}", file=sys.stderr)
        mapping = json.loads(_strip_fences(raw))
        # Validate: only keep entries where both keys and values are known labels
        curr_set = set(curr_labels)
        prev_set = set(prev_labels)
        validated = {
            k: v for k, v in mapping.items()
            if isinstance(k, str) and isinstance(v, str)
            and k in prev_set and v in curr_set
        }
        print(f"[analyzer] topic aliases ({len(validated)}): {validated}", file=sys.stderr)
        return validated
    except Exception as exc:
        print(f"[analyzer] align_topic_labels failed, skipping: {exc}", file=sys.stderr)
        return {}


def compare_quarters(
    prev_topics: dict,
    curr_topics: dict,
    ticker: str,
    label_aliases: dict[str, str] | None = None,
) -> dict:
    """Quarter-over-quarter topic diff.

    Args:
        prev_topics:   dict from extract_topics() for the prior quarter.
        curr_topics:   dict from extract_topics() for the current quarter.
        ticker:        company ticker (for labelling only).
        label_aliases: optional {prev_label: curr_label} map from
                       align_topic_labels(). Matched aliases are treated as
                       the same topic and produce a weight/sentiment delta
                       instead of a drop+new pair.

    Returns a diff dict with keys:
        ticker, matched, dropped, new_topics, drift_score
    """
    _SENTIMENT_ORDER = {"positive": 0, "neutral": 1, "cautious": 2, "negative": 3}

    aliases = label_aliases or {}

    # Build prev_map with aliases applied so renamed labels line up with curr.
    raw_prev_map: dict[str, Any] = {t["label"]: t for t in prev_topics.get("topics", [])}
    prev_map: dict[str, Any] = {}
    alias_used: dict[str, str] = {}  # curr_label → original prev_label
    for label, topic in raw_prev_map.items():
        mapped = aliases.get(label, label)
        prev_map[mapped] = topic
        if mapped != label:
            alias_used[mapped] = label

    curr_map: dict[str, Any] = {t["label"]: t for t in curr_topics.get("topics", [])}

    prev_label_set = set(prev_map)
    curr_label_set = set(curr_map)
    common_labels = prev_label_set & curr_label_set

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

        entry: dict[str, Any] = {
            "label": label,
            "prev_weight": prev_t["weight"],
            "curr_weight": curr_t["weight"],
            "weight_delta": round(weight_delta, 4),
            "prev_sentiment": prev_t["sentiment"],
            "curr_sentiment": curr_t["sentiment"],
            "sentiment_degraded": sentiment_degraded,
            "flagged": flagged,
        }
        # Preserve original label for display when an alias was used
        if label in alias_used:
            entry["prev_label"] = alias_used[label]
        matched.append(entry)

    dropped = []
    for label in prev_label_set - curr_label_set:
        w = prev_map[label]["weight"]
        drift_accumulator += w * 2.0
        # Recover original label for display (may have been aliased but unmatched)
        orig = alias_used.get(label, label)
        dropped.append({"label": orig, "prev_weight": w})

    new_topics = []
    for label in curr_label_set - prev_label_set:
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


def _strip_markdown(text: str) -> str:
    """Remove common markdown formatting so narrative renders as plain text."""
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Italic: *text* or _text_
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"_(.+?)_", r"\1", text)
    # ATX headings: ## Heading
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    return text.strip()


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
    return _strip_markdown(response.content[0].text)
