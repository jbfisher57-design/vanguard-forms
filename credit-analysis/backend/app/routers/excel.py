"""
Excel round-trip endpoints.
GET  /api/companies/{cik}/forecasts/{session_id}/excel  → download .xlsx
POST /api/companies/{cik}/forecasts/upload              → upload modified .xlsx
"""
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.database import get_async_session
from app.models.filing import Filing
from app.models.financial_statement import FinancialStatement
from app.models.forecast_session import ForecastSession
from app.models.user import User
from app.services.excel_builder import build_excel
from app.services.excel_parser import ExcelParseError, extract_overrides, parse_uploaded_excel
from app.services.forecast_engine import compute_forecasts

router = APIRouter(prefix="/api/companies", tags=["excel"])


@router.get("/{cik}/forecasts/{session_id}/excel")
async def download_excel(
    cik: str,
    session_id: UUID,
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    padded = cik.zfill(10)
    result = await db.execute(
        select(ForecastSession).where(
            ForecastSession.id == session_id,
            ForecastSession.cik == padded,
            ForecastSession.user_id == user.id,
        )
    )
    fs_session = result.scalar_one_or_none()
    if not fs_session:
        raise HTTPException(status_code=404, detail="Forecast session not found.")

    # Get the reference financial statement for line items / row ordering
    base_periods = fs_session.base_period_ends or []
    if not base_periods:
        raise HTTPException(status_code=422, detail="No base periods in session.")

    latest_period = sorted(base_periods)[-1]
    filing_result = await db.execute(
        select(Filing).where(
            Filing.cik == padded,
        ).order_by(Filing.period_of_report.desc()).limit(1)
    )
    filing = filing_result.scalar_one_or_none()
    if not filing:
        raise HTTPException(status_code=404, detail="No filings found.")

    stmt_result = await db.execute(
        select(FinancialStatement).where(
            FinancialStatement.filing_id == filing.id,
        )
    )
    fs = stmt_result.scalar_one_or_none()
    if not fs:
        raise HTTPException(status_code=404, detail="Financial statement not found.")

    # Build columns list
    hist_columns = [
        {"key": p, "label": _period_label(p), "period_end": p, "type": "historical"}
        for p in sorted(base_periods)
    ]
    forecast_periods = fs_session.forecast_periods or []
    fore_columns = [
        {"key": fp["label"], "label": fp["label"], "period_end": fp.get("period_end"), "type": "forecast"}
        for fp in forecast_periods
    ]
    all_columns = hist_columns + fore_columns

    # Build rows with forecast values attached
    forecast_values = fs_session.forecast_values or {}
    rows = []
    for item in (fs.line_items or []):
        forecast_col_vals = {}
        for fp in forecast_periods:
            label = fp["label"]
            concept_forecasts = forecast_values.get(item["concept"], {})
            forecast_col_vals[label] = concept_forecasts.get(label)

        rows.append({
            "row_id": item["concept"],
            "label": item["label"],
            "level": item.get("level", 1),
            "is_abstract": item.get("is_abstract", False),
            "semantic_type": item.get("semantic_type", "other"),
            "values": item.get("periods", {}),
            "forecast": {
                "computed": forecast_col_vals,
            },
        })

    forecast_labels = [fp["label"] for fp in forecast_periods]
    from app.models.company import Company
    company_result = await db.execute(select(Company).where(Company.cik == padded))
    company = company_result.scalar_one_or_none()
    company_name = company.name if company else padded

    xlsx_bytes = build_excel(
        company_name=company_name,
        cik=padded,
        statement_type=fs.statement_type,
        columns=all_columns,
        rows=rows,
        session_id=str(session_id),
        forecast_period_labels=forecast_labels,
    )

    safe_name = company_name.replace(" ", "_").replace("/", "-")[:40]
    filename = f"{safe_name}_forecast.xlsx"

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{cik}/forecasts/upload")
async def upload_excel(
    cik: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    padded = cik.zfill(10)
    content = await file.read()

    try:
        parsed = parse_uploaded_excel(content, expected_cik=padded)
    except ExcelParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    session_id = parsed.get("session_id")
    if not session_id:
        raise HTTPException(status_code=422, detail="No session ID in uploaded file.")

    result = await db.execute(
        select(ForecastSession).where(
            ForecastSession.id == session_id,
            ForecastSession.cik == padded,
            ForecastSession.user_id == user.id,
        )
    )
    fs_session = result.scalar_one_or_none()
    if not fs_session:
        raise HTTPException(
            status_code=404,
            detail="Forecast session not found or does not belong to your account.",
        )

    # Extract overrides: cells where user changed the value
    overrides = extract_overrides(
        parsed_rows=parsed["rows"],
        current_forecast_values=fs_session.forecast_values or {},
    )

    # Apply overrides to assumptions
    assumptions = list(fs_session.assumptions or [])
    for assumption in assumptions:
        concept = assumption["concept"]
        if concept in overrides:
            assumption.setdefault("overrides", {})
            assumption["overrides"].update(overrides[concept])

    # Add overrides for concepts not yet in assumptions
    existing_concepts = {a["concept"] for a in assumptions}
    for concept, override_vals in overrides.items():
        if concept not in existing_concepts:
            assumptions.append({
                "concept": concept,
                "method": "direct_input",
                "params": {},
                "overrides": override_vals,
            })

    fs_session.assumptions = assumptions

    # Re-fetch line items to recompute forecast
    filing_result = await db.execute(
        select(Filing).where(
            Filing.cik == padded,
        ).order_by(Filing.period_of_report.desc()).limit(1)
    )
    filing = filing_result.scalar_one_or_none()
    if filing:
        stmt_result = await db.execute(
            select(FinancialStatement).where(
                FinancialStatement.filing_id == filing.id,
            )
        )
        fs = stmt_result.scalar_one_or_none()
        if fs:
            fs_session.forecast_values = compute_forecasts(
                line_items=fs.line_items,
                assumptions=assumptions,
                forecast_periods=fs_session.forecast_periods,
                historical_period_keys=fs_session.base_period_ends,
            )

    await db.commit()
    await db.refresh(fs_session)

    return {
        "session_id": str(fs_session.id),
        "overrides_applied": sum(len(v) for v in overrides.values()),
        "message": "Forecast updated successfully.",
    }


def _period_label(period_key: str) -> str:
    try:
        from datetime import date
        d = date.fromisoformat(period_key)
        return f"FY{d.year}"
    except ValueError:
        return period_key
