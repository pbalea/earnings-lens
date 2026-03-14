from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------

class CompanyCreate(BaseModel):
    ticker: str = Field(..., max_length=20)
    name: str = Field(..., max_length=255)
    sector: Optional[str] = Field(None, max_length=100)


class CompanyOut(BaseModel):
    id: int
    ticker: str
    name: str
    sector: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------

class TranscriptIngest(BaseModel):
    ticker: str = Field(..., max_length=20)
    url: str
    fiscal_quarter: str = Field(..., pattern=r"^Q[1-4]$")
    fiscal_year: int = Field(..., ge=2000, le=2100)


class TranscriptOut(BaseModel):
    id: int
    company_id: int
    fiscal_quarter: str
    fiscal_year: int
    source_url: Optional[str]
    fetched_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# TopicExtraction
# ---------------------------------------------------------------------------

class TopicExtractionOut(BaseModel):
    id: int
    transcript_id: int
    topics: Any
    extracted_at: Optional[datetime]
    model_used: Optional[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# QuarterComparison
# ---------------------------------------------------------------------------

class QuarterComparisonOut(BaseModel):
    id: int
    company_id: int
    current_transcript_id: int
    prior_transcript_id: int
    diff_json: Optional[Any]
    drift_score: Optional[float]
    narrative_summary: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

class AlertOut(BaseModel):
    id: int
    company_id: int
    comparison_id: int
    alert_type: str
    severity: str
    message: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Ingest response
# ---------------------------------------------------------------------------

class IngestResponse(BaseModel):
    transcript: TranscriptOut
    extraction: TopicExtractionOut
    comparison: Optional[QuarterComparisonOut] = None
    alerts_created: int = 0
