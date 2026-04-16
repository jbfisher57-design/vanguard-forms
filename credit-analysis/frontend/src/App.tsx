import React, { Suspense, lazy, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CompanySearch } from "./components/CompanySearch/CompanySearch";
import { FinancialGrid } from "./components/FinancialGrid/FinancialGrid";
import { ForecastMethodPanel } from "./components/FinancialGrid/ForecastMethodPanel";
import { DebtSchedule } from "./components/DebtSchedule/DebtSchedule";
import { ExcelPanel } from "./components/ExcelPanel/ExcelPanel";
import { GridSkeleton, SpinnerOverlay } from "./components/common/LoadingSkeleton";
import { LoginPage } from "./components/common/AuthPages";
import { useAuthStore } from "./store/authStore";
import { useForecastStore } from "./store/forecastStore";
import { getCompany } from "./api/companies";
import { getFinancials, type StatementType, type FormType } from "./api/financials";
import {
  listForecasts,
  createForecast,
  updateForecast,
  type ForecastPeriod,
} from "./api/forecasts";
import { logout } from "./api/auth";
import type { CompanySearchResult } from "./api/companies";

type TabType = "income_statement" | "balance_sheet" | "cash_flow" | "debt";

const TAB_LABELS: Record<TabType, string> = {
  income_statement: "Income Statement",
  balance_sheet: "Balance Sheet",
  cash_flow: "Cash Flow",
  debt: "Debt Schedule",
};

export default function App() {
  const { isAuthenticated, setToken } = useAuthStore();
  const queryClient = useQueryClient();

  const [selectedCompany, setSelectedCompany] = useState<CompanySearchResult | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>("income_statement");
  const [formType, setFormType] = useState<FormType>("10-K");
  const [periods, setPeriods] = useState(5);
  const [forecastPanelOpen, setForecastPanelOpen] = useState(false);
  const [forecastSessionName, setForecastSessionName] = useState("Base Case");

  const {
    activeSession,
    setActiveSession,
    isDirty,
    setDirty,
    selectedRowConcept,
  } = useForecastStore();

  if (!isAuthenticated()) {
    return <LoginPage />;
  }

  const cik = selectedCompany?.cik ?? "";

  // ── Data queries ──────────────────────────────────────────────────────────
  const { data: companyDetail } = useQuery({
    queryKey: ["company", cik],
    queryFn: () => getCompany(cik),
    enabled: !!cik,
  });

  const financialStatement: StatementType =
    activeTab === "debt" ? "income_statement" : activeTab;

  const {
    data: financialsData,
    isLoading: financialsLoading,
    error: financialsError,
  } = useQuery({
    queryKey: ["financials", cik, financialStatement, periods, formType],
    queryFn: () => getFinancials(cik, financialStatement, periods, formType),
    enabled: !!cik && activeTab !== "debt",
    staleTime: 5 * 60 * 1000,
  });

  const { data: forecastSessions } = useQuery({
    queryKey: ["forecasts", cik],
    queryFn: () => listForecasts(cik),
    enabled: !!cik,
  });

  // ── Mutations ─────────────────────────────────────────────────────────────
  const createForecastMutation = useMutation({
    mutationFn: async () => {
      if (!companyDetail || !financialsData) return;
      const latestPeriod = companyDetail.available_periods.find(
        (p) => p.form_type === formType
      );
      if (!latestPeriod) return;

      const baseYear = new Date(latestPeriod.period_end).getFullYear();
      const forecastPeriods: ForecastPeriod[] = [1, 2, 3].map((n) => ({
        label: `${baseYear + n}E`,
        period_end: `${baseYear + n}-12-31`,
      }));

      const basePeriods = financialsData.columns
        .filter((c) => c.type === "historical")
        .map((c) => c.key);

      return createForecast(cik, {
        name: forecastSessionName,
        statement_type: financialStatement,
        base_filing_id: latestPeriod.filing_id,
        base_period_ends: basePeriods,
        forecast_periods: forecastPeriods,
      });
    },
    onSuccess: (session) => {
      if (session) {
        setActiveSession(session);
        queryClient.invalidateQueries({ queryKey: ["forecasts", cik] });
      }
    },
  });

  const saveForecastMutation = useMutation({
    mutationFn: async () => {
      if (!activeSession) return;
      return updateForecast(cik, activeSession.id, {
        assumptions: activeSession.assumptions,
        forecast_periods: activeSession.forecast_periods,
      });
    },
    onSuccess: (session) => {
      if (session) {
        setActiveSession(session);
        setDirty(false);
      }
    },
  });

  const handleLogout = async () => {
    await logout();
    setToken(null);
  };

  const forecastValues = activeSession?.forecast_values;
  const forecastPeriodCols = (activeSession?.forecast_periods ?? []).map((p) => ({
    key: p.label,
    label: p.label,
    period_end: p.period_end,
    type: "forecast" as const,
  }));

  const combinedGrid = financialsData
    ? {
        ...financialsData,
        columns: [
          ...financialsData.columns,
          ...forecastPeriodCols.filter(
            (fc) => !financialsData.columns.find((hc) => hc.key === fc.key)
          ),
        ],
      }
    : null;

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* ── Top navigation ── */}
      <header className="bg-navy text-white px-6 py-3 flex items-center gap-4 shadow-md">
        <div className="font-bold text-lg tracking-tight">Credit Analysis</div>
        <div className="flex-1">
          <CompanySearch onSelect={setSelectedCompany} />
        </div>
        <button
          onClick={handleLogout}
          className="text-blue-200 hover:text-white text-sm transition-colors"
        >
          Sign out
        </button>
      </header>

      {!selectedCompany ? (
        <div className="flex-1 flex items-center justify-center text-gray-400">
          <div className="text-center">
            <div className="text-4xl mb-4">📊</div>
            <div className="text-lg font-medium text-gray-600 mb-1">
              Search for any SEC-reporting company
            </div>
            <div className="text-sm">
              Enter a company name or ticker to load financials
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col">
          {/* ── Company header ── */}
          <div className="bg-white border-b border-gray-200 px-6 py-3">
            <div className="flex items-center gap-3">
              {selectedCompany.ticker && (
                <span className="font-mono font-bold text-blue-700 bg-blue-50 px-2 py-1 rounded text-sm">
                  {selectedCompany.ticker}
                </span>
              )}
              <h1 className="font-bold text-navy text-lg">{selectedCompany.name}</h1>
              {companyDetail?.sic_description && (
                <span className="text-xs text-gray-400">— {companyDetail.sic_description}</span>
              )}
              <div className="ml-auto flex items-center gap-3">
                {/* Form type toggle */}
                <div className="flex rounded-lg overflow-hidden border border-gray-300 text-xs">
                  {(["10-K", "10-Q"] as FormType[]).map((ft) => (
                    <button
                      key={ft}
                      onClick={() => setFormType(ft)}
                      className={`px-3 py-1.5 font-medium transition-colors ${
                        formType === ft
                          ? "bg-navy text-white"
                          : "bg-white text-gray-600 hover:bg-gray-50"
                      }`}
                    >
                      {ft}
                    </button>
                  ))}
                </div>
                {/* Period selector */}
                <div className="flex items-center gap-1.5 text-xs text-gray-600">
                  <span>Periods:</span>
                  <select
                    value={periods}
                    onChange={(e) => setPeriods(Number(e.target.value))}
                    className="border border-gray-300 rounded px-2 py-1 text-xs focus:outline-none"
                  >
                    {[3, 4, 5, 7, 10].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {/* ── Statement tabs ── */}
            <div className="flex gap-0 mt-3 border-b border-gray-100">
              {(Object.keys(TAB_LABELS) as TabType[]).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === tab
                      ? "border-blue-600 text-blue-700"
                      : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {TAB_LABELS[tab]}
                </button>
              ))}
            </div>
          </div>

          {/* ── Main content ── */}
          <div className="flex-1 px-6 py-4 overflow-hidden">
            {activeTab === "debt" ? (
              <DebtSchedule cik={cik} />
            ) : (
              <>
                {/* Forecast toolbar */}
                <div className="flex items-center gap-3 mb-3 flex-wrap">
                  {!activeSession ? (
                    <>
                      <input
                        value={forecastSessionName}
                        onChange={(e) => setForecastSessionName(e.target.value)}
                        className="border border-gray-300 rounded px-2 py-1.5 text-sm w-40
                                   focus:outline-none focus:ring-1 focus:ring-blue-500"
                        placeholder="Session name"
                      />
                      <button
                        onClick={() => createForecastMutation.mutate()}
                        disabled={createForecastMutation.isPending || !financialsData}
                        className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm
                                   font-medium rounded-lg disabled:bg-gray-300 transition-colors"
                      >
                        + Add Forecast
                      </button>
                      {forecastSessions && forecastSessions.length > 0 && (
                        <select
                          onChange={(e) => {
                            const s = forecastSessions.find((fs) => fs.id === e.target.value);
                            if (s) setActiveSession(s);
                          }}
                          className="border border-gray-300 rounded px-2 py-1.5 text-sm
                                     focus:outline-none"
                          defaultValue=""
                        >
                          <option value="" disabled>
                            Load saved session…
                          </option>
                          {forecastSessions.map((s) => (
                            <option key={s.id} value={s.id}>
                              {s.name}
                            </option>
                          ))}
                        </select>
                      )}
                    </>
                  ) : (
                    <>
                      <span className="text-sm font-semibold text-navy">
                        {activeSession.name}
                      </span>
                      {isDirty && (
                        <button
                          onClick={() => saveForecastMutation.mutate()}
                          disabled={saveForecastMutation.isPending}
                          className="px-3 py-1.5 bg-green-700 hover:bg-green-800 text-white text-xs
                                     font-medium rounded-lg transition-colors"
                        >
                          {saveForecastMutation.isPending ? "Saving…" : "Save"}
                        </button>
                      )}
                      <button
                        onClick={() => setActiveSession(null)}
                        className="px-3 py-1.5 border border-gray-300 text-gray-600 text-xs
                                   font-medium rounded-lg hover:bg-gray-100"
                      >
                        Close
                      </button>
                      <div className="ml-auto">
                        <ExcelPanel
                          cik={cik}
                          sessionId={activeSession.id}
                          onUploadComplete={(sid) => {
                            queryClient.invalidateQueries({
                              queryKey: ["forecasts", cik],
                            });
                          }}
                        />
                      </div>
                    </>
                  )}
                </div>

                {/* Financial grid */}
                {financialsLoading ? (
                  <GridSkeleton />
                ) : financialsError ? (
                  <div className="py-8 text-center text-red-500 text-sm">
                    Could not load financials. Please try again.
                  </div>
                ) : combinedGrid ? (
                  <FinancialGrid
                    data={combinedGrid}
                    forecastValues={forecastValues}
                    onRowClick={(rowId) => {
                      if (activeSession) setForecastPanelOpen(true);
                    }}
                  />
                ) : null}
              </>
            )}
          </div>
        </div>
      )}

      {/* Forecast method side panel */}
      {activeSession && (
        <ForecastMethodPanel
          isOpen={forecastPanelOpen && !!selectedRowConcept}
          onClose={() => setForecastPanelOpen(false)}
          forecastPeriods={activeSession.forecast_periods}
        />
      )}
    </div>
  );
}
