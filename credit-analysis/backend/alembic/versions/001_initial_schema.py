"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users (managed by fastapi-users)
    op.create_table(
        "user",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(1024), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, default=True),
        sa.Column("is_superuser", sa.Boolean, nullable=False, default=False),
        sa.Column("is_verified", sa.Boolean, nullable=False, default=False),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    # companies
    op.create_table(
        "companies",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("ticker", sa.String(20)),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("sic", sa.String(10)),
        sa.Column("sic_description", sa.String(200)),
        sa.Column("state_of_inc", sa.String(5)),
        sa.Column("fiscal_year_end", sa.String(5)),
        sa.Column("ein", sa.String(20)),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_companies_ticker", "companies", ["ticker"])
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_companies_name_trgm ON companies USING gin(name gin_trgm_ops)"
    )

    # filings
    op.create_table(
        "filings",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("cik", sa.String(10), sa.ForeignKey("companies.cik"), nullable=False),
        sa.Column("accession_no", sa.String(25), nullable=False, unique=True),
        sa.Column("accession_no_raw", sa.String(20), nullable=False),
        sa.Column("form_type", sa.String(20), nullable=False),
        sa.Column("filing_date", sa.Date, nullable=False),
        sa.Column("period_of_report", sa.Date),
        sa.Column("primary_doc", sa.String(500)),
        sa.Column("doc_url", sa.String(1000)),
        sa.Column("index_url", sa.String(1000)),
        sa.Column("has_xbrl", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_filings_cik_form", "filings", ["cik", "form_type", "period_of_report"])

    # financial_statements
    op.create_table(
        "financial_statements",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("filing_id", sa.BigInteger, sa.ForeignKey("filings.id"), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("period_type", sa.String(10), nullable=False),
        sa.Column("statement_type", sa.String(30), nullable=False),
        sa.Column("currency", sa.String(5), default="USD"),
        sa.Column("unit_multiplier", sa.Integer, default=1),
        sa.Column("line_items", JSONB, nullable=False),
        sa.Column("concept_values", JSONB, nullable=False, server_default="{}"),
        sa.Column("parsed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("filing_id", "statement_type", name="uq_fs_filing_type"),
    )
    op.create_index(
        "ix_fs_cik_period", "financial_statements", ["cik", "period_end", "statement_type"]
    )

    # debt_instruments
    op.create_table(
        "debt_instruments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("cik", sa.String(10), sa.ForeignKey("companies.cik"), nullable=False),
        sa.Column("source_filing_id", sa.BigInteger, sa.ForeignKey("filings.id")),
        sa.Column("instrument_name", sa.String(500), nullable=False),
        sa.Column("instrument_type", sa.String(50)),
        sa.Column("seniority", sa.String(50)),
        sa.Column("principal_amount", sa.Numeric(20, 2)),
        sa.Column("currency", sa.String(5), default="USD"),
        sa.Column("coupon_rate", sa.Numeric(8, 5)),
        sa.Column("coupon_type", sa.String(10)),
        sa.Column("floating_benchmark", sa.String(20)),
        sa.Column("floating_spread", sa.Numeric(8, 5)),
        sa.Column("maturity_date", sa.Date),
        sa.Column("issuance_date", sa.Date),
        sa.Column("is_outstanding", sa.Boolean, default=True),
        sa.Column("is_current", sa.Boolean, default=True),
        sa.Column("confidence_score", sa.Numeric(3, 2), default=1.0),
        sa.Column("originating_filing_id", sa.BigInteger, sa.ForeignKey("filings.id")),
        sa.Column("originating_doc_url", sa.String(1000)),
        sa.Column("originating_doc_type", sa.String(30)),
        sa.Column("raw_data", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_debt_cik_outstanding", "debt_instruments", ["cik", "is_outstanding", "is_current"]
    )

    # forecast_sessions
    op.create_table(
        "forecast_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cik", sa.String(10), sa.ForeignKey("companies.cik"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("user.id")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("base_period_ends", JSONB, nullable=False),
        sa.Column("forecast_periods", JSONB, nullable=False),
        sa.Column("assumptions", JSONB, nullable=False, server_default="[]"),
        sa.Column("forecast_values", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_forecast_cik_updated", "forecast_sessions", ["cik", "updated_at"]
    )


def downgrade() -> None:
    op.drop_table("forecast_sessions")
    op.drop_table("debt_instruments")
    op.drop_table("financial_statements")
    op.drop_table("filings")
    op.drop_table("companies")
    op.drop_table("user")
