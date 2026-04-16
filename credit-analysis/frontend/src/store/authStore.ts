import { create } from "zustand";

interface AuthState {
  token: string | null;
  setToken: (token: string | null) => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem("access_token"),
  setToken: (token) => {
    if (token) {
      localStorage.setItem("access_token", token);
    } else {
      localStorage.removeItem("access_token");
    }
    set({ token });
  },
  isAuthenticated: () => !!get().token,
}));
