"""
Excel parser: reads an uploaded .xlsx back and extracts forecast overrides.

Reads the hidden __meta__ sheet to map row indices → concept_ids,
then compares cell values to last saved computed values to detect overrides.
"""
import io
from typing import Any, Optional

from openpyxl import load_workbook

META_SHEET = "__meta__"
EXCEL_VERSION = "1"


class ExcelParseError(ValueError):
    pass


def parse_uploaded_excel(
    content: bytes,
    expected_cik: Optional[str] = None,
) -> dict:
    """
    Parse an uploaded Excel file.

    Returns:
    {
        cik: str,
        session_id: str | None,
        company_name: str,
        statement_type: str,
        forecast_cols: [str],
        hist_cols: [str],
        version: str,
        # rows: [{concept_id, is_forecast_input, values: {col_key: value}}]
        rows: [...]
    }
    """
    wb = load_workbook(io.BytesIO(content), data_only=True)

    if META_SHEET not in wb.sheetnames:
        raise ExcelParseError(
            "The uploaded file is missing the metadata sheet (__meta__). "
            "Please use a file downloaded from this application."
        )

    ws_meta = wb[META_SHEET]

    # Read metadata from F/G columns
    meta: dict[str, str] = {}
    for row in ws_meta.iter_rows(min_row=1, max_row=20, min_col=6, max_col=7):
        if row[0].value and row[1].value is not None:
            meta[str(row[0].value)] = str(row[1].value)

    cik = meta.get("cik", "")
    session_id = meta.get("session_id") or None
    company_name = meta.get("company_name", "")
    statement_type = meta.get("statement_type", "income_statement")
    forecast_cols_str = meta.get("forecast_cols", "")
    hist_cols_str = meta.get("hist_cols", "")
    version = meta.get("version", "1")

    if version != EXCEL_VERSION:
        raise ExcelParseError(
            f"Unsupported Excel version '{version}'. Please re-download the file."
        )

    if expected_cik and cik.zfill(10) != expected_cik.zfill(10):
        raise ExcelParseError(
            f"CIK mismatch: file is for company {cik}, but upload was to {expected_cik}."
        )

    forecast_cols = [c.strip() for c in forecast_cols_str.split(",") if c.strip()]
    hist_cols = [c.strip() for c in hist_cols_str.split(",") if c.strip()]

    if not forecast_cols:
        raise ExcelParseError("No forecast columns found in metadata.")

    # Build row_index → {concept_id, semantic_type, is_forecast_input}
    row_map: dict[int, dict] = {}
    for row in ws_meta.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            break
        row_idx = int(row[0])
        row_map[row_idx] = {
            "concept_id": str(row[1]) if row[1] else "",
            "semantic_type": str(row[2]) if row[2] else "other",
            "is_forecast_input": bool(row[3]) if row[3] is not None else True,
        }

    # Read the Financials sheet
    ws_fin = wb.active if "Financials" not in wb.sheetnames else wb["Financials"]

    # Read header row to map column index → period key
    col_key_map: dict[int, str] = {}
    all_col_keys = hist_cols + forecast_cols
    for col_idx, cell in enumerate(ws_fin[1], start=1):
        if col_idx == 1:
            continue  # label column
        col_offset = col_idx - 2  # 0-based index into all columns
        if col_offset < len(all_col_keys):
            col_key_map[col_idx] = all_col_keys[col_offset]

    # Read data rows
    parsed_rows = []
    for row_idx_excel, row in enumerate(ws_fin.iter_rows(min_row=2, values_only=True), start=2):
        if row_idx_excel not in row_map:
            continue
        meta_row = row_map[row_idx_excel]
        if not meta_row["is_forecast_input"]:
            continue

        values: dict[str, Any] = {}
        for col_idx, val in enumerate(row, start=1):
            col_key = col_key_map.get(col_idx)
            if col_key and col_key in forecast_cols and val is not None:
                try:
                    values[col_key] = float(val)
                except (TypeError, ValueError):
                    pass

        parsed_rows.append({
            "concept_id": meta_row["concept_id"],
            "semantic_type": meta_row["semantic_type"],
            "values": values,
        })

    return {
        "cik": cik,
        "session_id": session_id,
        "company_name": company_name,
        "statement_type": statement_type,
        "forecast_cols": forecast_cols,
        "hist_cols": hist_cols,
        "version": version,
        "rows": parsed_rows,
    }


def extract_overrides(
    parsed_rows: list[dict],
    current_forecast_values: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    Compare uploaded values against current computed forecast values.
    Any cell that differs is treated as a direct override.

    Returns: {concept: {period_label: override_value}}
    """
    overrides: dict[str, dict[str, Any]] = {}

    for row in parsed_rows:
        concept = row["concept_id"]
        uploaded_vals = row["values"]
        computed_vals = current_forecast_values.get(concept, {})

        row_overrides: dict[str, Any] = {}
        for period_label, uploaded_val in uploaded_vals.items():
            computed_val = computed_vals.get(period_label)
            if computed_val is None:
                # New value where there was none
                row_overrides[period_label] = uploaded_val
            elif abs(float(uploaded_val) - float(computed_val)) > 0.01:
                # User changed the value
                row_overrides[period_label] = uploaded_val

        if row_overrides:
            overrides[concept] = row_overrides

    return overrides
