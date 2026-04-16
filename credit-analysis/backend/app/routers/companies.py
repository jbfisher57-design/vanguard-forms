"""
Company search and metadata endpoints.
GET /api/companies/search?q=apple&limit=20
GET /api/companies/{cik}
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.models.company import Company
from app.models.filing import Filing
from app.services import cache, sec_client

router = APIRouter(prefix="/api/companies", tags=["companies"])


class CompanySearchResult(BaseModel):
    cik: str
    ticker: Optional[str]
    name: str
    sic: Optional[str]
    fiscal_year_end: Optional[str]


class AvailablePeriod(BaseModel):
    period_end: str
    form_type: str
    filing_id: int


class CompanyDetail(BaseModel):
    cik: str
    ticker: Optional[str]
    name: str
    sic: Optional[str]
    sic_description: Optional[str]
    state_of_inc: Optional[str]
    fiscal_year_end: Optional[str]
    available_periods: list[AvailablePeriod]


async def _ensure_ticker_map(session: AsyncSession) -> dict:
    """Load the SEC company tickers map from cache or API, seed DB if needed."""
    cached = await cache.cache_get("sec:tickers_map")
    if cached:
        return cached

    raw = await sec_client.get_company_tickers()
    # raw is {0: {cik_str, ticker, title}, 1: ...}
    tickers_map: dict[str, dict] = {}
    for entry in raw.values():
        cik = str(entry.get("cik_str", "")).zfill(10)
        tickers_map[cik] = {
            "ticker": entry.get("ticker", ""),
            "name": entry.get("title", ""),
        }

    await cache.cache_set("sec:tickers_map", tickers_map, settings.cache_ttl_company_facts)
    return tickers_map


@router.get("/search", response_model=list[CompanySearchResult])
async def search_companies(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, le=50),
    session: AsyncSession = Depends(get_async_session),
):
    q_lower = q.strip().lower()
    cache_key = f"search:{q_lower}:{limit}"
    cached = await cache.cache_get(cache_key)
    if cached:
        return cached

    # Search in local DB first (trigram index on name, exact on ticker)
    stmt = (
        select(Company)
        .where(
            (Company.name.ilike(f"%{q}%")) | (Company.ticker.ilike(f"%{q}%"))
        )
        .limit(limit)
    )
    result = await session.execute(stmt)
    companies = result.scalars().all()

    if companies:
        out = [
            CompanySearchResult(
                cik=c.cik,
                ticker=c.ticker,
                name=c.name,
                sic=c.sic,
                fiscal_year_end=c.fiscal_year_end,
            ).model_dump()
            for c in companies
        ]
        await cache.cache_set(cache_key, out, settings.cache_ttl_search)
        return out

    # Fallback: search the SEC tickers map
    tickers_map = await _ensure_ticker_map(session)
    matches = []
    for cik, info in tickers_map.items():
        name_lower = info["name"].lower()
        ticker_lower = info["ticker"].lower()
        if q_lower in name_lower or q_lower in ticker_lower:
            matches.append(
                CompanySearchResult(
                    cik=cik,
                    ticker=info["ticker"] or None,
                    name=info["name"],
                    sic=None,
                    fiscal_year_end=None,
                )
            )
        if len(matches) >= limit:
            break

    out = [m.model_dump() for m in matches]
    await cache.cache_set(cache_key, out, settings.cache_ttl_search)
    return out


@router.get("/{cik}", response_model=CompanyDetail)
async def get_company(
    cik: str,
    session: AsyncSession = Depends(get_async_session),
):
    padded = cik.zfill(10)
    cache_key = f"company:{padded}"
    cached = await cache.cache_get(cache_key)
    if cached:
        return cached

    # Try DB first
    result = await session.execute(select(Company).where(Company.cik == padded))
    company = result.scalar_one_or_none()

    if not company:
        # Fetch from SEC and upsert
        try:
            subs = await sec_client.get_submissions(padded)
        except Exception:
            raise HTTPException(status_code=404, detail="Company not found in SEC EDGAR")

        company = Company(
            cik=padded,
            ticker=subs.get("tickers", [None])[0],
            name=subs.get("name", ""),
            sic=subs.get("sic"),
            sic_description=subs.get("sicDescription"),
            state_of_inc=subs.get("stateOfIncorporation"),
            fiscal_year_end=subs.get("fiscalYearEnd"),
            ein=subs.get("ein"),
        )
        session.add(company)
        await session.commit()
        await session.refresh(company)

    # Get available filing periods
    periods_result = await session.execute(
        select(Filing)
        .where(
            Filing.cik == padded,
            Filing.form_type.in_(["10-K", "10-Q"]),
            Filing.period_of_report.is_not(None),
        )
        .order_by(Filing.period_of_report.desc())
        .limit(40)
    )
    filings = periods_result.scalars().all()

    detail = CompanyDetail(
        cik=company.cik,
        ticker=company.ticker,
        name=company.name,
        sic=company.sic,
        sic_description=company.sic_description,
        state_of_inc=company.state_of_inc,
        fiscal_year_end=company.fiscal_year_end,
        available_periods=[
            AvailablePeriod(
                period_end=str(f.period_of_report),
                form_type=f.form_type,
                filing_id=f.id,
            )
            for f in filings
        ],
    ).model_dump()

    await cache.cache_set(cache_key, detail, settings.cache_ttl_submissions)
    return detail
