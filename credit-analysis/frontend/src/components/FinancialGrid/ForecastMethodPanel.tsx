import React from "react";
import { FORECAST_METHODS, type ForecastMethodValue } from "../../utils/constants";
import { useForecastStore } from "../../store/forecastStore";
import type { AssumptionRow } from "../../api/forecasts";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  forecastPeriods: { label: string }[];
}

export function ForecastMethodPanel({ isOpen, onClose, forecastPeriods }: Props) {
  const { activeSession, selectedRowConcept, updateAssumption } = useForecastStore();

  if (!isOpen || !selectedRowConcept || !activeSession) return null;

  const assumption = activeSession.assumptions.find((a) => a.concept === selectedRowConcept);
  if (!assumption) return null;

  const method = assumption.method as ForecastMethodValue;
  const params = assumption.params as Record<string, unknown>;

  const handleMethodChange = (newMethod: string) => {
    updateAssumption(selectedRowConcept, {
      method: newMethod,
      params: _defaultParams(newMethod as ForecastMethodValue, forecastPeriods.length),
      overrides: {},
    });
  };

  const handleParamChange = (paramKey: string, periodIdx: number, value: string) => {
    const numVal = parseFloat(value);
    if (isNaN(numVal)) return;
    const arr = [...((params[paramKey] as number[]) || Array(forecastPeriods.length).fill(0))];
    arr[periodIdx] = numVal / 100; // convert pct to decimal
    updateAssumption(selectedRowConcept, {
      params: { ...params, [paramKey]: arr },
    });
  };

  const handleDirectInputChange = (periodLabel: string, value: string) => {
    const numVal = parseFloat(value.replace(/,/g, ""));
    const vals = { ...((params["values"] as Record<string, number>) || {}) };
    if (!isNaN(numVal)) vals[periodLabel] = numVal;
    updateAssumption(selectedRowConcept, { params: { ...params, values: vals } });
  };

  const rowData = activeSession.assumptions.find((a) => a.concept === selectedRowConcept);
  const conceptLabel =
    activeSession.forecast_values && selectedRowConcept
      ? selectedRowConcept.split(":")[1] || selectedRowConcept
      : "Row";

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white shadow-2xl z-50 flex flex-col border-l border-gray-200">
      <div className="flex items-center justify-between px-5 py-4 bg-navy text-white">
        <div>
          <div className="text-xs text-blue-200 mb-0.5">Forecast Method</div>
          <div className="font-semibold text-sm truncate max-w-[280px]">{conceptLabel}</div>
        </div>
        <button onClick={onClose} className="text-blue-200 hover:text-white text-xl font-bold">
          ×
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* Method selector */}
        <div>
          <label className="block text-xs font-semibold text-gray-600 mb-2 uppercase tracking-wide">
            Projection Method
          </label>
          <div className="space-y-1.5">
            {FORECAST_METHODS.map((m) => (
              <label key={m.value} className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="radio"
                  name="forecast_method"
                  value={m.value}
                  checked={method === m.value}
                  onChange={() => handleMethodChange(m.value)}
                  className="accent-blue-600"
                />
                <span className="text-sm text-gray-700">{m.label}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Parameter inputs */}
        {method !== "copy_historical" && method !== "direct_input" && (
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-2 uppercase tracking-wide">
              {_paramLabel(method)}
            </label>
            <div className="space-y-2">
              {forecastPeriods.map((period, idx) => {
                const paramKey = _paramKey(method);
                const arr = (params[paramKey] as number[]) || [];
                const val = arr[idx] ?? 0;
                return (
                  <div key={period.label} className="flex items-center gap-2">
                    <span className="text-xs text-gray-500 w-14 shrink-0">{period.label}</span>
                    <div className="relative flex-1">
                      <input
                        type="number"
                        step="0.1"
                        value={(val * 100).toFixed(1)}
                        onChange={(e) => handleParamChange(paramKey, idx, e.target.value)}
                        className="w-full border border-gray-300 rounded px-2 py-1 text-sm text-right pr-6
                                   focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                      <span className="absolute right-2 top-1.5 text-gray-400 text-xs">%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {method === "direct_input" && (
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-2 uppercase tracking-wide">
              Direct Values
            </label>
            <div className="space-y-2">
              {forecastPeriods.map((period) => {
                const vals = (params["values"] as Record<string, number>) || {};
                return (
                  <div key={period.label} className="flex items-center gap-2">
                    <span className="text-xs text-gray-500 w-14 shrink-0">{period.label}</span>
                    <input
                      type="number"
                      value={vals[period.label] ?? ""}
                      onChange={(e) => handleDirectInputChange(period.label, e.target.value)}
                      placeholder="Enter value"
                      className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm text-right
                                 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Overrides summary */}
        {rowData && Object.keys(rowData.overrides || {}).length > 0 && (
          <div>
            <div className="text-xs font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
              {Object.keys(rowData.overrides).length} override(s) applied from Excel upload.
              <button
                className="ml-2 underline"
                onClick={() => updateAssumption(selectedRowConcept, { overrides: {} })}
              >
                Clear
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="px-5 py-4 border-t border-gray-200 bg-gray-50">
        <button
          onClick={onClose}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white rounded-lg py-2 text-sm font-semibold transition-colors"
        >
          Apply
        </button>
      </div>
    </div>
  );
}

function _paramLabel(method: string): string {
  switch (method) {
    case "pct_revenue_growth":
    case "yoy_growth":
      return "Growth Rate (% per period)";
    case "gross_margin_pct":
      return "Gross Margin (%)";
    case "ebitda_margin_pct":
      return "EBITDA Margin (%)";
    case "pct_of_revenue":
      return "As % of Revenue";
    default:
      return "Parameter";
  }
}

function _paramKey(method: string): string {
  switch (method) {
    case "pct_revenue_growth":
    case "yoy_growth":
      return "growth_rates";
    case "gross_margin_pct":
    case "ebitda_margin_pct":
      return "margins";
    case "pct_of_revenue":
      return "pcts";
    default:
      return "values";
  }
}

function _defaultParams(method: ForecastMethodValue, numPeriods: number): Record<string, unknown> {
  switch (method) {
    case "pct_revenue_growth":
    case "yoy_growth":
      return { growth_rates: Array(numPeriods).fill(0.05) };
    case "gross_margin_pct":
    case "ebitda_margin_pct":
      return { margins: Array(numPeriods).fill(0.35) };
    case "pct_of_revenue":
      return { pcts: Array(numPeriods).fill(0.10) };
    default:
      return {};
  }
}
