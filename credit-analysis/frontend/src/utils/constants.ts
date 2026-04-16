export const FORECAST_METHODS = [
  { value: "pct_revenue_growth", label: "% Revenue Growth" },
  { value: "gross_margin_pct", label: "Gross Margin %" },
  { value: "ebitda_margin_pct", label: "EBITDA Margin %" },
  { value: "pct_of_revenue", label: "% of Revenue" },
  { value: "direct_input", label: "Direct Input" },
  { value: "copy_historical", label: "Flat / Copy Historical" },
  { value: "yoy_growth", label: "YoY Growth %" },
] as const;

export type ForecastMethodValue = (typeof FORECAST_METHODS)[number]["value"];

export const SENIORITY_LABELS: Record<string, string> = {
  senior_secured: "Sr. Secured",
  senior_unsecured: "Sr. Unsecured",
  subordinated: "Subordinated",
  pik: "PIK",
};

export const SENIORITY_COLORS: Record<string, string> = {
  senior_secured: "bg-green-100 text-green-800",
  senior_unsecured: "bg-blue-100 text-blue-800",
  subordinated: "bg-orange-100 text-orange-800",
  pik: "bg-red-100 text-red-800",
};

export const INSTRUMENT_TYPE_LABELS: Record<string, string> = {
  senior_notes: "Sr. Notes",
  term_loan: "Term Loan",
  revolver: "Revolver",
  sub_notes: "Sub. Notes",
  convertible: "Convertible",
  other: "Other",
};
