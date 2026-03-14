"""initial schema

Revision ID: 280c86e75071
Revises:
Create Date: 2026-03-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "280c86e75071"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_companies_id", "companies", ["id"])
    op.create_index("ix_companies_ticker", "companies", ["ticker"], unique=True)

    op.create_table(
        "transcripts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", sa.String(2), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("prepared_remarks", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcripts_id", "transcripts", ["id"])

    op.create_table(
        "topic_extractions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=False),
        sa.Column("topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_topic_extractions_id", "topic_extractions", ["id"])

    op.create_table(
        "quarter_comparisons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("current_transcript_id", sa.Integer(), nullable=False),
        sa.Column("prior_transcript_id", sa.Integer(), nullable=False),
        sa.Column("diff_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("drift_score", sa.Float(), nullable=True),
        sa.Column("narrative_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["current_transcript_id"], ["transcripts.id"]),
        sa.ForeignKeyConstraint(["prior_transcript_id"], ["transcripts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quarter_comparisons_id", "quarter_comparisons", ["id"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("comparison_id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["comparison_id"], ["quarter_comparisons.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_id", "alerts", ["id"])


def downgrade() -> None:
    op.drop_index("ix_alerts_id", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_quarter_comparisons_id", table_name="quarter_comparisons")
    op.drop_table("quarter_comparisons")
    op.drop_index("ix_topic_extractions_id", table_name="topic_extractions")
    op.drop_table("topic_extractions")
    op.drop_index("ix_transcripts_id", table_name="transcripts")
    op.drop_table("transcripts")
    op.drop_index("ix_companies_ticker", table_name="companies")
    op.drop_index("ix_companies_id", table_name="companies")
    op.drop_table("companies")
