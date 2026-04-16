import axios from "axios";

export const apiClient = axios.create({
  baseURL: "",
  headers: { "Content-Type": "application/json" },
});

// Attach JWT token from localStorage to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(error)
);
