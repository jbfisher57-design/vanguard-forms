from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DebtInstrument(Base):
    __tablename__ = "debt_instruments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), ForeignKey("companies.cik"), nullable=False)
    source_filing_id: Mapped[Optional[int]] = mapped_column(ForeignKey("filings.id"))
    instrument_name: Mapped[str] = mapped_column(String(500), nullable=False)
    instrument_type: Mapped[Optional[str]] = mapped_column(String(50))
    # senior_notes | term_loan | revolver | sub_notes | convertible | other
    seniority: Mapped[Optional[str]] = mapped_column(String(50))
    # senior_secured | senior_unsecured | subordinated | pik
    principal_amount: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(5), default="USD")
    coupon_rate: Mapped[Optional[float]] = mapped_column(Numeric(8, 5))
    coupon_type: Mapped[Optional[str]] = mapped_column(String(10))  # fixed | floating | pik
    floating_benchmark: Mapped[Optional[str]] = mapped_column(String(20))  # SOFR | LIBOR
    floating_spread: Mapped[Optional[float]] = mapped_column(Numeric(8, 5))
    maturity_date: Mapped[Optional[date]] = mapped_column(Date)
    issuance_date: Mapped[Optional[date]] = mapped_column(Date)
    is_outstanding: Mapped[bool] = mapped_column(Boolean, default=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence_score: Mapped[float] = mapped_column(Numeric(3, 2), default=1.0)
    # Link to originating filing (prospectus / indenture / 8-K)
    originating_filing_id: Mapped[Optional[int]] = mapped_column(ForeignKey("filings.id"))
    originating_doc_url: Mapped[Optional[str]] = mapped_column(String(1000))
    originating_doc_type: Mapped[Optional[str]] = mapped_column(String(30))
    # prospectus | indenture | 8-K | 10-K_note | S-3
    raw_data: Mapped[Optional[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="debt_instruments")
    source_filing: Mapped[Optional["Filing"]] = relationship(
        back_populates="debt_instruments_source",
        foreign_keys=[source_filing_id],
    )
    originating_filing: Mapped[Optional["Filing"]] = relationship(
        back_populates="debt_instruments_originating",
        foreign_keys=[originating_filing_id],
    )
