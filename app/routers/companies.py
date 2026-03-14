from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.routers.transcripts import _do_qoq_comparison, _quarter_key

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[schemas.CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return db.query(models.Company).order_by(models.Company.ticker).all()


@router.post("", response_model=schemas.CompanyOut, status_code=201)
def create_company(payload: schemas.CompanyCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Company).filter(
        models.Company.ticker == payload.ticker.upper()
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Company {payload.ticker} already exists.")

    company = models.Company(
        ticker=payload.ticker.upper(),
        name=payload.name,
        sector=payload.sector,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/{ticker}/transcripts", response_model=list[schemas.TranscriptOut])
def list_transcripts(ticker: str, db: Session = Depends(get_db)):
    company = db.query(models.Company).filter(
        models.Company.ticker == ticker.upper()
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found.")
    return (
        db.query(models.Transcript)
        .filter(models.Transcript.company_id == company.id)
        .order_by(models.Transcript.fiscal_year.desc(), models.Transcript.fiscal_quarter.desc())
        .all()
    )


@router.get("/{ticker}/run-comparison", response_model=schemas.IngestResponse)
def run_comparison(ticker: str, db: Session = Depends(get_db)):
    """Manually trigger a QoQ comparison between the two most recent transcripts.

    Useful when transcripts were ingested out of order and no comparison was
    automatically created at ingest time.
    """
    company = db.query(models.Company).filter(
        models.Company.ticker == ticker.upper()
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found.")

    all_transcripts = (
        db.query(models.Transcript)
        .filter(models.Transcript.company_id == company.id)
        .all()
    )
    if len(all_transcripts) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"Need at least 2 transcripts for {ticker}; found {len(all_transcripts)}.",
        )

    # Deduplicate by quarter: for each (year, quarter) keep the one fetched most recently.
    # This handles cases where the same quarter was accidentally ingested twice.
    best_per_quarter: dict[tuple, models.Transcript] = {}
    for t in all_transcripts:
        key = _quarter_key(t)
        existing = best_per_quarter.get(key)
        if existing is None or (t.fetched_at or 0) > (existing.fetched_at or 0):
            best_per_quarter[key] = t

    unique_transcripts = sorted(best_per_quarter.values(), key=_quarter_key, reverse=True)

    if len(unique_transcripts) < 2:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Need at least 2 distinct quarters for {ticker}; "
                f"found {len(unique_transcripts)} after deduplication."
            ),
        )

    curr_transcript = unique_transcripts[0]
    prior_transcript = unique_transcripts[1]

    comparison, alerts_created = _do_qoq_comparison(db, company, curr_transcript, prior_transcript)

    curr_extraction = (
        db.query(models.TopicExtraction)
        .filter(models.TopicExtraction.transcript_id == curr_transcript.id)
        .order_by(models.TopicExtraction.extracted_at.desc())
        .first()
    )

    return schemas.IngestResponse(
        transcript=schemas.TranscriptOut.model_validate(curr_transcript),
        extraction=schemas.TopicExtractionOut.model_validate(curr_extraction),
        comparison=schemas.QuarterComparisonOut.model_validate(comparison),
        alerts_created=alerts_created,
    )


@router.get("/{ticker}/latest-analysis", response_model=schemas.QuarterComparisonOut)
def latest_analysis(ticker: str, db: Session = Depends(get_db)):
    company = db.query(models.Company).filter(
        models.Company.ticker == ticker.upper()
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {ticker} not found.")

    comparison = (
        db.query(models.QuarterComparison)
        .filter(models.QuarterComparison.company_id == company.id)
        .order_by(models.QuarterComparison.created_at.desc())
        .first()
    )
    if not comparison:
        raise HTTPException(status_code=404, detail="No analysis found for this company.")
    return comparison
