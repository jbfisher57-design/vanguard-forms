"""
Forecast session CRUD.
POST /api/companies/{cik}/forecasts
GET  /api/companies/{cik}/forecasts
GET  /api/companies/{cik}/forecasts/{session_id}
PUT  /api/companies/{cik}/forecasts/{session_id}
DELETE /api/companies/{cik}/forecasts/{session_id}
"""
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.database import get_async_session
from app.models.financial_statement import FinancialStatement
from app.models.forecast_session import ForecastSession
from app.models.user import User
from app.services.forecast_engine import build_default_assumptions, compute_forecasts

router = APIRouter(prefix="/api/companies", tags=["forecasts"])


class ForecastPeriod(BaseModel):
    label: str       # e.g. "2025E"
    period_end: str  # ISO date


class AssumptionRow(BaseModel):
    concept: str
    method: str
    params: dict[str, Any] = {}
    overrides: dict[str, Any] = {}


class CreateForecastRequest(BaseModel):
    name: str
    statement_type: str = "income_statement"
    base_filing_id: int          # The filing to base forecasts on
    base_period_ends: list[str]  # All historical period keys to include
    forecast_periods: list[ForecastPeriod]
    assumptions: Optional[list[AssumptionRow]] = None


class UpdateForecastRequest(BaseModel):
    name: Optional[str] = None
    assumptions: Optional[list[AssumptionRow]] = None
    forecast_periods: Optional[list[ForecastPeriod]] = None


class ForecastSessionResponse(BaseModel):
    id: str
    cik: str
    name: str
    statement_type: str = "income_statement"
    base_period_ends: list[str]
    forecast_periods: list[ForecastPeriod]
    assumptions: list[AssumptionRow]
    forecast_values: dict[str, dict[str, Any]]
    created_at: str
    updated_at: str


@router.post("/{cik}/forecasts", response_model=ForecastSessionResponse)
async def create_forecast(
    cik: str,
    body: CreateForecastRequest,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    padded = cik.zfill(10)

    # Fetch the reference financial statement
    fs_result = await session.execute(
        select(FinancialStatement).where(
            FinancialStatement.filing_id == body.base_filing_id,
            FinancialStatement.statement_type == body.statement_type,
        )
    )
    fs = fs_result.scalar_one_or_none()
    if not fs:
        raise HTTPException(status_code=404, detail="Financial statement not found.")

    line_items = fs.line_items
    num_periods = len(body.forecast_periods)

    # Use provided assumptions or generate defaults
    if body.assumptions:
        assumptions = [a.model_dump() for a in body.assumptions]
    else:
        assumptions = build_default_assumptions(line_items, num_periods)

    # Compute forecast values
    forecast_values = compute_forecasts(
        line_items=line_items,
        assumptions=assumptions,
        forecast_periods=[p.model_dump() for p in body.forecast_periods],
        historical_period_keys=body.base_period_ends,
    )

    fs_session = ForecastSession(
        cik=padded,
        user_id=user.id,
        name=body.name,
        base_period_ends=body.base_period_ends,
        forecast_periods=[p.model_dump() for p in body.forecast_periods],
        assumptions=assumptions,
        forecast_values=forecast_values,
    )
    session.add(fs_session)
    await session.commit()
    await session.refresh(fs_session)

    return _to_response(fs_session)


@router.get("/{cik}/forecasts", response_model=list[ForecastSessionResponse])
async def list_forecasts(
    cik: str,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    padded = cik.zfill(10)
    result = await session.execute(
        select(ForecastSession).where(
            ForecastSession.cik == padded,
            ForecastSession.user_id == user.id,
        ).order_by(ForecastSession.updated_at.desc())
    )
    sessions = result.scalars().all()
    return [_to_response(s) for s in sessions]


@router.get("/{cik}/forecasts/{session_id}", response_model=ForecastSessionResponse)
async def get_forecast(
    cik: str,
    session_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    padded = cik.zfill(10)
    result = await session.execute(
        select(ForecastSession).where(
            ForecastSession.id == session_id,
            ForecastSession.cik == padded,
            ForecastSession.user_id == user.id,
        )
    )
    fs_session = result.scalar_one_or_none()
    if not fs_session:
        raise HTTPException(status_code=404, detail="Forecast session not found.")
    return _to_response(fs_session)


@router.put("/{cik}/forecasts/{session_id}", response_model=ForecastSessionResponse)
async def update_forecast(
    cik: str,
    session_id: UUID,
    body: UpdateForecastRequest,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    padded = cik.zfill(10)
    result = await session.execute(
        select(ForecastSession).where(
            ForecastSession.id == session_id,
            ForecastSession.cik == padded,
            ForecastSession.user_id == user.id,
        )
    )
    fs_session = result.scalar_one_or_none()
    if not fs_session:
        raise HTTPException(status_code=404, detail="Forecast session not found.")

    if body.name is not None:
        fs_session.name = body.name
    if body.assumptions is not None:
        fs_session.assumptions = [a.model_dump() for a in body.assumptions]
    if body.forecast_periods is not None:
        fs_session.forecast_periods = [p.model_dump() for p in body.forecast_periods]

    # Re-fetch line items to recompute
    # We need the base filing's financial statement
    # Use the most recent period in base_period_ends
    base_periods = fs_session.base_period_ends
    if base_periods:
        from app.models.filing import Filing
        latest_period = sorted(base_periods)[-1]
        filing_result = await session.execute(
            select(Filing).where(
                Filing.cik == padded,
                Filing.period_of_report.cast(str) == latest_period,
            ).limit(1)
        )
        filing = filing_result.scalar_one_or_none()
        if filing:
            from app.models.financial_statement import FinancialStatement
            stmt_result = await session.execute(
                select(FinancialStatement).where(
                    FinancialStatement.filing_id == filing.id,
                )
            )
            fs = stmt_result.scalar_one_or_none()
            if fs:
                fs_session.forecast_values = compute_forecasts(
                    line_items=fs.line_items,
                    assumptions=fs_session.assumptions,
                    forecast_periods=fs_session.forecast_periods,
                    historical_period_keys=base_periods,
                )

    await session.commit()
    await session.refresh(fs_session)
    return _to_response(fs_session)


@router.delete("/{cik}/forecasts/{session_id}", status_code=204)
async def delete_forecast(
    cik: str,
    session_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    padded = cik.zfill(10)
    result = await session.execute(
        select(ForecastSession).where(
            ForecastSession.id == session_id,
            ForecastSession.cik == padded,
            ForecastSession.user_id == user.id,
        )
    )
    fs_session = result.scalar_one_or_none()
    if not fs_session:
        raise HTTPException(status_code=404, detail="Forecast session not found.")
    await session.delete(fs_session)
    await session.commit()


def _to_response(fs: ForecastSession) -> ForecastSessionResponse:
    return ForecastSessionResponse(
        id=str(fs.id),
        cik=fs.cik,
        name=fs.name,
        base_period_ends=fs.base_period_ends or [],
        forecast_periods=[ForecastPeriod(**p) for p in (fs.forecast_periods or [])],
        assumptions=[AssumptionRow(**a) for a in (fs.assumptions or [])],
        forecast_values=fs.forecast_values or {},
        created_at=str(fs.created_at),
        updated_at=str(fs.updated_at),
    )
