import React, { useState } from "react";
import { login, register } from "../../api/auth";
import { useAuthStore } from "../../store/authStore";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [success, setSuccess] = useState(false);
  const setToken = useAuthStore((s) => s.setToken);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === "register") {
        await register(email, password);
        setSuccess(true);
        setMode("login");
      } else {
        const res = await login(email, password);
        setToken(res.access_token);
        window.location.href = "/";
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || (mode === "login" ? "Invalid email or password." : "Registration failed."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow-lg p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="text-2xl font-bold text-navy mb-1">Credit Analysis</div>
          <div className="text-sm text-gray-500">
            {mode === "login" ? "Sign in to your account" : "Create an account"}
          </div>
        </div>

        {success && (
          <div className="mb-4 bg-green-50 border border-green-200 text-green-700 rounded-lg px-4 py-2.5 text-sm">
            Account created! Please sign in.
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm
                         focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg px-3 py-2 text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-navy hover:bg-navy-light text-white rounded-lg py-2.5 font-semibold text-sm transition-colors disabled:opacity-60"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                {mode === "login" ? "Signing in..." : "Creating account..."}
              </span>
            ) : mode === "login" ? (
              "Sign In"
            ) : (
              "Create Account"
            )}
          </button>
        </form>

        <div className="mt-5 text-center">
          <button
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
              setSuccess(false);
            }}
            className="text-sm text-blue-600 hover:underline"
          >
            {mode === "login" ? "Need an account? Register" : "Already have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}
