from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FinancialStatement(Base):
    __tablename__ = "financial_statements"
    __table_args__ = (UniqueConstraint("filing_id", "statement_type"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id"), nullable=False)
    cik: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # annual | quarterly
    statement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # income_statement | balance_sheet | cash_flow
    currency: Mapped[str] = mapped_column(String(5), default="USD")
    unit_multiplier: Mapped[int] = mapped_column(Integer, default=1)
    # Ordered line items from presentation linkbase
    # [{concept, label, level, is_abstract, semantic_type, periods: {date: value}}]
    line_items: Mapped[Any] = mapped_column(JSONB, nullable=False)
    # Flat concept -> value map for the period_end date (fast lookup)
    concept_values: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict)
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    filing: Mapped["Filing"] = relationship(back_populates="financial_statements")
