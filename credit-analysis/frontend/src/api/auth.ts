import { apiClient } from "./client";

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const form = new URLSearchParams();
  form.append("username", email);
  form.append("password", password);
  const res = await apiClient.post<LoginResponse>("/auth/jwt/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return res.data;
}

export async function register(email: string, password: string) {
  const res = await apiClient.post("/auth/register", { email, password });
  return res.data;
}

export async function logout() {
  await apiClient.post("/auth/jwt/logout");
  localStorage.removeItem("access_token");
}
