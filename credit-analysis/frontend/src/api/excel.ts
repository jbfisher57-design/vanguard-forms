import { apiClient } from "./client";

export async function downloadExcel(cik: string, sessionId: string): Promise<void> {
  const res = await apiClient.get(`/api/companies/${cik}/forecasts/${sessionId}/excel`, {
    responseType: "blob",
  });
  const url = window.URL.createObjectURL(new Blob([res.data]));
  const link = document.createElement("a");
  link.href = url;
  const disposition = res.headers["content-disposition"] || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  link.download = match ? match[1] : "forecast.xlsx";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export interface UploadResult {
  session_id: string;
  overrides_applied: number;
  message: string;
}

export async function uploadExcel(cik: string, file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiClient.post<UploadResult>(
    `/api/companies/${cik}/forecasts/upload`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } }
  );
  return res.data;
}
