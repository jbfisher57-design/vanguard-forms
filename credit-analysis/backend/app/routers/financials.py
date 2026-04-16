"""
Financial statements endpoint.
GET /api/companies/{cik}/financials
    ?statement=income_statement|balance_sheet|cash_flow
    &periods=5
    &form_type=10-K|10-Q
"""
import hashlib
import json
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.models.company import Company
from app.models.filing import Filing
from app.models.financial_statement import FinancialStatement
from app.services import cache, sec_client, xbrl_parser

router = APIRouter(prefix="/api/companies", tags=["financials"])

VALID_STATEMENTS = {"income_statement", "balance_sheet", "cash_flow"}
VALID_FORM_TYPES = {"10-K", "10-Q"}


class GridColumn(BaseModel):
    key: str
    label: str
    period_end: Optional[str]
    type: str  # "historical" | "forecast"


class GridRow(BaseModel):
    row_id: str
    label: str
    level: int
    is_abstract: bool
    semantic_type: str
    values: dict[str, Any]
    forecast: Optional[dict] = None


class FinancialGrid(BaseModel):
    cik: str
    company_name: str
    statement_type: str
    form_type: str
    unit: str
    columns: list[GridColumn]
    rows: list[GridRow]


@router.get("/{cik}/financials", response_model=FinancialGrid)
async def get_financials(
    cik: str,
    statement: str = Query("income_statement", enum=list(VALID_STATEMENTS)),
    periods: int = Query(5, ge=1, le=20),
    form_type: str = Query("10-K", enum=list(VALID_FORM_TYPES)),
    session: AsyncSession = Depends(get_async_session),
):
    padded = cik.zfill(10)
    cache_key = f"financials:{padded}:{statement}:{form_type}:{periods}"
    cached = await cache.cache_get(cache_key)
    if cached:
        return cached

    # Ensure company exists
    company_result = await session.execute(
        select(Company).where(Company.cik == padded)
    )
    company = company_result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found. Search for it first.")

    # Find the N most recent filings of this type
    filings_result = await session.execute(
        select(Filing)
        .where(
            Filing.cik == padded,
            Filing.form_type == form_type,
            Filing.period_of_report.is_not(None),
        )
        .order_by(Filing.period_of_report.desc())
        .limit(periods)
    )
    filings = filings_result.scalars().all()

    if not filings:
        # Trigger a sync for this company
        await _sync_company_filings(padded, session)
        filings_result = await session.execute(
            select(Filing)
            .where(
                Filing.cik == padded,
                Filing.form_type == form_type,
                Filing.period_of_report.is_not(None),
            )
            .order_by(Filing.period_of_report.desc())
            .limit(periods)
        )
        filings = filings_result.scalars().all()

    if not filings:
        raise HTTPException(status_code=404, detail=f"No {form_type} filings found.")

    # For each filing, ensure we have the parsed financial statement
    statements_by_period: dict[str, list[dict]] = {}
    for filing in filings:
        stmt_result = await session.execute(
            select(FinancialStatement).where(
                FinancialStatement.filing_id == filing.id,
                FinancialStatement.statement_type == statement,
            )
        )
        fs = stmt_result.scalar_one_or_none()

        if fs is None:
            # Parse XBRL for this filing
            try:
                parsed = await xbrl_parser.parse_filing_statements(
                    cik=padded,
                    accession_no=filing.accession_no,
                    accession_no_raw=filing.accession_no_raw,
                    form_type=filing.form_type,
                    period_end=str(filing.period_of_report),
                )
                for stmt_type, line_items in parsed.items():
                    concept_values = {
                        item["concept"]: item["periods"].get(str(filing.period_of_report))
                        for item in line_items
                        if not item["is_abstract"]
                    }
                    fs_obj = FinancialStatement(
                        filing_id=filing.id,
                        cik=padded,
                        period_end=filing.period_of_report,
                        period_type="annual" if form_type == "10-K" else "quarterly",
                        statement_type=stmt_type,
                        line_items=line_items,
                        concept_values=concept_values,
                        unit_multiplier=1,
                    )
                    session.add(fs_obj)
                await session.commit()

                # Re-fetch the one we need
                stmt_result2 = await session.execute(
                    select(FinancialStatement).where(
                        FinancialStatement.filing_id == filing.id,
                        FinancialStatement.statement_type == statement,
                    )
                )
                fs = stmt_result2.scalar_one_or_none()
            except Exception as e:
                print(f"[financials] Parse error for filing {filing.id}: {e}")

        if fs:
            period_key = _period_key(filing.period_of_report, form_type)
            statements_by_period[period_key] = fs.line_items

    if not statements_by_period:
        raise HTTPException(
            status_code=422,
            detail="Could not parse financial statements for this company.",
        )

    # Build the grid
    # Use the most recent filing's line items as the row template
    sorted_periods = sorted(
        statements_by_period.keys(),
        key=lambda k: k,
    )
    reference_items = statements_by_period[sorted_periods[-1]]

    columns = [
        GridColumn(
            key=pk,
            label=_period_label(pk, form_type),
            period_end=pk,
            type="historical",
        )
        for pk in sorted_periods
    ]

    rows = []
    for item in reference_items:
        values: dict[str, Any] = {}
        for pk in sorted_periods:
            period_items = statements_by_period.get(pk, [])
            match = next(
                (x for x in period_items if x["concept"] == item["concept"]), None
            )
            if match:
                period_val = _get_period_value(match, pk)
                if period_val is not None:
                    values[pk] = period_val
            # Also check the current item's own periods dict
            if pk not in values:
                own_val = _get_period_value(item, pk)
                if own_val is not None:
                    values[pk] = own_val

        rows.append(
            GridRow(
                row_id=item["concept"],
                label=item["label"],
                level=item.get("level", 1),
                is_abstract=item.get("is_abstract", False),
                semantic_type=item.get("semantic_type", "other"),
                values=values,
            )
        )

    grid = FinancialGrid(
        cik=padded,
        company_name=company.name,
        statement_type=statement,
        form_type=form_type,
        unit="USD",
        columns=columns,
        rows=rows,
    )

    result = grid.model_dump()
    await cache.cache_set(cache_key, result, settings.cache_ttl_financials)
    return result


def _period_key(period_end: date, form_type: str) -> str:
    return str(period_end)


def _period_label(period_key: str, form_type: str) -> str:
    """Convert a period key like '2024-09-28' to 'FY2024' or 'Q3 2024'."""
    try:
        d = date.fromisoformat(period_key)
        if form_type == "10-K":
            return f"FY{d.year}"
        else:
            month = d.month
            q = (month - 1) // 3 + 1
            return f"Q{q} {d.year}"
    except ValueError:
        return period_key


def _get_period_value(item: dict, period_key: str) -> Optional[float]:
    """Find a value in the periods dict for a given period key."""
    periods = item.get("periods", {})
    if period_key in periods:
        return periods[period_key]
    # Try prefix match (e.g. "2024-09-28" matches "2024")
    for k, v in periods.items():
        if k.startswith(period_key[:7]):  # YYYY-MM prefix
            return v
    return None


async def _sync_company_filings(cik: str, session: AsyncSession) -> None:
    """Fetch submissions from SEC and upsert filings into DB."""
    try:
        subs = await sec_client.get_submissions(cik)
    except Exception as e:
        print(f"[financials] Failed to fetch submissions for {cik}: {e}")
        return

    recent = subs.get("filings", {}).get("recent", {})
    if not recent:
        return

    accessions = recent.get("accessionNumber", [])
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    periods = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])
    has_xbrl_list = recent.get("isXBRL", [])

    for i, accession in enumerate(accessions):
        form = forms[i] if i < len(forms) else ""
        if form not in ("10-K", "10-Q", "8-K"):
            continue

        raw = accession.replace("-", "")
        filing_date = dates[i] if i < len(dates) else None
        period = periods[i] if i < len(periods) else None
        primary_doc = primary_docs[i] if i < len(primary_docs) else None
        has_xbrl = bool(has_xbrl_list[i]) if i < len(has_xbrl_list) else False

        # Check if already exists
        existing = await session.execute(
            select(Filing).where(Filing.accession_no == accession)
        )
        if existing.scalar_one_or_none():
            continue

        doc_url = None
        index_url = None
        if primary_doc:
            doc_url = sec_client.build_doc_url(cik, raw, primary_doc)
            index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{raw}/index.json"

        filing = Filing(
            cik=cik,
            accession_no=accession,
            accession_no_raw=raw,
            form_type=form,
            filing_date=date.fromisoformat(filing_date) if filing_date else date.today(),
            period_of_report=date.fromisoformat(period) if period else None,
            primary_doc=primary_doc,
            doc_url=doc_url,
            index_url=index_url,
            has_xbrl=has_xbrl,
        )
        session.add(filing)

    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        print(f"[financials] DB error syncing filings for {cik}: {e}")
