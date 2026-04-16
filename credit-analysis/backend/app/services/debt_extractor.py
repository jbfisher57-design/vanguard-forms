"""
Debt instrument extractor - 3-step pipeline:

Step 1: XBRL concept-level data (specific debt concepts from companyfacts)
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

# Ordered list of XBRL concepts to probe, from most-specific to least-specific.
# Tuple: (concept_name, display_name, confidence)
_XBRL_DEBT_CONCEPTS = [
    ("SeniorNotes", "Senior Notes", 0.75),
    ("SeniorSecuredNotes", "Senior Secured Notes", 0.80),
    ("SeniorUnsecuredNotes", "Senior Unsecured Notes", 0.80),
    ("SeniorSubordinatedNotes", "Senior Subordinated Notes", 0.80),
    ("SubordinatedNotes", "Subordinated Notes", 0.80),
    ("JuniorSubordinatedNotes", "Junior Subordinated Notes", 0.80),
    ("ConvertibleNotesPayable", "Convertible Notes", 0.80),
    ("SecuredDebt", "Secured Debt", 0.70),
    ("UnsecuredDebt", "Unsecured Debt", 0.70),
    ("LineOfCredit", "Revolving Credit Facility", 0.75),
    ("NotesPayable", "Notes Payable", 0.65),
    ("LongTermDebtNoncurrent", "Long-Term Debt", 0.60),
    ("LongTermDebt", "Long-Term Debt (Total)", 0.55),
]

# Concepts to skip if more specific ones were already found
_AGGREGATE_FALLBACK_CONCEPTS = {"LongTermDebtNoncurrent", "LongTermDebt"}

_DEBT_TABLE_KEYWORDS = re.compile(
    r"(senior\s+notes|term\s+loan|revolv|debenture|senior\s+secured|"
    r"subordinated|convertible|%\s+due\s+|%\s+notes|notes\s+due|"
    r"credit\s+facility|long.?term\s+debt)",
    re.IGNORECASE,
)


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

    # Step 1: XBRL concept-level data
    try:
        step1 = await _extract_from_xbrl_concepts(cik)
        if step1:
            print(f"[debt_extractor] Step1 found {len(step1)} instruments via XBRL concepts")
            instruments.extend(step1)
        else:
            print(f"[debt_extractor] Step1: no XBRL concept data found for {cik}")
    except Exception as e:
        print(f"[debt_extractor] Step1 XBRL failed for {cik}: {e}")

    # Step 2: HTML table parsing
    if doc_url:
        try:
            step2 = await _extract_from_html(cik, doc_url)
            print(f"[debt_extractor] Step2 found {len(step2)} instruments via HTML")
            existing_names = {_normalize_name(i["instrument_name"]) for i in instruments}
            for inst in step2:
                norm = _normalize_name(inst["instrument_name"])
                if norm not in existing_names:
                    instruments.append(inst)
                    existing_names.add(norm)
        except Exception as e:
            print(f"[debt_extractor] Step2 HTML failed for {cik}: {e}")
    else:
        print(f"[debt_extractor] Step2 skipped: no doc_url for {cik}")

    print(f"[debt_extractor] Total instruments after Steps 1+2: {len(instruments)}")

    # Step 3: Link each instrument to its originating filing
    for inst in instruments:
        if not inst.get("originating_doc_url"):
            try:
                await _find_originating_filing(inst, cik)
            except Exception as e:
                print(f"[debt_extractor] Step3 search failed for {inst['instrument_name']}: {e}")

    return instruments


async def _extract_from_xbrl_concepts(cik: str) -> list[dict]:
    """
    Look for common debt XBRL concepts in the companyfacts API.
    The companyfacts API does NOT expose segment/dimensional breakdowns,
    so we probe specific concept names directly.
    """
    facts = await sec_client.get_company_facts(cik)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    instruments = []
    seen = set()
    has_specific = False  # True once we find a more specific concept than the aggregate fallbacks

    for concept_name, display_name, confidence in _XBRL_DEBT_CONCEPTS:
        if concept_name not in us_gaap:
            continue

        # Skip aggregate fallbacks if we already have specific instruments
        if has_specific and concept_name in _AGGREGATE_FALLBACK_CONCEPTS:
            continue

        units_data = us_gaap[concept_name].get("units", {}).get("USD", [])
        if not units_data:
            continue

        # Prefer 10-K FY entries with a positive value
        fy_entries = [
            e for e in units_data
            if e.get("form") in ("10-K",) and (e.get("val") or 0) > 0
        ]
        if not fy_entries:
            fy_entries = [e for e in units_data if (e.get("val") or 0) > 0]
        if not fy_entries:
            continue

        recent = max(fy_entries, key=lambda e: e.get("end", ""))

        norm = _normalize_name(display_name)
        if norm in seen:
            continue
        seen.add(norm)

        if concept_name not in _AGGREGATE_FALLBACK_CONCEPTS:
            has_specific = True

        instruments.append({
            "instrument_name": display_name,
            "instrument_type": _classify_instrument_type(display_name),
            "seniority": _classify_seniority(display_name),
            "principal_amount": recent.get("val"),
            "currency": "USD",
            "coupon_rate": None,
            "coupon_type": "fixed",
            "floating_benchmark": None,
            "floating_spread": None,
            "maturity_date": None,
            "issuance_date": _parse_date(recent.get("start")),
            "confidence_score": confidence,
            "originating_doc_url": None,
            "originating_doc_type": None,
            "raw_data": {"concept": concept_name, "entry": recent},
        })

    return instruments


async def _extract_from_html(cik: str, doc_url: str) -> list[dict]:
    """
    Parse the 10-K HTML to find the long-term debt footnote table.
    """
    try:
        html_bytes = await sec_client.get_filing_document(doc_url)
    except Exception as e:
        print(f"[debt_extractor] Failed to fetch {doc_url}: {e}")
        return []

    html = html_bytes.decode("utf-8", errors="replace")
    print(f"[debt_extractor] Fetched HTML doc size={len(html):,} bytes")
    soup = BeautifulSoup(html, "lxml")

    # Find the debt section heading
    debt_section = _find_debt_section(soup)
    print(f"[debt_extractor] Debt section heading found: {debt_section is not None}")
    if debt_section:
        print(f"[debt_extractor] Debt section text: {debt_section.get_text(strip=True)[:100]}")

    instruments = []

    if debt_section:
        # Search sibling elements for a table
        stop_tags = {"h1", "h2"}
        for sibling in debt_section.find_next_siblings():
            if sibling.name in stop_tags:
                break
            if sibling.name == "h3" or sibling.name == "h4":
                txt = sibling.get_text(strip=True).lower()
                if not any(kw in txt for kw in ["debt", "note", "borrow", "credit"]):
                    break
            if sibling.name == "table":
                parsed = _parse_debt_table(sibling, cik)
                instruments.extend(parsed)
                if instruments:
                    break

        if not instruments:
            # Search within parent container
            parent = debt_section.parent
            if parent:
                for table in parent.find_all("table", recursive=True):
                    parsed = _parse_debt_table(table, cik)
                    if parsed:
                        instruments.extend(parsed)
                        break

    if not instruments:
        # Fallback: scan all tables for debt-related content
        instruments = _scan_all_tables_for_debt(soup, cik)
        if instruments:
            print(f"[debt_extractor] Found {len(instruments)} instruments via full-table scan")

    return instruments


def _scan_all_tables_for_debt(soup: BeautifulSoup, cik: str) -> list[dict]:
    """Scan all tables in the document for debt-related content."""
    instruments = []
    seen = set()
    for table in soup.find_all("table"):
        table_text = table.get_text()
        if _DEBT_TABLE_KEYWORDS.search(table_text):
            parsed = _parse_debt_table(table, cik)
            for inst in parsed:
                norm = _normalize_name(inst["instrument_name"])
                if norm not in seen:
                    instruments.append(inst)
                    seen.add(norm)
    return instruments


def _find_debt_section(soup: BeautifulSoup) -> Optional[Any]:
    """Find the heading element for the long-term debt note."""
    patterns = [
        re.compile(r"long.?term\s+debt", re.IGNORECASE),
        re.compile(r"debt\s+and\s+(credit|financing|borrowing)", re.IGNORECASE),
        re.compile(r"note\s+\d+\s*[–\-:\.]\s*(?:long.?term\s+)?debt", re.IGNORECASE),
        re.compile(r"debt\s+obligations", re.IGNORECASE),
        re.compile(r"borrowings", re.IGNORECASE),
    ]

    # Heading tags first
    for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = tag.get_text(strip=True)
        if len(text) > 200:
            continue
        for pat in patterns:
            if pat.search(text):
                return tag

    # div/span/p with bold styling (iXBRL uses these for headings)
    for tag in soup.find_all(["p", "div", "span"]):
        text = tag.get_text(strip=True)
        if not text or len(text) > 200:
            continue
        for pat in patterns:
            if pat.search(text):
                style = tag.get("style", "").lower()
                classes = " ".join(tag.get("class", [])).lower()
                if any(kw in style for kw in ["bold", "font-weight"]):
                    return tag
                if any(kw in classes for kw in ["bold", "heading", "title"]):
                    return tag

    # Final fallback: any short element containing debt text
    for tag in soup.find_all(["p", "div"]):
        text = tag.get_text(strip=True)
        if 5 < len(text) < 120:
            for pat in patterns:
                if pat.search(text):
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
        if len(name) < 5 or name.lower() in ("total", "total long-term debt", "less:", "less current portion"):
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
    entity_id = source.get("entity_id", cik)

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
            for item in items:
                if item.get("type") in ("10-K", "8-K", "S-3", "424B5"):
                    inst["originating_doc_url"] = sec_client.build_doc_url(
                        entity_id, acc_raw, item["name"]
                    )
                    inst["originating_doc_type"] = form_type
                    return
        except Exception:
            pass

    inst["originating_doc_type"] = "8-K"


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
    if "term loan" in name_lower or "revolver" in name_lower or "credit facility" in name_lower:
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
