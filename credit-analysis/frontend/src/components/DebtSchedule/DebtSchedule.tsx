import React from "react";
import { useQuery } from "@tanstack/react-query";
import { getDebtSchedule, type DebtInstrument } from "../../api/debt";
import { formatValue, formatDate, formatCoupon } from "../../utils/formatters";
import { SENIORITY_LABELS, SENIORITY_COLORS, INSTRUMENT_TYPE_LABELS } from "../../utils/constants";

interface Props {
  cik: string;
}

const DOC_TYPE_LABELS: Record<string, string> = {
  prospectus: "Prosp.",
  indenture: "Indent.",
  "8-K": "8-K",
  "10-K_note": "10-K",
  "S-3": "S-3",
  credit_agreement: "Credit Agmt",
};

export function DebtSchedule({ cik }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["debt", cik],
    queryFn: () => getDebtSchedule(cik),
    staleTime: 12 * 60 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="py-8 text-center text-gray-400 text-sm">
        <div className="w-6 h-6 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
        Extracting debt instruments from filing...
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-6 text-center text-red-500 text-sm">
        Could not load debt schedule. Load financials first.
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="py-6 text-center text-gray-400 text-sm">
        No debt instruments found for this company.
      </div>
    );
  }

  const totalDebt = data.reduce((sum, inst) => sum + (inst.principal_amount || 0), 0);

  return (
    <div className="mt-2">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-navy text-sm">
          Debt Schedule — {data.length} instrument{data.length !== 1 ? "s" : ""}
        </h3>
        <span className="text-sm font-mono text-gray-600">
          Total: {formatValue(totalDebt)}
        </span>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-navy-light text-white">
              <th className="text-left px-3 py-2.5 font-semibold">Instrument</th>
              <th className="text-left px-3 py-2.5 font-semibold">Type</th>
              <th className="text-left px-3 py-2.5 font-semibold">Seniority</th>
              <th className="text-right px-3 py-2.5 font-semibold">Amount</th>
              <th className="text-right px-3 py-2.5 font-semibold">Rate</th>
              <th className="text-right px-3 py-2.5 font-semibold">Maturity</th>
              <th className="text-center px-3 py-2.5 font-semibold">Filing</th>
            </tr>
          </thead>
          <tbody>
            {data.map((inst, i) => (
              <DebtRow key={inst.id} inst={inst} isEven={i % 2 === 0} />
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-gray-100 font-semibold border-t border-gray-300">
              <td className="px-3 py-2 text-left" colSpan={3}>
                Total Debt
              </td>
              <td className="px-3 py-2 text-right font-mono">{formatValue(totalDebt)}</td>
              <td colSpan={3} />
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="text-xs text-gray-400 mt-2">
        Debt instruments extracted from SEC filings. Click filing badges to view source documents.
        Low-confidence extractions shown with ⚠.
      </p>
    </div>
  );
}

function DebtRow({ inst, isEven }: { inst: DebtInstrument; isEven: boolean }) {
  const seniority = inst.seniority || "senior_unsecured";
  const seniorityClass = SENIORITY_COLORS[seniority] || "bg-gray-100 text-gray-600";
  const docLabel =
    inst.originating_doc_type
      ? DOC_TYPE_LABELS[inst.originating_doc_type] || inst.originating_doc_type
      : null;

  return (
    <tr className={`border-b border-gray-100 hover:bg-blue-50 ${isEven ? "bg-white" : "bg-gray-50"}`}>
      <td className="px-3 py-2 max-w-[240px]">
        <div className="flex items-center gap-1.5">
          {inst.confidence_score < 0.85 && (
            <span title="Low-confidence extraction — verify against filing" className="text-amber-500">
              ⚠
            </span>
          )}
          <span className="truncate font-medium text-gray-800">{inst.instrument_name}</span>
        </div>
      </td>
      <td className="px-3 py-2 text-gray-600">
        {INSTRUMENT_TYPE_LABELS[inst.instrument_type || "other"] || inst.instrument_type || "—"}
      </td>
      <td className="px-3 py-2">
        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${seniorityClass}`}>
          {SENIORITY_LABELS[seniority] || seniority}
        </span>
      </td>
      <td className="px-3 py-2 text-right font-mono text-gray-800">
        {formatValue(inst.principal_amount)}
      </td>
      <td className="px-3 py-2 text-right font-mono text-gray-700">
        {formatCoupon(inst.coupon_rate, inst.coupon_type, inst.floating_benchmark, inst.floating_spread)}
      </td>
      <td className="px-3 py-2 text-right text-gray-600">
        {formatDate(inst.maturity_date)}
      </td>
      <td className="px-3 py-2 text-center">
        {inst.originating_doc_url && docLabel ? (
          <a
            href={inst.originating_doc_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block px-2 py-0.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded font-medium transition-colors"
          >
            {docLabel}
          </a>
        ) : (
          <span className="text-gray-300">—</span>
        )}
      </td>
    </tr>
  );
}
