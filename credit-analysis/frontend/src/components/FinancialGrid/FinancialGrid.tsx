import React, { useMemo } from "react";
import type { FinancialGrid as FinancialGridData } from "../../api/financials";
import { formatValue } from "../../utils/formatters";
import { useForecastStore } from "../../store/forecastStore";

interface Props {
  data: FinancialGridData;
  forecastValues?: Record<string, Record<string, number | null>>;
  onRowClick?: (rowId: string) => void;
}

export function FinancialGrid({ data, forecastValues, onRowClick }: Props) {
  const setSelectedRowConcept = useForecastStore((s) => s.setSelectedRowConcept);

  const columns = useMemo(() => data.columns, [data.columns]);
  const rows = useMemo(() => data.rows, [data.rows]);

  const handleRowClick = (rowId: string, isAbstract: boolean) => {
    if (!isAbstract) {
      setSelectedRowConcept(rowId);
      onRowClick?.(rowId);
    }
  };

  return (
    <div className="w-full overflow-auto" style={{ height: "calc(100vh - 290px)" }}>
      <table className="border-collapse text-sm w-full" style={{ minWidth: 600 }}>
        <thead>
          <tr>
            <th
              className="sticky left-0 z-20 text-left px-3 py-2 font-semibold text-white text-xs whitespace-nowrap"
              style={{ background: "#1e3a5f", minWidth: 260, width: 260 }}
            >
              <span>Line Item</span>
              {data.unit && data.unit !== "USD" && (
                <span className="ml-2 font-normal text-blue-200 text-xs">
                  ({data.unit})
                </span>
              )}
            </th>
            {columns.map((col) => (
              <th
                key={col.key}
                className="text-right px-3 py-2 font-semibold text-white text-xs whitespace-nowrap"
                style={{
                  background: col.type === "forecast" ? "#1565c0" : "#1e3a5f",
                  minWidth: 110,
                  width: 110,
                }}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const paddingLeft = (row.level - 1) * 16 + 12;
            const isAbstract = row.is_abstract;

            return (
              <tr
                key={row.row_id}
                onClick={() => handleRowClick(row.row_id, isAbstract)}
                className={[
                  isAbstract
                    ? "bg-slate-100 font-semibold"
                    : i % 2 === 0
                    ? "bg-white hover:bg-blue-50 cursor-pointer"
                    : "bg-gray-50 hover:bg-blue-50 cursor-pointer",
                ].join(" ")}
              >
                <td
                  className="sticky left-0 z-10 border-b border-gray-100 py-1 text-xs whitespace-nowrap overflow-hidden text-ellipsis"
                  style={{
                    paddingLeft,
                    paddingRight: 12,
                    maxWidth: 260,
                    background: isAbstract ? "#e8eaf0" : i % 2 === 0 ? "#fff" : "#f9fafb",
                    color: isAbstract ? "#1e3a5f" : "#374151",
                  }}
                  title={row.label}
                >
                  {row.label}
                </td>
                {columns.map((col) => {
                  const rawVal =
                    col.type === "forecast"
                      ? forecastValues?.[row.row_id]?.[col.key] ?? null
                      : (row.values?.[col.key] ?? null);
                  const num = typeof rawVal === "number" ? rawVal : null;

                  return (
                    <td
                      key={col.key}
                      className="border-b border-gray-100 py-1 px-3 text-right font-mono text-xs whitespace-nowrap"
                      style={{
                        color: col.type === "forecast" ? "#1d4ed8" : "#1f2937",
                        background:
                          col.type === "forecast"
                            ? "#ebf3ff"
                            : isAbstract
                            ? "#e8eaf0"
                            : undefined,
                      }}
                    >
                      {isAbstract ? "" : formatValue(num)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
