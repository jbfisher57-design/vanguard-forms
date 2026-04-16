"""
Debt schedule endpoint.
GET /api/companies/{cik}/debt
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.models.debt_instrument import DebtInstrument
from app.models.filing import Filing
from app.services import cache
from app.services.debt_extractor import extract_debt_instruments

router = APIRouter(prefix="/api/companies", tags=["debt"])


class DebtInstrumentResponse(BaseModel):
    id: int
    instrument_name: str
    instrument_type: Optional[str]
    seniority: Optional[str]
    principal_amount: Optional[float]
    currency: str
    coupon_rate: Optional[float]
    coupon_type: Optional[str]
    floating_benchmark: Optional[str]
    floating_spread: Optional[float]
    maturity_date: Optional[str]
    issuance_date: Optional[str]
    is_outstanding: bool
    confidence_score: float
    originating_doc_url: Optional[str]
    originating_doc_type: Optional[str]


@router.get("/{cik}/debt", response_model=list[DebtInstrumentResponse])
async def get_debt_schedule(
    cik: str,
    session: AsyncSession = Depends(get_async_session),
):
    padded = cik.zfill(10)
    cache_key = f"debt:{padded}"
    cached = await cache.cache_get(cache_key)
    if cached:
        return cached

    # Try DB first
    db_result = await session.execute(
        select(DebtInstrument).where(
            DebtInstrument.cik == padded,
            DebtInstrument.is_current == True,
            DebtInstrument.is_outstanding == True,
        ).order_by(DebtInstrument.seniority, DebtInstrument.maturity_date)
    )
    existing = db_result.scalars().all()

    if not existing:
        # Trigger extraction from the most recent 10-K
        filing_result = await session.execute(
            select(Filing).where(
                Filing.cik == padded,
                Filing.form_type == "10-K",
            ).order_by(Filing.period_of_report.desc()).limit(1)
        )
        filing = filing_result.scalar_one_or_none()

        if not filing:
            raise HTTPException(
                status_code=404,
                detail="No 10-K filing found. Please load financials first.",
            )

        instruments = await extract_debt_instruments(
            cik=padded,
            accession_no=filing.accession_no,
            accession_no_raw=filing.accession_no_raw,
            doc_url=filing.doc_url,
        )

        for inst_data in instruments:
            db_inst = DebtInstrument(
                cik=padded,
                source_filing_id=filing.id,
                instrument_name=inst_data["instrument_name"],
                instrument_type=inst_data.get("instrument_type"),
                seniority=inst_data.get("seniority"),
                principal_amount=inst_data.get("principal_amount"),
                currency=inst_data.get("currency", "USD"),
                coupon_rate=inst_data.get("coupon_rate"),
                coupon_type=inst_data.get("coupon_type"),
                floating_benchmark=inst_data.get("floating_benchmark"),
                floating_spread=inst_data.get("floating_spread"),
                maturity_date=inst_data.get("maturity_date"),
                issuance_date=inst_data.get("issuance_date"),
                confidence_score=inst_data.get("confidence_score", 0.8),
                originating_doc_url=inst_data.get("originating_doc_url"),
                originating_doc_type=inst_data.get("originating_doc_type"),
                raw_data=inst_data.get("raw_data"),
            )
            session.add(db_inst)

        await session.commit()

        db_result2 = await session.execute(
            select(DebtInstrument).where(
                DebtInstrument.cik == padded,
                DebtInstrument.is_current == True,
                DebtInstrument.is_outstanding == True,
            ).order_by(DebtInstrument.seniority, DebtInstrument.maturity_date)
        )
        existing = db_result2.scalars().all()

    out = [_to_response(inst) for inst in existing]
    await cache.cache_set(cache_key, [r.model_dump() for r in out], settings.cache_ttl_debt)
    return out


def _to_response(inst: DebtInstrument) -> DebtInstrumentResponse:
    return DebtInstrumentResponse(
        id=inst.id,
        instrument_name=inst.instrument_name,
        instrument_type=inst.instrument_type,
        seniority=inst.seniority,
        principal_amount=float(inst.principal_amount) if inst.principal_amount else None,
        currency=inst.currency or "USD",
        coupon_rate=float(inst.coupon_rate) if inst.coupon_rate else None,
        coupon_type=inst.coupon_type,
        floating_benchmark=inst.floating_benchmark,
        floating_spread=float(inst.floating_spread) if inst.floating_spread else None,
        maturity_date=str(inst.maturity_date) if inst.maturity_date else None,
        issuance_date=str(inst.issuance_date) if inst.issuance_date else None,
        is_outstanding=inst.is_outstanding,
        confidence_score=float(inst.confidence_score) if inst.confidence_score else 0.8,
        originating_doc_url=inst.originating_doc_url,
        originating_doc_type=inst.originating_doc_type,
    )
