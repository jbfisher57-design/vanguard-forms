"""
Forecast engine.

Applies per-row assumptions to compute forecast values for all line items.

Supported methods:
  pct_revenue_growth  - Revenue grows at specified % per period
  gross_margin_pct    - COGS = Revenue * (1 - margin)
  ebitda_margin_pct   - EBITDA = Revenue * margin
  pct_of_revenue      - Line = Revenue * pct
  direct_input        - User supplies absolute values per period
  copy_historical     - Flat-line the most recent historical value
  yoy_growth          - Apply fixed YoY growth rate to prior period
  formula_sum         - Sum of other concepts (used for subtotals)
"""
from typing import Any, Optional


def compute_forecasts(
    line_items: list[dict],
    assumptions: list[dict],
    forecast_periods: list[dict],
    historical_period_keys: list[str],
) -> dict[str, dict[str, Optional[float]]]:
    """
    Compute forecast values for all line items.

    Returns: {concept: {period_label: value_or_None}}
    """
    # Build assumption lookup
    assumption_map: dict[str, dict] = {a["concept"]: a for a in assumptions}

    # Build historical values lookup: concept -> {period_key: value}
    historical: dict[str, dict[str, float]] = {}
    for item in line_items:
        if item.get("is_abstract"):
            continue
        historical[item["concept"]] = item.get("periods", {})

    # Most recent historical value per concept
    def last_hist(concept: str) -> Optional[float]:
        periods = historical.get(concept, {})
        if not periods:
            return None
        return periods.get(sorted(periods.keys())[-1])

    # Find revenue concept for margin-based methods
    revenue_concept = _find_revenue_concept(line_items)
    forecast_period_labels = [p["label"] for p in forecast_periods]

    results: dict[str, dict[str, Optional[float]]] = {}

    # First pass: compute revenue (needed by other methods)
    if revenue_concept:
        rev_assumption = assumption_map.get(revenue_concept, {})
        results[revenue_concept] = _apply_method(
            concept=revenue_concept,
            assumption=rev_assumption,
            forecast_period_labels=forecast_period_labels,
            last_hist_val=last_hist(revenue_concept),
            revenue_by_period={},  # not yet available, use 0 placeholder
            historical=historical,
        )

    # Get forecast revenue by period for margin methods
    forecast_revenue: dict[str, Optional[float]] = {}
    if revenue_concept and revenue_concept in results:
        forecast_revenue = results[revenue_concept]

    # Second pass: all other items
    for item in line_items:
        concept = item["concept"]
        if concept == revenue_concept:
            continue
        if item.get("is_abstract"):
            results[concept] = {p: None for p in forecast_period_labels}
            continue

        assumption = assumption_map.get(concept, {})
        results[concept] = _apply_method(
            concept=concept,
            assumption=assumption,
            forecast_period_labels=forecast_period_labels,
            last_hist_val=last_hist(concept),
            revenue_by_period=forecast_revenue,
            historical=historical,
        )

    return results


def _apply_method(
    concept: str,
    assumption: dict,
    forecast_period_labels: list[str],
    last_hist_val: Optional[float],
    revenue_by_period: dict[str, Optional[float]],
    historical: dict[str, dict[str, float]],
) -> dict[str, Optional[float]]:
    method = assumption.get("method", "copy_historical")
    params = assumption.get("params", {})
    overrides = assumption.get("overrides", {})

    out: dict[str, Optional[float]] = {}

    for i, label in enumerate(forecast_period_labels):
        # Check for a direct override first
        if label in overrides:
            out[label] = float(overrides[label])
            continue

        val: Optional[float] = None

        if method == "direct_input":
            vals = params.get("values", {})
            val = float(vals[label]) if label in vals else None

        elif method == "copy_historical":
            val = last_hist_val

        elif method == "yoy_growth":
            growth = _get_param_for_period(params.get("growth_rates", []), i)
            prior = out.get(forecast_period_labels[i - 1]) if i > 0 else last_hist_val
            if prior is not None and growth is not None:
                val = prior * (1 + growth)

        elif method == "pct_revenue_growth":
            growth = _get_param_for_period(params.get("growth_rates", []), i)
            prior = out.get(forecast_period_labels[i - 1]) if i > 0 else last_hist_val
            if prior is not None and growth is not None:
                val = prior * (1 + growth)

        elif method == "gross_margin_pct":
            margin = _get_param_for_period(params.get("margins", []), i)
            rev = revenue_by_period.get(label)
            if rev is not None and margin is not None:
                val = rev * (1 - margin)  # COGS = Rev * (1 - gross margin)

        elif method == "ebitda_margin_pct":
            margin = _get_param_for_period(params.get("margins", []), i)
            rev = revenue_by_period.get(label)
            if rev is not None and margin is not None:
                val = rev * margin

        elif method == "pct_of_revenue":
            pct = _get_param_for_period(params.get("pcts", []), i)
            rev = revenue_by_period.get(label)
            if rev is not None and pct is not None:
                val = rev * pct

        else:
            val = last_hist_val  # default: flat-line

        out[label] = round(val, 2) if val is not None else None

    return out


def _get_param_for_period(param_list: list, period_idx: int) -> Optional[float]:
    """Get the parameter value for a given period index. Last value extends forward."""
    if not param_list:
        return None
    idx = min(period_idx, len(param_list) - 1)
    v = param_list[idx]
    return float(v) if v is not None else None


def _find_revenue_concept(line_items: list[dict]) -> Optional[str]:
    """Find the primary revenue line item concept."""
    for item in line_items:
        if item.get("is_abstract"):
            continue
        if item.get("semantic_type") == "revenue":
            return item["concept"]
    # Fallback: look for "revenue" in label
    for item in line_items:
        if item.get("is_abstract"):
            continue
        label = item.get("label", "").lower()
        if "total revenue" in label or "net revenue" in label or "net sales" in label:
            return item["concept"]
    return None


def build_default_assumptions(line_items: list[dict], num_periods: int) -> list[dict]:
    """
    Build sensible default assumptions for each non-abstract line item.
    """
    assumptions = []
    for item in line_items:
        if item.get("is_abstract"):
            continue
        semantic = item.get("semantic_type", "other")
        concept = item["concept"]

        if semantic == "revenue":
            method = "pct_revenue_growth"
            params = {"growth_rates": [0.05] * num_periods}
        elif semantic == "cogs":
            method = "gross_margin_pct"
            params = {"margins": [0.40] * num_periods}
        elif semantic in ("ebitda",):
            method = "ebitda_margin_pct"
            params = {"margins": [0.25] * num_periods}
        elif semantic in ("rd_expense", "sga", "interest_expense", "tax_expense"):
            method = "pct_of_revenue"
            params = {"pcts": [0.10] * num_periods}
        elif semantic in ("da",):
            method = "pct_of_revenue"
            params = {"pcts": [0.05] * num_periods}
        else:
            method = "copy_historical"
            params = {}

        assumptions.append({
            "concept": concept,
            "method": method,
            "params": params,
            "overrides": {},
        })

    return assumptions
