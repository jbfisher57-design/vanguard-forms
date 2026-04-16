import { apiClient } from "./client";

export interface GridColumn {
  key: string;
  label: string;
  period_end: string | null;
  type: "historical" | "forecast";
}

export interface ForecastData {
  method: string;
  params: Record<string, unknown>;
  computed: Record<string, number | null>;
}

export interface GridRow {
  row_id: string;
  label: string;
  level: number;
  is_abstract: boolean;
  semantic_type: string;
  values: Record<string, number | null>;
  forecast?: ForecastData;
}

export interface FinancialGrid {
  cik: string;
  company_name: string;
  statement_type: string;
  form_type: string;
  unit: string;
  columns: GridColumn[];
  rows: GridRow[];
}

export type StatementType = "income_statement" | "balance_sheet" | "cash_flow";
export type FormType = "10-K" | "10-Q";

export async function getFinancials(
  cik: string,
  statement: StatementType,
  periods: number,
  formType: FormType
): Promise<FinancialGrid> {
  const res = await apiClient.get<FinancialGrid>(`/api/companies/${cik}/financials`, {
    params: { statement, periods, form_type: formType },
  });
  return res.data;
}
