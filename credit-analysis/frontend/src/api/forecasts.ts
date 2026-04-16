import { apiClient } from "./client";

export interface ForecastPeriod {
  label: string;
  period_end: string;
}

export interface AssumptionRow {
  concept: string;
  method: string;
  params: Record<string, unknown>;
  overrides: Record<string, number>;
}

export interface ForecastSession {
  id: string;
  cik: string;
  name: string;
  base_period_ends: string[];
  forecast_periods: ForecastPeriod[];
  assumptions: AssumptionRow[];
  forecast_values: Record<string, Record<string, number | null>>;
  created_at: string;
  updated_at: string;
}

export interface CreateForecastRequest {
  name: string;
  statement_type?: string;
  base_filing_id: number;
  base_period_ends: string[];
  forecast_periods: ForecastPeriod[];
  assumptions?: AssumptionRow[];
}

export async function listForecasts(cik: string): Promise<ForecastSession[]> {
  const res = await apiClient.get<ForecastSession[]>(`/api/companies/${cik}/forecasts`);
  return res.data;
}

export async function getForecast(cik: string, sessionId: string): Promise<ForecastSession> {
  const res = await apiClient.get<ForecastSession>(
    `/api/companies/${cik}/forecasts/${sessionId}`
  );
  return res.data;
}

export async function createForecast(
  cik: string,
  body: CreateForecastRequest
): Promise<ForecastSession> {
  const res = await apiClient.post<ForecastSession>(`/api/companies/${cik}/forecasts`, body);
  return res.data;
}

export async function updateForecast(
  cik: string,
  sessionId: string,
  body: Partial<{ name: string; assumptions: AssumptionRow[]; forecast_periods: ForecastPeriod[] }>
): Promise<ForecastSession> {
  const res = await apiClient.put<ForecastSession>(
    `/api/companies/${cik}/forecasts/${sessionId}`,
    body
  );
  return res.data;
}

export async function deleteForecast(cik: string, sessionId: string): Promise<void> {
  await apiClient.delete(`/api/companies/${cik}/forecasts/${sessionId}`);
}
