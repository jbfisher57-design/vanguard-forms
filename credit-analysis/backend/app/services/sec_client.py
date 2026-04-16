"""
Rate-limited SEC EDGAR HTTP client.
Enforces 8 req/s with a token bucket and exponential backoff on 429/503.
"""
import asyncio
import time
from typing import Any, Optional

import httpx

from app.config import settings

SEC_BASE = "https://data.sec.gov"
SEC_WWW = "https://www.sec.gov"
EFTS_BASE = "https://efts.sec.gov"


class _TokenBucket:
    def __init__(self, rate: float):
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._rate, self._tokens + elapsed * self._rate)
            self._last = now
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1


_bucket = _TokenBucket(settings.sec_requests_per_second)

_HEADERS = {
    "User-Agent": settings.sec_user_agent,
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json",
}


async def _get(url: str, params: Optional[dict] = None, retries: int = 4) -> Any:
    await _bucket.acquire()
    backoff = 2
    last_exc: Optional[Exception] = None
    async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
        for attempt in range(retries + 1):
            try:
                resp = await client.get(url, params=params)
                if resp.status_code in (429, 503):
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2
    raise last_exc or RuntimeError(f"Failed to GET {url}")


async def _get_bytes(url: str, retries: int = 4) -> bytes:
    await _bucket.acquire()
    backoff = 2
    last_exc: Optional[Exception] = None
    async with httpx.AsyncClient(
        headers={**_HEADERS, "Accept": "*/*"}, timeout=60
    ) as client:
        for attempt in range(retries + 1):
            try:
                resp = await client.get(url)
                if resp.status_code in (429, 503):
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                resp.raise_for_status()
                return resp.content
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2
    raise last_exc or RuntimeError(f"Failed to GET bytes {url}")


def _pad_cik(cik: str) -> str:
    return cik.zfill(10)


async def get_company_tickers() -> dict:
    """Fetch the bulk ticker→CIK mapping (~10 MB JSON)."""
    return await _get(f"{SEC_WWW}/files/company_tickers.json")


async def get_submissions(cik: str) -> dict:
    """Fetch all submissions for a company."""
    padded = _pad_cik(cik)
    return await _get(f"{SEC_BASE}/submissions/CIK{padded}.json")


async def get_company_facts(cik: str) -> dict:
    """Fetch all XBRL facts for a company."""
    padded = _pad_cik(cik)
    return await _get(f"{SEC_BASE}/api/xbrl/companyfacts/CIK{padded}.json")


async def get_filing_index(cik: str, accession_no_raw: str) -> dict:
    """Fetch the index JSON for a specific filing."""
    url = f"{SEC_WWW}/Archives/edgar/data/{cik}/{accession_no_raw}/index.json"
    return await _get(url)


async def get_filing_document(url: str) -> bytes:
    """Fetch the raw bytes of a filing document (HTML, XML, etc.)."""
    return await _get_bytes(url)


async def search_fulltext(
    query: str,
    cik: Optional[str] = None,
    forms: str = "8-K,S-3,424B5",
    start_dt: Optional[str] = None,
    end_dt: Optional[str] = None,
    hits_per_page: int = 10,
) -> dict:
    """Full-text search across EDGAR filings."""
    params: dict = {
        "q": f'"{query}"',
        "forms": forms,
        "hits.hits.total.value": hits_per_page,
    }
    if cik:
        params["entity"] = cik
    if start_dt:
        params["dateRange"] = "custom"
        params["startdt"] = start_dt
    if end_dt:
        params["enddt"] = end_dt
    return await _get(f"{EFTS_BASE}/LATEST/search-index", params=params)


def build_doc_url(cik: str, accession_no_raw: str, filename: str) -> str:
    """Construct the permanent SEC EDGAR document URL."""
    return f"{SEC_WWW}/Archives/edgar/data/{cik}/{accession_no_raw}/{filename}"
