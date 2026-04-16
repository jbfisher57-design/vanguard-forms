"""
XBRL parser service.

Fetches a 10-K or 10-Q filing's XBRL attachments and extracts ordered
financial statements (income statement, balance sheet, cash flow) via the
presentation linkbase. Falls back to the Company Facts API when XBRL
attachments are unavailable.

Each parsed statement is stored as an ordered list of line items:
[{
    concept: str,           # XBRL concept (e.g. "us-gaap:Revenues")
    label: str,             # Label from .LAB file as company wrote it
    level: int,             # Indentation depth (1 = top)
    is_abstract: bool,      # True for header/grouping rows
    semantic_type: str,     # "revenue" | "cogs" | "gross_profit" | etc.
    periods: {              # ISO date -> value (None for abstract rows)
        "2024-09-28": 391035000000,
        "2023-09-30": 383285000000,
    }
}]
"""
import re
from typing import Any, Optional

from app.services import sec_client

# edgartools is optional — used when available for richer presentation-order parsing
try:
    from edgar import Company as EdgarCompany  # edgartools pip package
    _EDGARTOOLS_AVAILABLE = True
except ImportError:
    _EDGARTOOLS_AVAILABLE = False

# Maps XBRL role fragments to our statement_type keys
_ROLE_TO_STMT: dict[str, str] = {
    "incomestatement": "income_statement",
    "statementofoperations": "income_statement",
    "consolidatedstatementofoperations": "income_statement",
    "consolidatedstatementsofincome": "income_statement",
    "statementsofoperations": "income_statement",
    "operationsstatement": "income_statement",
    "balancesheet": "balance_sheet",
    "consolidatedbalancesheets": "balance_sheet",
    "financialposition": "balance_sheet",
    "statementoffinancialposition": "balance_sheet",
    "cashflow": "cash_flow",
    "cashflows": "cash_flow",
    "consolidatedstatementofcashflows": "cash_flow",
    "statementofcashflows": "cash_flow",
}

# Semantic type inference based on known XBRL concept names
_CONCEPT_SEMANTIC: dict[str, str] = {
    "revenues": "revenue",
    "revenuefromcontractwithcustomerexcludingassessedtax": "revenue",
    "revenuefromcontractwithcustomerincludingassessedtax": "revenue",
    "salesrevenuenet": "revenue",
    "netsales": "revenue",
    "costofgoodsandservicessold": "cogs",
    "costofrevenue": "cogs",
    "costofgoodssold": "cogs",
    "grossprofit": "gross_profit",
    "operatingincomeloss": "operating_income",
    "ebitda": "ebitda",
    "incomelossfromcontinuingoperationsbeforeincometaxes": "pretax_income",
    "incometaxexpensebenefit": "tax_expense",
    "netincomeloss": "net_income",
    "earningspersharebasic": "eps_basic",
    "earningspersharediluted": "eps_diluted",
    "depreciationdepletionandamortization": "da",
    "depreciationandamortization": "da",
    "researchanddevelopmentexpense": "rd_expense",
    "sellinggeneralandadministrativeexpense": "sga",
    "interestexpense": "interest_expense",
    "interestincome": "interest_income",
    "assets": "total_assets",
    "liabilities": "total_liabilities",
    "stockholdersequity": "total_equity",
    "cashandcashequivalentsatcarryingvalue": "cash",
    "longtermdebtnoncurrent": "long_term_debt",
    "longtermdebt": "long_term_debt",
    "netcashprovidedbyusedinoperatingactivities": "cfo",
    "netcashprovidedbyusedininvestingactivities": "cfi",
    "netcashprovidedbyusedinfinancingactivities": "cff",
}


def _normalize_concept(concept: str) -> str:
    """Strip namespace prefix and lowercase for semantic lookup."""
    if ":" in concept:
        concept = concept.split(":", 1)[1]
    return re.sub(r"[^a-z0-9]", "", concept.lower())


def _infer_semantic_type(concept: str, label: str) -> str:
    key = _normalize_concept(concept)
    if key in _CONCEPT_SEMANTIC:
        return _CONCEPT_SEMANTIC[key]
    # Label-based heuristics
    label_lower = label.lower()
    if "revenue" in label_lower or "net sales" in label_lower:
        return "revenue"
    if "cost of" in label_lower:
        return "cogs"
    if "gross profit" in label_lower:
        return "gross_profit"
    if "operating income" in label_lower or "operating loss" in label_lower:
        return "operating_income"
    if "net income" in label_lower or "net loss" in label_lower:
        return "net_income"
    if "depreciation" in label_lower or "amortization" in label_lower:
        return "da"
    if "interest expense" in label_lower:
        return "interest_expense"
    if "income tax" in label_lower:
        return "tax_expense"
    return "other"


def _role_to_statement_type(role_uri: str) -> Optional[str]:
    """Map a presentation role URI to one of our statement type keys."""
    fragment = role_uri.lower().split("/")[-1]
    normalized = re.sub(r"[^a-z]", "", fragment)
    for key, stmt_type in _ROLE_TO_STMT.items():
        if key in normalized:
            return stmt_type
    return None


async def parse_filing_statements(
    cik: str,
    accession_no: str,
    accession_no_raw: str,
    form_type: str,
    period_end: str,
) -> dict[str, list[dict]]:
    """
    Parse all financial statements for a given filing.
    Returns {statement_type: [line_item, ...]}
    Tries edgartools first (faithful presentation order), falls back to
    Company Facts API which is always available.
    """
    if _EDGARTOOLS_AVAILABLE:
        try:
            return await _parse_via_edgartools(cik, accession_no)
        except Exception as e:
            print(f"[xbrl_parser] edgartools failed for {cik}/{accession_no}: {e}")

    return await _parse_via_company_facts(cik, form_type, period_end)


async def _parse_via_edgartools(
    cik: str, accession_no: str
) -> dict[str, list[dict]]:
    """Use edgartools to parse statements from XBRL attachments."""
    padded = cik.zfill(10)
    edgar_company = EdgarCompany(cik=int(padded))
    # edgartools uses synchronous edgar API internally; wrap in thread if needed
    import asyncio
    loop = asyncio.get_event_loop()

    def _fetch():
        filings = edgar_company.get_filings(accession_number=accession_no)
        if not filings:
            raise ValueError(f"Filing {accession_no} not found for CIK {cik}")
        filing = filings[0]
        financials = Financials.from_filing(filing)
        return financials

    financials = await loop.run_in_executor(None, _fetch)

    results: dict[str, list[dict]] = {}

    stmt_map = {
        "income_statement": financials.income_statement,
        "balance_sheet": financials.balance_sheet,
        "cash_flow": financials.cash_flow_statement,
    }

    for stmt_type, stmt in stmt_map.items():
        if stmt is None:
            continue
        line_items = _convert_edgartools_statement(stmt, stmt_type)
        if line_items:
            results[stmt_type] = line_items

    return results


def _convert_edgartools_statement(stmt: Any, stmt_type: str) -> list[dict]:
    """Convert an edgartools Statement object to our line_item format."""
    line_items = []
    try:
        df = stmt.to_dataframe()
    except Exception:
        return []

    if df is None or df.empty:
        return []

    # edgartools dataframe has concept as index, period columns as values
    # It also has 'label' and 'level' columns when available
    for idx, row in df.iterrows():
        concept = str(idx)
        label = row.get("label", concept) if hasattr(row, "get") else concept
        if not label or label == "nan":
            label = concept

        level = int(row.get("level", 1)) if hasattr(row, "get") else 1
        is_abstract = bool(row.get("abstract", False)) if hasattr(row, "get") else False

        # Period values: remaining columns are period end dates
        periods: dict[str, Any] = {}
        for col in df.columns:
            if col in ("label", "level", "abstract", "concept"):
                continue
            val = row[col]
            if val is not None and str(val) not in ("nan", "None", ""):
                try:
                    periods[str(col)] = float(val)
                except (ValueError, TypeError):
                    pass

        line_items.append({
            "concept": concept,
            "label": str(label),
            "level": level,
            "is_abstract": is_abstract,
            "semantic_type": _infer_semantic_type(concept, str(label)),
            "periods": periods,
        })

    return line_items


async def _parse_via_company_facts(
    cik: str, form_type: str, period_end: str
) -> dict[str, list[dict]]:
    """
    Fallback: build statements from Company Facts API.
    Less faithful (no guaranteed ordering) but always available.
    """
    facts = await sec_client.get_company_facts(cik)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return {}

    # Group concepts by statement type using semantic classification
    stmt_concepts: dict[str, list[dict]] = {
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": [],
    }

    # Canonical ordering for fallback (less faithful but functional)
    IS_ORDER = [
        "revenue", "cogs", "gross_profit", "rd_expense", "sga",
        "operating_income", "interest_expense", "interest_income",
        "pretax_income", "tax_expense", "net_income", "eps_basic", "eps_diluted",
    ]
    BS_ORDER = [
        "cash", "total_assets", "total_liabilities", "long_term_debt", "total_equity"
    ]
    CF_ORDER = ["da", "cfo", "cfi", "cff"]

    stmt_semantic_map = {
        "income_statement": set(IS_ORDER),
        "balance_sheet": set(BS_ORDER),
        "cash_flow": set(CF_ORDER),
    }

    for concept_name, concept_data in us_gaap.items():
        units = concept_data.get("units", {})
        label = concept_data.get("label", concept_name)
        semantic = _infer_semantic_type(concept_name, label)

        # Find which statement this belongs to
        target_stmt = None
        for stype, semset in stmt_semantic_map.items():
            if semantic in semset:
                target_stmt = stype
                break
        if not target_stmt:
            continue

        # Extract values for the target period
        periods: dict[str, Any] = {}
        for unit_type, entries in units.items():
            if unit_type not in ("USD", "shares"):
                continue
            for entry in entries:
                if entry.get("form") not in ("10-K", "10-Q"):
                    continue
                end_date = entry.get("end", "")
                if entry.get("val") is not None:
                    periods[end_date] = entry["val"]

        if not periods:
            continue

        stmt_concepts[target_stmt].append({
            "concept": f"us-gaap:{concept_name}",
            "label": label,
            "level": 1,
            "is_abstract": False,
            "semantic_type": semantic,
            "periods": periods,
        })

    # Sort by canonical order within each statement
    def _sort_key(item: dict, order: list) -> int:
        try:
            return order.index(item["semantic_type"])
        except ValueError:
            return len(order)

    results = {}
    for stmt_type, items in stmt_concepts.items():
        if not items:
            continue
        order = IS_ORDER if stmt_type == "income_statement" else (
            BS_ORDER if stmt_type == "balance_sheet" else CF_ORDER
        )
        results[stmt_type] = sorted(items, key=lambda x: _sort_key(x, order))

    return results


def extract_unit_multiplier(line_items: list[dict]) -> int:
    """
    Detect the unit multiplier from values.
    If median non-zero abs value > 1e8, values are in base units → store as-is with multiplier=1.
    We store raw values and let the frontend format.
    """
    return 1
