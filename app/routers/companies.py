from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas

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
