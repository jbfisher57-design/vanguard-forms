from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    ticker: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    sic: Mapped[Optional[str]] = mapped_column(String(10))
    sic_description: Mapped[Optional[str]] = mapped_column(String(200))
    state_of_inc: Mapped[Optional[str]] = mapped_column(String(5))
    fiscal_year_end: Mapped[Optional[str]] = mapped_column(String(5))  # MM-DD
    ein: Mapped[Optional[str]] = mapped_column(String(20))
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    filings: Mapped[list["Filing"]] = relationship(back_populates="company")
    debt_instruments: Mapped[list["DebtInstrument"]] = relationship(back_populates="company")
    forecast_sessions: Mapped[list["ForecastSession"]] = relationship(back_populates="company")
