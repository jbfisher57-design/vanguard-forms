from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (UniqueConstraint("accession_no"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), ForeignKey("companies.cik"), nullable=False)
    accession_no: Mapped[str] = mapped_column(String(25), nullable=False)
    accession_no_raw: Mapped[str] = mapped_column(String(20), nullable=False)
    form_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_of_report: Mapped[Optional[date]] = mapped_column(Date, index=True)
    primary_doc: Mapped[Optional[str]] = mapped_column(String(500))
    doc_url: Mapped[Optional[str]] = mapped_column(String(1000))
    index_url: Mapped[Optional[str]] = mapped_column(String(1000))
    has_xbrl: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="filings")
    financial_statements: Mapped[list["FinancialStatement"]] = relationship(
        back_populates="filing"
    )
    debt_instruments_source: Mapped[list["DebtInstrument"]] = relationship(
        back_populates="source_filing",
        foreign_keys="DebtInstrument.source_filing_id",
    )
    debt_instruments_originating: Mapped[list["DebtInstrument"]] = relationship(
        back_populates="originating_filing",
        foreign_keys="DebtInstrument.originating_filing_id",
    )
