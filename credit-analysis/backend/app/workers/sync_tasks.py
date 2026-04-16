"""
Background sync tasks.

sync_company_task(cik): Full sync for one company (submissions + XBRL).
nightly_sync_task():    Refresh recently-accessed companies.
"""
import asyncio
from datetime import date

from app.workers.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def sync_company_task(self, cik: str):
    """
    Fetch latest submissions from SEC and parse new filings for a company.
    Runs in a worker process; uses a new async event loop.
    """
    try:
        asyncio.run(_sync_company(cik))
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task
def nightly_sync_task():
    """Refresh companies accessed in the last 30 days."""
    asyncio.run(_nightly_sync())


async def _sync_company(cik: str):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select, text
    from app.config import settings
    from app.models.company import Company
    from app.models.filing import Filing
    from app.services import sec_client, cache

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    padded = cik.zfill(10)
    async with session_factory() as session:
        try:
            subs = await sec_client.get_submissions(padded)
        except Exception as e:
            print(f"[sync] Failed submissions for {padded}: {e}")
            return

        # Upsert company
        result = await session.execute(select(Company).where(Company.cik == padded))
        company = result.scalar_one_or_none()
        if not company:
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
        else:
            company.ticker = subs.get("tickers", [company.ticker])[0]
            company.name = subs.get("name", company.name)
            company.last_sync_at = date.today()

        recent = subs.get("filings", {}).get("recent", {})
        accessions = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        periods = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])
        has_xbrl_list = recent.get("isXBRL", [])

        new_filings = []
        for i, accession in enumerate(accessions):
            form = forms[i] if i < len(forms) else ""
            if form not in ("10-K", "10-Q", "8-K"):
                continue

            raw = accession.replace("-", "")
            existing = await session.execute(
                select(Filing).where(Filing.accession_no == accession)
            )
            if existing.scalar_one_or_none():
                continue

            filing_date_str = dates[i] if i < len(dates) else None
            period_str = periods[i] if i < len(periods) else None
            primary_doc = primary_docs[i] if i < len(primary_docs) else None
            has_xbrl = bool(has_xbrl_list[i]) if i < len(has_xbrl_list) else False

            doc_url = sec_client.build_doc_url(padded, raw, primary_doc) if primary_doc else None
            index_url = f"https://www.sec.gov/Archives/edgar/data/{padded}/{raw}/index.json"

            filing = Filing(
                cik=padded,
                accession_no=accession,
                accession_no_raw=raw,
                form_type=form,
                filing_date=date.fromisoformat(filing_date_str) if filing_date_str else date.today(),
                period_of_report=date.fromisoformat(period_str) if period_str else None,
                primary_doc=primary_doc,
                doc_url=doc_url,
                index_url=index_url,
                has_xbrl=has_xbrl,
            )
            session.add(filing)
            new_filings.append(filing)

        await session.commit()

        # Invalidate cache
        await cache.cache_delete(f"company:{padded}")
        await cache.cache_delete_pattern(f"financials:{padded}:*")

        print(f"[sync] Synced {padded}: {len(new_filings)} new filings")

    await engine.dispose()


async def _nightly_sync():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy import select, text
    from app.config import settings
    from app.models.company import Company

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Get companies synced in the last 30 days
        result = await session.execute(
            text(
                "SELECT cik FROM companies "
                "WHERE last_sync_at > NOW() - INTERVAL '30 days' "
                "ORDER BY last_sync_at DESC LIMIT 200"
            )
        )
        ciks = [row[0] for row in result.fetchall()]

    await engine.dispose()

    for cik in ciks:
        sync_company_task.delay(cik)

    print(f"[nightly_sync] Queued {len(ciks)} companies for refresh")
