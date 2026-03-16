"use client";

import { useState } from "react";
import type { AdAccount } from "@/app/dashboard/settings/page";
import { Clock, Globe, DollarSign, AlertTriangle, Loader2, X } from "lucide-react";

type Props = {
  account: AdAccount;
  onDisconnect: (id: string) => Promise<void>;
};

export function AdAccountCard({ account, onDisconnect }: Props) {
  const [confirming, setConfirming] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const expiresAt = account.token_expires_at
    ? new Date(account.token_expires_at)
    : null;
  const daysLeft = expiresAt
    ? Math.ceil((expiresAt.getTime() - Date.now()) / 86_400_000)
    : null;
  const tokenWarning = daysLeft !== null && daysLeft < 14;

  const handleDisconnect = async () => {
    setDisconnecting(true);
    await onDisconnect(account.id);
  };

  return (
    <div className="glass rounded-2xl p-5 hover:bg-white/[0.04] transition-all duration-300">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          {/* Account name + ID */}
          <div className="flex items-center gap-2.5 mb-2">
            <div className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
            <span className="font-semibold text-white truncate">
              {account.account_name ?? "Unnamed Account"}
            </span>
            <span className="text-[11px] text-gray-600 font-mono shrink-0 bg-white/[0.03] px-2 py-0.5 rounded-md">
              {account.meta_account_id}
            </span>
          </div>

          {/* Meta info row */}
          <div className="flex flex-wrap gap-3 text-xs text-gray-500 ml-[18px]">
            <span className="inline-flex items-center gap-1">
              <DollarSign className="w-3 h-3" />
              {account.currency}
            </span>
            <span className="inline-flex items-center gap-1">
              <Globe className="w-3 h-3" />
              {account.timezone}
            </span>
            {expiresAt && (
              <span className={`inline-flex items-center gap-1 ${tokenWarning ? "text-amber-400" : ""}`}>
                <Clock className="w-3 h-3" />
                {tokenWarning
                  ? `Expires in ${daysLeft} day${daysLeft === 1 ? "" : "s"}`
                  : `Expires ${expiresAt.toLocaleDateString()}`}
              </span>
            )}
          </div>

          {/* Token expiry warning */}
          {tokenWarning && (
            <div className="mt-3 ml-[18px] flex items-center gap-2 text-xs text-amber-400 bg-amber-500/[0.06] border border-amber-500/15 rounded-xl px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              Token expiring soon — reconnect to refresh it.
            </div>
          )}
        </div>

        {/* Disconnect */}
        <div className="shrink-0">
          {!confirming ? (
            <button
              onClick={() => setConfirming(true)}
              className="text-xs text-gray-600 hover:text-red-400 transition-colors px-2 py-1 rounded-lg hover:bg-red-500/[0.06]"
            >
              Disconnect
            </button>
          ) : (
            <div className="flex items-center gap-1.5 bg-red-500/[0.06] border border-red-500/15 rounded-xl px-2.5 py-1.5">
              <button
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="text-xs font-medium text-red-400 hover:text-red-300 disabled:opacity-50 inline-flex items-center gap-1"
              >
                {disconnecting ? (
                  <><Loader2 className="w-3 h-3 animate-spin" /> Removing…</>
                ) : (
                  "Remove"
                )}
              </button>
              <span className="text-gray-700">·</span>
              <button
                onClick={() => setConfirming(false)}
                className="text-xs text-gray-500 hover:text-gray-300"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
