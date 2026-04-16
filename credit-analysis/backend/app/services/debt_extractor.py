"""
Debt instrument extractor - 3-step pipeline:

Step 1: XBRL Dimensional data (LongtermDebtTypeAxis)
Step 2: HTML table parsing from 10-K/10-Q debt footnote
Step 3: EDGAR full-text search for originating filing
"""
import re
from datetime import date, datetime
from typing import Any, Optional

from bs4 import BeautifulSoup

from app.services import sec_client

# Regex patterns for debt parsing
_AMOUNT_RE = re.compile(
    r"\$?\s*([\d,]+(?:\.\d+)?)\s*(million|billion|thousand)?",
    re.IGNORECASE,
)
_RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_YEAR_RE = re.compile(r"\b(20\d\d)\b")
_DATE_FULL_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(20\d\d)", re.IGNORECASE)
_SOFR_RE = re.compile(r"(SOFR|LIBOR|EURIBOR)", re.IGNORECASE)
_SPREAD_RE = re.compile(r"\+\s*([\d.]+)\s*(bps|bp|basis points?)?", re.IGNORECASE)

_MONTHS = {m: i+1 for i, m in enumerate([
    "january","february","march","april","may","june",
    "july","august","september","october","november","december"
])}

_INSTRUMENT_TYPE_KEYWORDS = {
    "senior secured notes": "senior_notes",
    "senior notes": "senior_notes",
    "senior unsecured notes": "senior_notes",
    "subordinated notes": "sub_notes",
    "senior subordinated": "sub_notes",
    "term loan": "term_loan",
    "term a": "term_loan",
    "term b": "term_loan",
    "revolving credit": "revolver",
    "revolver": "revolver",
    "credit facility": "revolver",
    "convertible notes": "convertible",
    "convertible senior notes": "convertible",
    "debentures": "senior_notes",
    "notes due": "senior_notes",
}

_SENIORITY_KEYWORDS = {
    "senior secured": "senior_secured",
    "second lien": "senior_secured",
    "first lien": "senior_secured",
    "senior unsecured": "senior_unsecured",
    "senior notes": "senior_unsecured",
    "unsecured": "senior_unsecured",
    "subordinated": "subordinated",
    "junior subordinated": "subordinated",
    "pik": "pik",
}


async def extract_debt_instruments(
    cik: str,
    accession_no: str,
    accession_no_raw: str,
    doc_url: Optional[str],
) -> list[dict]:
    """
    Main pipeline: try all 3 steps, merge and deduplicate results.
    Returns a list of instrument dicts.
    """
    instruments: list[dict] = []

    # Step 1: XBRL dimensional data
    try:
        step1 = await _extract_from_xbrl_dimensions(cik)
        if step1:
            instruments.extend(step1)
    except Exception as e:
        print(f"[debt_extractor] Step1 XBRL failed for {cik}: {e}")

    # Step 2: HTML table parsing
    if doc_url:
        try:
            step2 = await _extract_from_html(cik, doc_url)
            # Only add instruments not already found
            existing_names = {_normalize_name(i["instrument_name"]) for i in instruments}
            for inst in step2:
                if _normalize_name(inst["instrument_name"]) not in existing_names:
                    instruments.append(inst)
                    existing_names.add(_normalize_name(inst["instrument_name"]))
        except Exception as e:
            print(f"[debt_extractor] Step2 HTML failed for {cik}: {e}")

    # Step 3: Link each instrument to its originating filing
    for inst in instruments:
        if not inst.get("originating_doc_url"):
            try:
                await _find_originating_filing(inst, cik)
            except Exception as e:
                print(f"[debt_extractor] Step3 search failed for {inst['instrument_name']}: {e}")

    return instruments


async def _extract_from_xbrl_dimensions(cik: str) -> list[dict]:
    """
    Look for LongtermDebtTypeAxis dimensional data in companyfacts.
    """
    facts = await sec_client.get_company_facts(cik)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    instruments = []
    for concept_name, concept_data in us_gaap.items():
        # Look for debt concepts with dimensional members
        if "LongTerm" not in concept_name and "Debt" not in concept_name:
            continue
        units = concept_data.get("units", {})
        for unit_type, entries in units.items():
            if unit_type != "USD":
                continue
            for entry in entries:
                segment = entry.get("segment")
                if not segment:
                    continue
                # dimensional entry has a segment with LongtermDebtTypeAxis
                dim = segment.get("dimension", "")
                member = segment.get("member", "")
                if "LongtermDebtType" not in dim and "DebtInstrument" not in dim:
                    continue

                name = _member_to_name(member)
                if not name:
                    continue

                instruments.append({
                    "instrument_name": name,
                    "instrument_type": _classify_instrument_type(name),
                    "seniority": _classify_seniority(name),
                    "principal_amount": entry.get("val"),
                    "currency": "USD",
                    "coupon_rate": None,
                    "coupon_type": None,
                    "floating_benchmark": None,
                    "floating_spread": None,
                    "maturity_date": None,
                    "issuance_date": _parse_date(entry.get("start")),
                    "confidence_score": 0.9,
                    "originating_doc_url": None,
                    "originating_doc_type": None,
                    "raw_data": entry,
                })

    return instruments


async def _extract_from_html(cik: str, doc_url: str) -> list[dict]:
    """
    Parse the 10-K HTML to find the long-term debt footnote table.
    """
    html_bytes = await sec_client.get_filing_document(doc_url)
    html = html_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    # Find the debt section heading
    debt_section = _find_debt_section(soup)
    if not debt_section:
        return []

    # Find the nearest table after the heading
    table = None
    for sibling in debt_section.find_next_siblings():
        if sibling.name == "table":
            table = sibling
            break
        if sibling.name in ("h2", "h3", "h4") and sibling != debt_section:
            break

    if not table:
        # Try looking for any table within 3000 chars of the heading
        heading_pos = str(soup).find(str(debt_section))
        if heading_pos > 0:
            snippet = str(soup)[heading_pos:heading_pos + 5000]
            snippet_soup = BeautifulSoup(snippet, "lxml")
            table = snippet_soup.find("table")

    if not table:
        return []

    return _parse_debt_table(table, cik)


def _find_debt_section(soup: BeautifulSoup) -> Optional[Any]:
    """Find the heading element for the long-term debt note."""
    patterns = [
        re.compile(r"long.?term debt", re.IGNORECASE),
        re.compile(r"debt and credit", re.IGNORECASE),
        re.compile(r"borrowings", re.IGNORECASE),
        re.compile(r"note\s+\d+.*debt", re.IGNORECASE),
    ]
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "div"]):
        text = tag.get_text(strip=True)
        for pat in patterns:
            if pat.search(text) and len(text) < 200:
                return tag
    return None


def _parse_debt_table(table: Any, cik: str) -> list[dict]:
    """Parse rows from a debt table."""
    instruments = []
    rows = table.find_all("tr")

    for row in rows[1:]:  # skip header
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells or not cells[0]:
            continue

        name = cells[0]
        if len(name) < 5 or name.lower() in ("total", "total long-term debt", "less:"):
            continue

        inst = _parse_instrument_row(name, cells)
        if inst:
            instruments.append(inst)

    return instruments


def _parse_instrument_row(name: str, cells: list[str]) -> Optional[dict]:
    """Extract instrument fields from a table row."""
    full_text = " ".join(cells)

    # Try to extract amount from cells[1] or cells[2]
    amount = None
    for cell in cells[1:4]:
        m = _AMOUNT_RE.search(cell.replace(",", ""))
        if m:
            val = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower()
            if unit == "billion":
                val *= 1_000_000_000
            elif unit == "million":
                val *= 1_000_000
            elif unit == "thousand":
                val *= 1_000
            amount = val
            break

    # Try to extract coupon rate
    coupon_rate = None
    coupon_type = "fixed"
    rate_match = _RATE_RE.search(name)
    if rate_match:
        coupon_rate = float(rate_match.group(1)) / 100
    elif _SOFR_RE.search(full_text):
        coupon_type = "floating"
        spread_match = _SPREAD_RE.search(full_text)
        if spread_match:
            spread_val = float(spread_match.group(1))
            coupon_rate = spread_val / 10000 if spread_val > 10 else spread_val / 100

    # Try to extract maturity date
    maturity = None
    date_match = _DATE_FULL_RE.search(full_text)
    if date_match:
        month_name = date_match.group(1).lower()
        day = int(date_match.group(2))
        year = int(date_match.group(3))
        month = _MONTHS.get(month_name, 1)
        try:
            maturity = date(year, month, day)
        except ValueError:
            pass
    if not maturity:
        year_match = _YEAR_RE.search(name)
        if year_match:
            year = int(year_match.group(1))
            if year >= 2025:
                try:
                    maturity = date(year, 12, 31)
                except ValueError:
                    pass

    # Floating benchmark
    floating_benchmark = None
    floating_spread = None
    sofr_match = _SOFR_RE.search(full_text)
    if sofr_match:
        floating_benchmark = sofr_match.group(1).upper()
        coupon_type = "floating"
        spread_match = _SPREAD_RE.search(full_text)
        if spread_match:
            spread_val = float(spread_match.group(1))
            floating_spread = spread_val / 10000 if spread_val > 100 else spread_val / 100

    if not amount and not maturity:
        return None

    confidence = 0.8
    if amount and maturity:
        confidence = 0.9
    if coupon_rate:
        confidence = min(0.95, confidence + 0.05)

    return {
        "instrument_name": name,
        "instrument_type": _classify_instrument_type(name),
        "seniority": _classify_seniority(name),
        "principal_amount": amount,
        "currency": "USD",
        "coupon_rate": coupon_rate,
        "coupon_type": coupon_type,
        "floating_benchmark": floating_benchmark,
        "floating_spread": floating_spread,
        "maturity_date": maturity,
        "issuance_date": None,
        "confidence_score": confidence,
        "originating_doc_url": None,
        "originating_doc_type": None,
        "raw_data": {"cells": cells},
    }


async def _find_originating_filing(inst: dict, cik: str) -> None:
    """
    Step 3: Search EDGAR for the originating filing (8-K, prospectus, indenture).
    Modifies the instrument dict in place.
    """
    name = inst["instrument_name"]
    # Build search query from key parts of the name
    # e.g. "6.25% Senior Notes due 2032" → "6.25% Senior Notes"
    query_parts = []
    rate_match = _RATE_RE.search(name)
    if rate_match:
        query_parts.append(rate_match.group(0))
    for kw in ["Senior Notes", "Term Loan", "Revolving Credit", "Senior Secured", "Subordinated"]:
        if kw.lower() in name.lower():
            query_parts.append(kw)
            break
    year_match = _YEAR_RE.search(name)
    if year_match:
        query_parts.append(year_match.group(0))

    if not query_parts:
        return

    query = " ".join(query_parts[:3])
    maturity = inst.get("maturity_date")
    start_dt = None
    end_dt = None
    if maturity and isinstance(maturity, date):
        # Search filings from 5 years before maturity to now
        start_yr = max(2000, maturity.year - 15)
        start_dt = f"{start_yr}-01-01"
        end_dt = datetime.now().strftime("%Y-%m-%d")

    try:
        results = await sec_client.search_fulltext(
            query=query,
            cik=cik,
            forms="8-K,S-3,424B5,424B3",
            start_dt=start_dt,
            end_dt=end_dt,
            hits_per_page=5,
        )
        hits = results.get("hits", {}).get("hits", [])
        if not hits:
            # Try without CIK filter
            results = await sec_client.search_fulltext(
                query=query,
                forms="8-K,S-3,424B5",
                hits_per_page=3,
            )
            hits = results.get("hits", {}).get("hits", [])
    except Exception:
        return

    if not hits:
        return

    best_hit = hits[0]
    source = best_hit.get("_source", {})
    filing_id_str = best_hit.get("_id", "")
    acc_no = source.get("file_date", "")
    entity_id = source.get("entity_id", cik)

    # Try to get the accession number from the hit
    # EDGAR EFTS returns _id in format "accession_number_no_dashes"
    if filing_id_str and len(filing_id_str) == 18:
        acc_raw = filing_id_str
        form_type = source.get("form_type", "8-K")
        try:
            index = await sec_client.get_filing_index(entity_id, acc_raw)
            items = index.get("directory", {}).get("item", [])
            for item in items:
                item_name = item.get("name", "").lower()
                if any(kw in item_name for kw in ["indenture", "prospectus", "exhibit"]):
                    inst["originating_doc_url"] = sec_client.build_doc_url(
                        entity_id, acc_raw, item["name"]
                    )
                    inst["originating_doc_type"] = _classify_doc_type(item["name"], form_type)
                    return
            # Fall back to the primary doc
            for item in items:
                if item.get("type") in ("10-K", "8-K", "S-3", "424B5"):
                    inst["originating_doc_url"] = sec_client.build_doc_url(
                        entity_id, acc_raw, item["name"]
                    )
                    inst["originating_doc_type"] = form_type
                    return
        except Exception:
            pass

    # Minimal fallback: point to EDGAR search
    inst["originating_doc_type"] = "8-K"


def _member_to_name(member: str) -> str:
    """Convert XBRL member name to human-readable instrument name."""
    name = re.sub(r"([A-Z])", r" \1", member).strip()
    name = re.sub(r"\s+", " ", name)
    return name.replace("Member", "").strip()


def _classify_instrument_type(name: str) -> str:
    name_lower = name.lower()
    for kw, itype in _INSTRUMENT_TYPE_KEYWORDS.items():
        if kw in name_lower:
            return itype
    return "other"


def _classify_seniority(name: str) -> str:
    name_lower = name.lower()
    for kw, seniority in _SENIORITY_KEYWORDS.items():
        if kw in name_lower:
            return seniority
    if "notes" in name_lower or "debenture" in name_lower:
        return "senior_unsecured"
    if "term loan" in name_lower or "revolver" in name_lower:
        return "senior_secured"
    return "senior_unsecured"


def _classify_doc_type(filename: str, form_type: str) -> str:
    fn = filename.lower()
    if "indent" in fn:
        return "indenture"
    if "prosp" in fn or "424" in fn:
        return "prospectus"
    if "credit" in fn or "loan" in fn:
        return "credit_agreement"
    return form_type


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str[:10])
    except (ValueError, TypeError):
        return None


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())
