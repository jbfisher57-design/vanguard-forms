"""
XBRL parser service.

Primary path: parse the filing's XBRL presentation linkbase (.pre.xml)
to get concepts in filing order with proper hierarchy.

Fallback: use the SEC Company Facts API (flatter, less faithful ordering).

Output line-item format:
[{
    concept: str,           # "us-gaap:Revenues"
    label: str,             # Label exactly as filed
    level: int,             # Indentation depth (1 = top)
    is_abstract: bool,      # True for section-header rows
    semantic_type: str,     # "revenue" | "cogs" | ...
    periods: {              # ISO-date -> raw USD value
        "2024-12-31": 97690000000,
        "2023-12-31": 96773000000,
    }
}]
"""
import re
import xml.etree.ElementTree as ET
from datetime import date as _date
from typing import Any, Optional

from app.services import sec_client

# edgartools optional
try:
    from edgar import Company as EdgarCompany
    _EDGARTOOLS_AVAILABLE = True
except ImportError:
    _EDGARTOOLS_AVAILABLE = False

# ── XML namespaces ────────────────────────────────────────────────────────────
_LINK_NS = "http://www.xbrl.org/2003/linkbase"
_XLINK_NS = "http://www.w3.org/1999/xlink"

# ── Role URI → statement type ─────────────────────────────────────────────────
_ROLE_TO_STMT: dict[str, str] = {
    "incomestatement": "income_statement",
    "statementofoperations": "income_statement",
    "consolidatedstatementofoperations": "income_statement",
    "consolidatedstatementsofincome": "income_statement",
    "statementsofoperations": "income_statement",
    "operationsstatement": "income_statement",
    "comprehensiveincome": "income_statement",
    "balancesheet": "balance_sheet",
    "consolidatedbalancesheets": "balance_sheet",
    "financialposition": "balance_sheet",
    "statementoffinancialposition": "balance_sheet",
    "cashflow": "cash_flow",
    "cashflows": "cash_flow",
    "consolidatedstatementofcashflows": "cash_flow",
    "statementofcashflows": "cash_flow",
}

# ── Semantic type inference ───────────────────────────────────────────────────
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

IS_ORDER = ["revenue","cogs","gross_profit","rd_expense","sga",
            "operating_income","interest_expense","interest_income",
            "da","pretax_income","tax_expense","net_income",
            "eps_basic","eps_diluted","other"]
BS_ORDER = ["cash","total_assets","total_liabilities","long_term_debt","total_equity","other"]
CF_ORDER = ["da","cfo","cfi","cff","other"]

# Keywords that identify cash-flow concepts (duration, but not IS)
_CF_SUBSTRINGS: frozenset = frozenset([
    "operatingactivit","investingactivit","financingactivit",
    "netcashprovid","netcashused","cashprovided","cashused",
    "purchaseofproperty","purchaseofintangible","purchaseofinvestment",
    "acquisitionofbusiness","proceedsfromsale","proceedsfromdisposal",
    "proceedsfromissuance","proceedsfrommaturity","proceedsfromlong",
    "repaymentoflong","repaymentofdebt","borrowingunderrevol",
    "paymentofdividend","dividendspaid","repurchaseofcommon",
    "paymentforrepurchase","effectofexchangerate",
    "netincreaseincase","netdecreaseincash","cashatend","cashatbegin",
    "netchangeincash","capitalexpenditure","financeleasepayment",
])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_concept(concept: str) -> str:
    if ":" in concept:
        concept = concept.split(":", 1)[1]
    return re.sub(r"[^a-z0-9]", "", concept.lower())


def _infer_semantic_type(concept: str, label: str) -> str:
    key = _normalize_concept(concept)
    if key in _CONCEPT_SEMANTIC:
        return _CONCEPT_SEMANTIC[key]
    if not label:
        return "other"
    ll = label.lower()
    if "revenue" in ll or "net sales" in ll:
        return "revenue"
    if "cost of" in ll:
        return "cogs"
    if "gross profit" in ll:
        return "gross_profit"
    if "operating income" in ll or "operating loss" in ll:
        return "operating_income"
    if "net income" in ll or "net loss" in ll:
        return "net_income"
    if "depreciation" in ll or "amortization" in ll:
        return "da"
    if "interest expense" in ll:
        return "interest_expense"
    if "income tax" in ll:
        return "tax_expense"
    return "other"


def _role_to_statement_type(role_uri: str) -> Optional[str]:
    fragment = role_uri.lower().split("/")[-1]
    normalized = re.sub(r"[^a-z]", "", fragment)
    for key, stmt_type in _ROLE_TO_STMT.items():
        if key in normalized:
            return stmt_type
    return None


def _is_cf_concept(concept_name: str) -> bool:
    norm = re.sub(r"[^a-z0-9]", "", concept_name.lower())
    return any(sub in norm for sub in _CF_SUBSTRINGS)


def _camel_to_label(name: str) -> str:
    """CamelCase → human readable (fallback when no label available)."""
    s = re.sub(r"([A-Z])", r" \1", name).strip()
    return re.sub(r"\s+", " ", s)


def _get_all_unit_entries(units: dict) -> list:
    out = []
    for unit_type, entries in units.items():
        if unit_type in ("USD", "shares", "USD/shares"):
            out.extend(entries)
    return out


def _extract_periods_for_form_type(
    units: dict, form_type: str, is_instant: bool
) -> dict[str, float]:
    """Return {end_date: value} filtered by form_type; skip YTD entries for 10-Q."""
    best: dict[str, tuple] = {}  # end_date -> (filed, val)

    for unit_type, entries in units.items():
        if unit_type not in ("USD", "shares", "USD/shares"):
            continue
        for entry in entries:
            if entry.get("form") != form_type:
                continue
            end_date = entry.get("end", "")
            val = entry.get("val")
            filed = entry.get("filed", "")
            start_date = entry.get("start", "")
            if val is None or not end_date:
                continue
            # Skip YTD entries for quarterly display
            if form_type == "10-Q" and not is_instant and start_date:
                try:
                    s = _date.fromisoformat(start_date)
                    e = _date.fromisoformat(end_date)
                    if (e - s).days > 130:
                        continue
                except ValueError:
                    pass
            if end_date not in best or filed > best[end_date][0]:
                best[end_date] = (filed, val)

    return {k: v[1] for k, v in best.items()}


# ── Main entry point ──────────────────────────────────────────────────────────

async def parse_filing_statements(
    cik: str,
    accession_no: str,
    accession_no_raw: str,
    form_type: str,
    period_end: str,
) -> dict[str, list[dict]]:
    """
    Return {statement_type: [line_item, ...]} for the given filing.
    Tries XBRL presentation linkbase first (faithful filing order),
    then falls back to Company Facts API classification.
    """
    # Fetch company facts once — reused by both paths
    facts = await sec_client.get_company_facts(cik)

    # Primary: parse .pre.xml for faithful presentation order
    result: dict[str, list[dict]] = {}
    if accession_no_raw:
        try:
            result = await _parse_via_xbrl_files(cik, accession_no_raw, form_type, facts)
        except Exception as e:
            import traceback
            print(f"[xbrl_parser] .pre.xml parse failed for {cik}: {e}")
            traceback.print_exc()

    # Fill any missing statements from the Company Facts fallback
    needed = {"income_statement", "balance_sheet", "cash_flow"}
    missing = needed - set(result.keys())
    if missing:
        cf = _parse_via_company_facts_data(facts, form_type)
        for s in missing:
            if s in cf:
                result[s] = cf[s]

    return result


# ── XBRL presentation-linkbase parser ────────────────────────────────────────

async def _parse_via_xbrl_files(
    cik: str,
    accession_no_raw: str,
    form_type: str,
    facts: dict,
) -> dict[str, list[dict]]:
    """
    1. Fetch filing index → find .pre.xml
    2. Parse presentation tree to get concept order and hierarchy
    3. Look up period values from Company Facts
    """
    # ── Find .pre.xml ─────────────────────────────────────────────────────────
    try:
        index = await sec_client.get_filing_index(cik, accession_no_raw)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch filing index: {e}")

    items = index.get("directory", {}).get("item", [])
    pre_file = next(
        (i["name"] for i in items
         if i.get("name", "").endswith("_pre.xml")
         or i.get("name", "").endswith("-pre.xml")),
        None,
    )
    if not pre_file:
        raise RuntimeError(f"No .pre.xml in filing {accession_no_raw}")

    # ── Fetch and parse XML ───────────────────────────────────────────────────
    pre_url = sec_client.build_doc_url(cik, accession_no_raw, pre_file)
    pre_bytes = await sec_client.get_filing_document(pre_url)
    try:
        root = ET.fromstring(pre_bytes)
    except ET.ParseError as e:
        raise RuntimeError(f"XML parse error in {pre_file}: {e}")

    # ── Build concept → {label, periods} from Company Facts ──────────────────
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    concept_map: dict[str, dict] = {}
    for cname, cdata in us_gaap.items():
        label = cdata.get("label") or cname
        if "(Deprecated" in label or "Deprecated" in cname:
            continue
        all_entries = _get_all_unit_entries(cdata.get("units", {}))
        is_instant = bool(all_entries) and not any("start" in e for e in all_entries)
        periods = _extract_periods_for_form_type(
            cdata.get("units", {}), form_type, is_instant
        )
        concept_map[cname] = {"label": label, "periods": periods, "is_instant": is_instant}

    # ── Parse each presentationLink ──────────────────────────────────────────
    results: dict[str, list[dict]] = {}

    for plink in root.findall(f"{{{_LINK_NS}}}presentationLink"):
        role = plink.get(f"{{{_XLINK_NS}}}role", "")
        stmt_type = _role_to_statement_type(role)
        if not stmt_type or stmt_type in results:
            continue

        # Locator map: xlink:label → concept_name
        loc_map: dict[str, str] = {}
        for loc in plink.findall(f"{{{_LINK_NS}}}loc"):
            xlink_lbl = loc.get(f"{{{_XLINK_NS}}}label", "")
            href = loc.get(f"{{{_XLINK_NS}}}href", "")
            if "#" not in href:
                continue
            concept_ref = href.split("#")[1]
            # concept_ref = "us-gaap_Revenues" or "tsla_AutomotiveSales"
            if "_" in concept_ref:
                ns, cname = concept_ref.split("_", 1)
            else:
                ns, cname = "us-gaap", concept_ref
            # Only include us-gaap concepts (others lack Company Facts values)
            if ns == "us-gaap":
                loc_map[xlink_lbl] = cname

        if not loc_map:
            continue

        # Build parent→children adjacency from arcs
        children: dict[str, list[tuple[float, str]]] = {}
        all_to: set[str] = set()

        for arc in plink.findall(f"{{{_LINK_NS}}}presentationArc"):
            from_lbl = arc.get(f"{{{_XLINK_NS}}}from", "")
            to_lbl = arc.get(f"{{{_XLINK_NS}}}to", "")
            try:
                order = float(arc.get("order", "0"))
            except ValueError:
                order = 0.0
            if from_lbl not in children:
                children[from_lbl] = []
            children[from_lbl].append((order, to_lbl))
            all_to.add(to_lbl)

        for parent in children:
            children[parent].sort(key=lambda x: x[0])

        root_labels = [lbl for lbl in loc_map if lbl not in all_to]

        # DFS traversal → ordered line items
        line_items: list[dict] = []
        visited: set[str] = set()

        def traverse(lbl: str, depth: int) -> None:
            if lbl in visited:
                return
            visited.add(lbl)

            cname = loc_map.get(lbl)
            if not cname:
                return

            has_ch = lbl in children
            data = concept_map.get(cname)

            if data:
                periods = data["periods"]
                label_text = data["label"]
            else:
                periods = {}
                label_text = _camel_to_label(cname)

            is_abstract = (not periods) and has_ch

            if periods or has_ch:
                line_items.append({
                    "concept": f"us-gaap:{cname}",
                    "label": label_text,
                    "level": depth,
                    "is_abstract": is_abstract,
                    "semantic_type": _infer_semantic_type(cname, label_text),
                    "periods": periods,
                })

            if has_ch:
                for _, child_lbl in children[lbl]:
                    traverse(child_lbl, depth + 1)

        for root_lbl in root_labels:
            traverse(root_lbl, 1)

        if line_items:
            results[stmt_type] = line_items
            print(f"[xbrl_parser] .pre.xml {stmt_type}: {len(line_items)} items from {pre_file}")

    return results


# ── Company Facts fallback ───────────────────────────────────────────────────

def _parse_via_company_facts_data(
    facts: dict, form_type: str
) -> dict[str, list[dict]]:
    """
    Classify all Company Facts concepts into statements using the
    instant-vs-duration heuristic (no deprecated concepts).
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return {}

    stmt_concepts: dict[str, list[dict]] = {
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": [],
    }

    for cname, cdata in us_gaap.items():
        label = cdata.get("label") or cname
        if "(Deprecated" in label or "Deprecated" in cname:
            continue

        all_entries = _get_all_unit_entries(cdata.get("units", {}))
        if not all_entries:
            continue

        has_duration = any("start" in e for e in all_entries)
        is_instant = not has_duration

        if is_instant:
            target = "balance_sheet"
        elif _is_cf_concept(cname):
            target = "cash_flow"
        else:
            target = "income_statement"

        periods = _extract_periods_for_form_type(
            cdata.get("units", {}), form_type, is_instant
        )
        if not periods:
            continue

        stmt_concepts[target].append({
            "concept": f"us-gaap:{cname}",
            "label": label,
            "level": 1,
            "is_abstract": False,
            "semantic_type": _infer_semantic_type(cname, label),
            "periods": periods,
        })

    def _sort_key(item: dict, order: list) -> tuple:
        try:
            return (order.index(item["semantic_type"]), item["label"])
        except ValueError:
            return (len(order), item["label"])

    results: dict[str, list[dict]] = {}
    for stmt_type, items in stmt_concepts.items():
        if not items:
            continue
        order = IS_ORDER if stmt_type == "income_statement" else (
            BS_ORDER if stmt_type == "balance_sheet" else CF_ORDER
        )
        results[stmt_type] = sorted(items, key=lambda x: _sort_key(x, order))

    print(
        f"[xbrl_parser] company_facts fallback: "
        + ", ".join(f"{k}={len(v)}" for k, v in results.items())
    )
    return results


# ── Legacy / edgartools path (unused but kept for reference) ─────────────────

async def _parse_via_company_facts(
    cik: str, form_type: str, period_end: str
) -> dict[str, list[dict]]:
    facts = await sec_client.get_company_facts(cik)
    return _parse_via_company_facts_data(facts, form_type)


def extract_unit_multiplier(line_items: list[dict]) -> int:
    return 1
