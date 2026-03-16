"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Loader2, ArrowUpRight } from "lucide-react";

export default function AccountsPage() {
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConnectMeta = async () => {
    setConnecting(true);
    setError(null);
    try {
      const { data } = await api.getMetaAuthUrl();
      window.location.href = data.authorization_url;
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 401 || status === 403) {
        setError("You must be logged in to connect an account.");
      } else if (err?.code === "ERR_NETWORK") {
        setError("Cannot reach the backend. Is it running?");
      } else {
        setError(detail ?? "Failed to start OAuth flow.");
      }
      setConnecting(false);
    }
  };

  return (
    <div className="p-8 w-full animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-1">Ad Accounts</h1>
        <p className="text-sm text-gray-500">Connect and manage your Meta Ad Accounts.</p>
      </div>

      <div className="glass rounded-2xl p-8">
        <div className="flex items-start gap-4 mb-6">
          <div className="w-10 h-10 rounded-xl bg-[#1877F2]/10 border border-[#1877F2]/20 flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 fill-[#1877F2]" viewBox="0 0 24 24">
              <path d="M24 12.073C24 5.404 18.627 0 12 0S0 5.404 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.514c-1.491 0-1.956.93-1.956 1.884v2.25h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z" />
            </svg>
          </div>
          <div>
            <h2 className="font-semibold text-white mb-1">Connect a Meta Ad Account</h2>
            <p className="text-sm text-gray-500 leading-relaxed">
              You&apos;ll be redirected to Facebook to authorize access. We request{" "}
              <code className="text-blue-400 text-xs bg-blue-500/[0.08] px-1.5 py-0.5 rounded">ads_management</code> and{" "}
              <code className="text-blue-400 text-xs bg-blue-500/[0.08] px-1.5 py-0.5 rounded">ads_read</code> permissions only.
            </p>
          </div>
        </div>

        {error && (
          <div className="mb-4 flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-red-500/[0.08] border border-red-500/20 text-red-400 text-sm">
            <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <circle cx="12" cy="12" r="10" />
              <path d="M12 8v4m0 4h.01" />
            </svg>
            {error}
          </div>
        )}

        <button
          onClick={handleConnectMeta}
          disabled={connecting}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#1877F2] hover:bg-[#166fe5] disabled:opacity-50 rounded-xl text-sm font-semibold transition-all hover:scale-[1.02] active:scale-[0.98] shadow-[0_0_15px_rgba(24,119,242,0.2)]"
        >
          {connecting ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Redirecting…</>
          ) : (
            <>Connect with Facebook <ArrowUpRight className="w-4 h-4" /></>
          )}
        </button>
      </div>
    </div>
  );
}
