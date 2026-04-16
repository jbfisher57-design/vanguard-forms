import React, { useCallback, useMemo, useRef } from "react";
import { AgGridReact } from "@ag-grid-community/react";
import {
  ClientSideRowModelModule,
  ModuleRegistry,
  type ColDef,
  type GridReadyEvent,
} from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-alpine.css";
import type { FinancialGrid as FinancialGridData } from "../../api/financials";
import { formatValue } from "../../utils/formatters";
import { useForecastStore } from "../../store/forecastStore";

ModuleRegistry.registerModules([ClientSideRowModelModule]);

interface Props {
  data: FinancialGridData;
  forecastValues?: Record<string, Record<string, number | null>>;
  onRowClick?: (rowId: string) => void;
}

function LabelCellRenderer({ value, data }: { value: string; data: Record<string, unknown> }) {
  const level = (data.level as number) || 1;
  const isAbstract = data.is_abstract as boolean;
  const paddingLeft = (level - 1) * 16;

  return (
    <div
      style={{ paddingLeft }}
      className={`flex items-center h-full ${isAbstract ? "font-semibold text-navy" : "text-gray-700"}`}
    >
      {value}
    </div>
  );
}

function ValueCellRenderer({
  value,
  data,
  colDef,
}: {
  value: unknown;
  data: Record<string, unknown>;
  colDef: ColDef;
}) {
  const isAbstract = data.is_abstract as boolean;
  if (isAbstract) return null;

  const colKey = (colDef as ColDef & { colKey?: string }).colKey;
  const isForecast = (colDef as ColDef & { isForecast?: boolean }).isForecast;

  // Check for override
  const forecastData = data.forecast as { computed?: Record<string, number | null> } | undefined;
  const isOverride =
    isForecast &&
    colKey &&
    forecastData?.computed?.[colKey] !== undefined &&
    value !== forecastData?.computed?.[colKey];

  const num = typeof value === "number" ? value : null;

  return (
    <div
      className={`h-full flex items-center justify-end font-mono text-right pr-2 ${
        isForecast ? "text-blue-700" : "text-gray-800"
      }`}
    >
      {formatValue(num)}
      {isOverride && <span className="override-indicator ml-1">✎</span>}
    </div>
  );
}

export function FinancialGrid({ data, forecastValues, onRowClick }: Props) {
  const gridRef = useRef<AgGridReact>(null);
  const setSelectedRowConcept = useForecastStore((s) => s.setSelectedRowConcept);

  const columnDefs = useMemo<ColDef[]>(() => {
    const cols: ColDef[] = [
      {
        field: "label",
        headerName: "Line Item",
        pinned: "left",
        width: 280,
        cellRenderer: LabelCellRenderer,
        headerClass: "bg-navy-light text-white",
        cellClass: (params) =>
          params.data.is_abstract ? "abstract-row bg-gray-100" : "bg-white",
        suppressMovable: true,
      },
    ];

    for (const col of data.columns) {
      const isHistorical = col.type === "historical";
      cols.push({
        field: `values.${col.key}`,
        headerName: col.label,
        width: 130,
        headerClass: isHistorical ? "hist-header" : "forecast-header",
        cellRenderer: ValueCellRenderer,
        cellRendererParams: {
          colKey: col.key,
          isForecast: !isHistorical,
        },
        cellClass: (params) => {
          const classes = ["value-cell"];
          if (params.data.is_abstract) classes.push("abstract-row");
          else if (!isHistorical) classes.push("forecast-cell");
          return classes.join(" ");
        },
        valueGetter: (params) => {
          if (!isHistorical) {
            const session = forecastValues;
            return session?.[params.data.row_id]?.[col.key] ?? null;
          }
          return params.data.values?.[col.key] ?? null;
        },
        type: "numericColumn",
      } as ColDef & { colKey?: string; isForecast?: boolean });
    }

    return cols;
  }, [data.columns, forecastValues]);

  const rowData = useMemo(
    () =>
      data.rows.map((row) => ({
        ...row,
        // flatten values for AG Grid field access
        values: row.values,
      })),
    [data.rows]
  );

  const onGridReady = useCallback((e: GridReadyEvent) => {
    e.api.sizeColumnsToFit();
  }, []);

  const onRowClicked = useCallback(
    (e: { data: { row_id: string; is_abstract: boolean } }) => {
      if (!e.data.is_abstract) {
        setSelectedRowConcept(e.data.row_id);
        onRowClick?.(e.data.row_id);
      }
    },
    [onRowClick, setSelectedRowConcept]
  );

  const getRowClass = useCallback(
    (params: { data: { is_abstract: boolean } }) =>
      params.data.is_abstract ? "abstract-row" : "",
    []
  );

  return (
    <div className="ag-theme-alpine w-full" style={{ height: "calc(100vh - 280px)" }}>
      <AgGridReact
        ref={gridRef}
        columnDefs={columnDefs}
        rowData={rowData}
        onGridReady={onGridReady}
        onRowClicked={onRowClicked}
        getRowClass={getRowClass}
        rowHeight={32}
        headerHeight={38}
        animateRows={false}
        suppressColumnVirtualisation={false}
        enableCellTextSelection={true}
        defaultColDef={{
          resizable: true,
          sortable: false,
          filter: false,
        }}
      />
    </div>
  );
}
