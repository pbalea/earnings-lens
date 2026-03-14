from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.services.scraper import fetch_motley_fool_transcript
from app.services.parser import segment_transcript
from app.services.analyzer import (
    align_topic_labels,
    compare_quarters,
    extract_topics,
    generate_narrative,
)

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

_SENTIMENT_ORDER = {"positive": 0, "neutral": 1, "cautious": 2, "negative": 3}


def _quarter_key(t: models.Transcript) -> tuple[int, int]:
    """Numeric sort key for a transcript: (fiscal_year, quarter_number).

    Uses int(quarter[1]) so "Q4" → 4 and comparisons like
    Q4 2025 < Q1 2026 work correctly across year boundaries.
    """
    return (t.fiscal_year, int(t.fiscal_quarter[1]))


def _prior_transcript(
    db: Session,
    company_id: int,
    fiscal_quarter: str,
    fiscal_year: int,
    exclude_id: int | None = None,
) -> models.Transcript | None:
    """Return the most recent transcript strictly before (fiscal_year, fiscal_quarter).

    Excludes the transcript with exclude_id (the one just committed) so we
    never accidentally pick the current record as its own prior.
    """
    q = db.query(models.Transcript).filter(models.Transcript.company_id == company_id)
    if exclude_id is not None:
        q = q.filter(models.Transcript.id != exclude_id)

    current_key = (fiscal_year, int(fiscal_quarter[1]))
    candidates = [t for t in q.all() if _quarter_key(t) < current_key]
    if not candidates:
        return None
    return max(candidates, key=_quarter_key)


def _severity_from_drift(drift_score: float) -> str:
    if drift_score >= 0.4:
        return "high"
    if drift_score >= 0.2:
        return "medium"
    return "low"


def _build_alerts(diff: dict, drift_score: float, company_id: int, comparison_id: int) -> list[models.Alert]:
    alerts = []
    now = datetime.now(timezone.utc)

    if drift_score >= 0.2:
        alerts.append(models.Alert(
            company_id=company_id,
            comparison_id=comparison_id,
            alert_type="topic_drift",
            severity=_severity_from_drift(drift_score),
            message=f"Drift score {drift_score:.2f} indicates significant topic shift.",
            created_at=now,
        ))

    for entry in diff.get("dropped", []):
        if entry["prev_weight"] >= 0.10:
            alerts.append(models.Alert(
                company_id=company_id,
                comparison_id=comparison_id,
                alert_type="topic_dropped",
                severity="medium",
                message=f"Topic '{entry['label']}' (weight {entry['prev_weight']:.0%}) was dropped.",
                created_at=now,
            ))

    for entry in diff.get("matched", []):
        if entry.get("sentiment_degraded"):
            alerts.append(models.Alert(
                company_id=company_id,
                comparison_id=comparison_id,
                alert_type="sentiment_drop",
                severity="medium",
                message=(
                    f"Topic '{entry['label']}' sentiment degraded: "
                    f"{entry['prev_sentiment']} → {entry['curr_sentiment']}."
                ),
                created_at=now,
            ))

    return alerts


def _do_qoq_comparison(
    db: Session,
    company: models.Company,
    curr_transcript: models.Transcript,
    prior_transcript: models.Transcript,
) -> tuple[models.QuarterComparison, int]:
    """Run compare_quarters + generate_narrative and persist results.

    Returns (QuarterComparison, alerts_created).
    Raises HTTPException 422 if either transcript lacks an extraction.
    """
    curr_extraction = (
        db.query(models.TopicExtraction)
        .filter(models.TopicExtraction.transcript_id == curr_transcript.id)
        .order_by(models.TopicExtraction.extracted_at.desc())
        .first()
    )
    prior_extraction = (
        db.query(models.TopicExtraction)
        .filter(models.TopicExtraction.transcript_id == prior_transcript.id)
        .order_by(models.TopicExtraction.extracted_at.desc())
        .first()
    )

    if not curr_extraction or not prior_extraction:
        missing = []
        if not curr_extraction:
            missing.append(f"current (id={curr_transcript.id})")
        if not prior_extraction:
            missing.append(f"prior (id={prior_transcript.id})")
        raise HTTPException(
            status_code=422,
            detail=f"Missing topic extraction for transcript(s): {', '.join(missing)}.",
        )

    ticker = company.ticker

    # Fuzzy-match topic labels before diffing so semantically equivalent topics
    # (e.g. "iphone supply constraints" vs "iphone strength and demand") are
    # treated as the same topic rather than a drop+new pair.
    prev_labels = [t["label"] for t in prior_extraction.topics.get("topics", [])]
    curr_labels = [t["label"] for t in curr_extraction.topics.get("topics", [])]
    label_aliases = align_topic_labels(prev_labels, curr_labels, ticker)

    diff = compare_quarters(
        prior_extraction.topics, curr_extraction.topics, ticker,
        label_aliases=label_aliases,
    )
    drift_score = diff["drift_score"]

    try:
        narrative = generate_narrative(diff, ticker, drift_score)
    except Exception:
        narrative = None

    comparison = models.QuarterComparison(
        company_id=company.id,
        current_transcript_id=curr_transcript.id,
        prior_transcript_id=prior_transcript.id,
        diff_json=diff,
        drift_score=drift_score,
        narrative_summary=narrative,
    )
    db.add(comparison)
    db.commit()
    db.refresh(comparison)

    alert_rows = _build_alerts(diff, drift_score, company.id, comparison.id)
    for alert in alert_rows:
        db.add(alert)
    db.commit()

    return comparison, len(alert_rows)


@router.post("", response_model=schemas.IngestResponse, status_code=201)
def ingest_transcript(payload: schemas.TranscriptIngest, db: Session = Depends(get_db)):
    # 1. Resolve company
    company = db.query(models.Company).filter(
        models.Company.ticker == payload.ticker.upper()
    ).first()
    if not company:
        raise HTTPException(
            status_code=404,
            detail=f"Company {payload.ticker} not found. Add it via POST /companies first.",
        )

    # 2. Duplicate guard
    duplicate = db.query(models.Transcript).filter(
        models.Transcript.company_id == company.id,
        models.Transcript.fiscal_quarter == payload.fiscal_quarter,
        models.Transcript.fiscal_year == payload.fiscal_year,
    ).first()
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Transcript for {payload.ticker} {payload.fiscal_quarter} {payload.fiscal_year} "
                f"already exists (id={duplicate.id}). Delete it first or use run-comparison."
            ),
        )

    # 3. Fetch raw text
    try:
        raw_text = fetch_motley_fool_transcript(payload.ticker, payload.url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch transcript: {exc}")

    # 4. Parse into segments
    segments = segment_transcript(raw_text)

    # 5. Persist Transcript row
    transcript = models.Transcript(
        company_id=company.id,
        fiscal_quarter=payload.fiscal_quarter,
        fiscal_year=payload.fiscal_year,
        raw_text=raw_text,
        prepared_remarks=segments["prepared_remarks"],
        source_url=payload.url,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)

    # 6. Extract topics via Claude Haiku
    try:
        topics_data = extract_topics(segments["prepared_remarks"], payload.ticker)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Topic extraction failed: {exc}")

    extraction = models.TopicExtraction(
        transcript_id=transcript.id,
        topics=topics_data,
        model_used="claude-haiku-4-5-20251001",
    )
    db.add(extraction)
    db.commit()
    db.refresh(extraction)

    # 7. QoQ comparison — exclude the just-committed transcript so it can't
    #    match itself, then look for the most recent transcript before this one.
    comparison = None
    alerts_created = 0

    prior = _prior_transcript(
        db, company.id, payload.fiscal_quarter, payload.fiscal_year,
        exclude_id=transcript.id,
    )
    if prior:
        comparison, alerts_created = _do_qoq_comparison(db, company, transcript, prior)

    return schemas.IngestResponse(
        transcript=schemas.TranscriptOut.model_validate(transcript),
        extraction=schemas.TopicExtractionOut.model_validate(extraction),
        comparison=schemas.QuarterComparisonOut.model_validate(comparison) if comparison else None,
        alerts_created=alerts_created,
    )
