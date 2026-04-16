"""
Excel builder: generates a .xlsx file for download.

Structure:
  Sheet "Financials"  - the main historical + forecast grid
  Sheet "__meta__"    - hidden, maps row_index -> concept_id for round-trip
  Custom document properties - cik, sessionId, forecastCols, version
"""
import io
from typing import Any, Optional

from openpyxl import Workbook
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    GradientFill,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter

# Colors
HEADER_HIST_BG = "1E3A5F"   # dark navy for historical headers
HEADER_FORE_BG = "1565C0"   # blue for forecast headers
HEADER_FONT = "FFFFFF"
HIST_BG = "F8F9FA"
FORE_BG = "EBF3FF"
ABSTRACT_BG = "E8EAF0"
ABSTRACT_FONT_BOLD = True
TOTAL_FONT_BOLD = True
META_SHEET = "__meta__"
EXCEL_VERSION = "1"

_thin = Side(style="thin", color="CCCCCC")
_border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def build_excel(
    company_name: str,
    cik: str,
    statement_type: str,
    columns: list[dict],          # GridColumn dicts
    rows: list[dict],             # GridRow dicts (with optional .forecast)
    session_id: Optional[str],
    forecast_period_labels: list[str],
) -> bytes:
    wb = Workbook()
    ws_fin = wb.active
    ws_fin.title = "Financials"

    # ── Header row ──────────────────────────────────────────────────────────
    ws_fin.cell(1, 1, "Line Item").font = Font(bold=True, color=HEADER_FONT)
    ws_fin.cell(1, 1).fill = PatternFill("solid", fgColor=HEADER_HIST_BG)
    ws_fin.cell(1, 1).alignment = Alignment(horizontal="left")

    col_keys = []
    for col_idx, col in enumerate(columns, start=2):
        cell = ws_fin.cell(1, col_idx, col["label"])
        is_forecast = col["type"] == "forecast"
        cell.font = Font(bold=True, color=HEADER_FONT)
        cell.fill = PatternFill(
            "solid", fgColor=FORE_BG[2:] if is_forecast else HEADER_HIST_BG
        )
        cell.fill = PatternFill(
            "solid",
            fgColor=HEADER_FORE_BG if is_forecast else HEADER_HIST_BG,
        )
        cell.alignment = Alignment(horizontal="right")
        col_keys.append(col["key"])

    # ── Data rows ────────────────────────────────────────────────────────────
    for row_idx, row in enumerate(rows, start=2):
        is_abstract = row.get("is_abstract", False)
        level = row.get("level", 1)
        indent = "  " * (level - 1)

        label_cell = ws_fin.cell(row_idx, 1, indent + row["label"])
        if is_abstract:
            label_cell.font = Font(bold=True)
            label_cell.fill = PatternFill("solid", fgColor="D0D4DC")
        else:
            label_cell.fill = PatternFill("solid", fgColor=HIST_BG)
        label_cell.alignment = Alignment(horizontal="left")

        for col_offset, col_key in enumerate(col_keys):
            cell_col = col_offset + 2
            col_meta = columns[col_offset]
            is_forecast_col = col_meta["type"] == "forecast"

            val: Optional[float] = None
            if is_forecast_col:
                forecast = row.get("forecast") or {}
                computed = forecast.get("computed", {}) or {}
                val = computed.get(col_key)
            else:
                val = row.get("values", {}).get(col_key)

            cell = ws_fin.cell(row_idx, cell_col)
            if val is not None and not is_abstract:
                cell.value = val
                cell.number_format = '#,##0;(#,##0);"-"'

            if is_abstract:
                cell.fill = PatternFill("solid", fgColor="D0D4DC")
            elif is_forecast_col:
                cell.fill = PatternFill("solid", fgColor="EBF3FF")
                cell.protection = None  # editable
            else:
                cell.fill = PatternFill("solid", fgColor=HIST_BG)

            cell.alignment = Alignment(horizontal="right")
            cell.border = _border

    # Column widths
    ws_fin.column_dimensions["A"].width = 36
    for i in range(2, len(col_keys) + 2):
        ws_fin.column_dimensions[get_column_letter(i)].width = 14

    # Freeze panes: freeze the label column and header row
    ws_fin.freeze_panes = "B2"

    # ── Meta sheet ───────────────────────────────────────────────────────────
    ws_meta = wb.create_sheet(META_SHEET)
    ws_meta.sheet_state = "hidden"

    # Header
    ws_meta["A1"] = "row_index"
    ws_meta["B1"] = "concept_id"
    ws_meta["C1"] = "semantic_type"
    ws_meta["D1"] = "is_forecast_input"

    for row_idx, row in enumerate(rows, start=2):
        ws_meta.cell(row_idx, 1, row_idx)
        ws_meta.cell(row_idx, 2, row["row_id"])
        ws_meta.cell(row_idx, 3, row.get("semantic_type", "other"))
        ws_meta.cell(row_idx, 4, not row.get("is_abstract", False))

    # Metadata in a special area
    ws_meta["F1"] = "cik"
    ws_meta["G1"] = cik
    ws_meta["F2"] = "session_id"
    ws_meta["G2"] = session_id or ""
    ws_meta["F3"] = "company_name"
    ws_meta["G3"] = company_name
    ws_meta["F4"] = "statement_type"
    ws_meta["G4"] = statement_type
    ws_meta["F5"] = "forecast_cols"
    ws_meta["G5"] = ",".join(forecast_period_labels)
    ws_meta["F6"] = "version"
    ws_meta["G6"] = EXCEL_VERSION
    ws_meta["F7"] = "hist_cols"
    ws_meta["G7"] = ",".join(
        col["key"] for col in columns if col["type"] == "historical"
    )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
