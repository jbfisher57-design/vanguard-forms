from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Date

from app.database import Base


class ForecastSession(Base):
    __tablename__ = "forecast_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    cik: Mapped[str] = mapped_column(String(10), ForeignKey("companies.cik"), nullable=False)
    user_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("user.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Historical anchor period end dates
    base_period_ends: Mapped[Any] = mapped_column(JSONB, nullable=False)  # list of ISO date strings
    # Forecast period definitions: [{label: "2025E", period_end: "2025-12-31"}]
    forecast_periods: Mapped[Any] = mapped_column(JSONB, nullable=False)
    # Per-row assumptions: [{concept, method, params, overrides}]
    assumptions: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    # Computed forecast output: {concept: {period_label: value}}
    forecast_values: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="forecast_sessions")
