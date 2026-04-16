import { apiClient } from "./client";

export interface DebtInstrument {
  id: number;
  instrument_name: string;
  instrument_type: string | null;
  seniority: string | null;
  principal_amount: number | null;
  currency: string;
  coupon_rate: number | null;
  coupon_type: string | null;
  floating_benchmark: string | null;
  floating_spread: number | null;
  maturity_date: string | null;
  issuance_date: string | null;
  is_outstanding: boolean;
  confidence_score: number;
  originating_doc_url: string | null;
  originating_doc_type: string | null;
}

export async function getDebtSchedule(cik: string): Promise<DebtInstrument[]> {
  const res = await apiClient.get<DebtInstrument[]>(`/api/companies/${cik}/debt`);
  return res.data;
}
