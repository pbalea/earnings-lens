from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Column, DateTime, Float, ForeignKey, Integer, String, Text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


def _now():
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    sector = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=_now)

    transcripts = relationship("Transcript", back_populates="company")
    alerts = relationship("Alert", back_populates="company")
    comparisons = relationship("QuarterComparison", back_populates="company",
                               foreign_keys="QuarterComparison.company_id")


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    fiscal_quarter = Column(String(2), nullable=False)   # Q1 / Q2 / Q3 / Q4
    fiscal_year = Column(Integer, nullable=False)
    raw_text = Column(Text)
    prepared_remarks = Column(Text)
    source_url = Column(Text)
    fetched_at = Column(DateTime(timezone=True), default=_now)

    company = relationship("Company", back_populates="transcripts")
    topic_extractions = relationship("TopicExtraction", back_populates="transcript")


class TopicExtraction(Base):
    __tablename__ = "topic_extractions"

    id = Column(Integer, primary_key=True, index=True)
    transcript_id = Column(Integer, ForeignKey("transcripts.id"), nullable=False)
    topics = Column(JSONB, nullable=False)       # full extract_topics() result
    extracted_at = Column(DateTime(timezone=True), default=_now)
    model_used = Column(String(100))

    transcript = relationship("Transcript", back_populates="topic_extractions")


class QuarterComparison(Base):
    __tablename__ = "quarter_comparisons"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    current_transcript_id = Column(Integer, ForeignKey("transcripts.id"), nullable=False)
    prior_transcript_id = Column(Integer, ForeignKey("transcripts.id"), nullable=False)
    diff_json = Column(JSONB)
    drift_score = Column(Float)
    narrative_summary = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_now)

    company = relationship("Company", back_populates="comparisons",
                           foreign_keys=[company_id])
    current_transcript = relationship("Transcript", foreign_keys=[current_transcript_id])
    prior_transcript = relationship("Transcript", foreign_keys=[prior_transcript_id])
    alerts = relationship("Alert", back_populates="comparison")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    comparison_id = Column(Integer, ForeignKey("quarter_comparisons.id"), nullable=False)
    alert_type = Column(String(100), nullable=False)   # e.g. "topic_drift", "sentiment_drop"
    severity = Column(String(20), nullable=False)      # "low", "medium", "high"
    message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_now)

    company = relationship("Company", back_populates="alerts")
    comparison = relationship("QuarterComparison", back_populates="alerts")
