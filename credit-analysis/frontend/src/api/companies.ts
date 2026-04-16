import { apiClient } from "./client";

export interface CompanySearchResult {
  cik: string;
  ticker: string | null;
  name: string;
  sic: string | null;
  fiscal_year_end: string | null;
}

export interface AvailablePeriod {
  period_end: string;
  form_type: string;
  filing_id: number;
}

export interface CompanyDetail extends CompanySearchResult {
  sic_description: string | null;
  state_of_inc: string | null;
  available_periods: AvailablePeriod[];
}

export async function searchCompanies(q: string, limit = 20): Promise<CompanySearchResult[]> {
  const res = await apiClient.get<CompanySearchResult[]>("/api/companies/search", {
    params: { q, limit },
  });
  return res.data;
}

export async function getCompany(cik: string): Promise<CompanyDetail> {
  const res = await apiClient.get<CompanyDetail>(`/api/companies/${cik}`);
  return res.data;
}
