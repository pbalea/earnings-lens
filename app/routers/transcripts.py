from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.services.scraper import fetch_motley_fool_transcript
from app.services.parser import segment_transcript
from app.services.analyzer import extract_topics, compare_quarters, generate_narrative

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

_SENTIMENT_ORDER = {"positive": 0, "neutral": 1, "cautious": 2, "negative": 3}


def _prior_transcript(db: Session, company_id: int, fiscal_quarter: str, fiscal_year: int):
    """Return the most recent transcript before the given quarter/year, or None."""
    all_transcripts = (
        db.query(models.Transcript)
        .filter(models.Transcript.company_id == company_id)
        .all()
    )
    candidates = []
    for t in all_transcripts:
        if (t.fiscal_year, t.fiscal_quarter) < (fiscal_year, fiscal_quarter):
            candidates.append(t)
    if not candidates:
        return None
    return max(candidates, key=lambda t: (t.fiscal_year, t.fiscal_quarter))


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

    # 2. Fetch raw text
    try:
        raw_text = fetch_motley_fool_transcript(payload.ticker, payload.url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch transcript: {exc}")

    # 3. Parse into segments
    segments = segment_transcript(raw_text)

    # 4. Persist Transcript row
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

    # 5. Extract topics via Claude Haiku
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

    # 6. QoQ comparison if prior transcript exists
    comparison = None
    alerts_created = 0

    prior = _prior_transcript(db, company.id, payload.fiscal_quarter, payload.fiscal_year)
    if prior:
        prior_extraction = (
            db.query(models.TopicExtraction)
            .filter(models.TopicExtraction.transcript_id == prior.id)
            .order_by(models.TopicExtraction.extracted_at.desc())
            .first()
        )
        if prior_extraction:
            diff = compare_quarters(prior_extraction.topics, topics_data, payload.ticker)
            drift_score = diff["drift_score"]

            try:
                narrative = generate_narrative(diff, payload.ticker, drift_score)
            except Exception:
                narrative = None

            comparison = models.QuarterComparison(
                company_id=company.id,
                current_transcript_id=transcript.id,
                prior_transcript_id=prior.id,
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
            alerts_created = len(alert_rows)

    return schemas.IngestResponse(
        transcript=schemas.TranscriptOut.model_validate(transcript),
        extraction=schemas.TopicExtractionOut.model_validate(extraction),
        comparison=schemas.QuarterComparisonOut.model_validate(comparison) if comparison else None,
        alerts_created=alerts_created,
    )
