"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Loader2, AlertCircle } from "lucide-react";

export function ConnectMetaButton() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnect = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.getMetaAuthUrl();
      window.location.href = data.authorization_url;
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 401 || status === 403) {
        setError("You must be logged in to connect an account.");
      } else if (status === 503) {
        setError(detail ?? "Meta OAuth is not configured on the server.");
      } else if (err?.code === "ERR_NETWORK") {
        setError("Cannot reach the backend server. Make sure it is running.");
      } else {
        setError(detail ?? "Failed to start OAuth flow.");
      }
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        onClick={handleConnect}
        disabled={loading}
        className="inline-flex items-center gap-2 px-4 py-2.5 bg-[#1877F2] hover:bg-[#166fe5] active:bg-[#1464d8] disabled:opacity-50 disabled:cursor-not-allowed rounded-xl text-sm font-semibold text-white transition-all hover:scale-[1.02] active:scale-[0.98] shadow-[0_0_15px_rgba(24,119,242,0.2)]"
      >
        {loading ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Redirecting…
          </>
        ) : (
          <>
            <svg className="w-4 h-4 fill-white" viewBox="0 0 24 24">
              <path d="M24 12.073C24 5.404 18.627 0 12 0S0 5.404 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.514c-1.491 0-1.956.93-1.956 1.884v2.25h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z" />
            </svg>
            Connect with Facebook
          </>
        )}
      </button>
      {error && (
        <div className="flex items-center gap-1.5 max-w-xs text-right">
          <AlertCircle className="w-3.5 h-3.5 text-red-400 shrink-0" />
          <p className="text-xs text-red-400">{error}</p>
        </div>
      )}
    </div>
  );
}
