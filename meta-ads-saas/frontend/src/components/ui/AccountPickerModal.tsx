"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Loader2, Check, X, Building2 } from "lucide-react";

type MetaAccount = {
  id: string;
  name: string;
  currency: string;
  timezone_name: string;
  already_linked: boolean;
};

export function AccountPickerModal({
  open,
  onClose,
  onLinked,
}: {
  open: boolean;
  onClose: () => void;
  onLinked: () => void;
}) {
  const [accounts, setAccounts] = useState<MetaAccount[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [linking, setLinking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    api
      .getAvailableAccounts()
      .then(({ data }) => {
        setAccounts(data.accounts || []);
        // Pre-select already linked ones
        const linked = new Set(
          (data.accounts || []).filter((a) => a.already_linked).map((a) => a.id)
        );
        setSelected(linked);
      })
      .catch((err) => {
        setError(
          err?.response?.data?.detail || "Failed to fetch accounts from Meta."
        );
      })
      .finally(() => setLoading(false));
  }, [open]);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleLink = async () => {
    // Send ALL selected (including already-linked). The backend's upsert
    // path is idempotent and re-activates rows that were previously flagged
    // inactive. Skipping already-linked rows here would prevent recovery
    // when a row exists but its is_active flag is false.
    const toLink = [...selected];
    if (toLink.length === 0) {
      onClose();
      return;
    }
    setLinking(true);
    try {
      await api.linkAccounts(toLink);
      onLinked();
      onClose();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to link accounts.");
    } finally {
      setLinking(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-lg mx-4 glass rounded-2xl overflow-hidden animate-slide-up">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-[#1877F2]/10 border border-[#1877F2]/20 flex items-center justify-center">
              <Building2 className="w-4 h-4 text-[#1877F2]" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">
                Choose Ad Accounts
              </p>
              <p className="text-xs text-gray-500">
                Select which accounts to link to this workspace
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/[0.06] transition-colors"
          >
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 max-h-[400px] overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12 gap-2 text-gray-500 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              Fetching accounts from Meta...
            </div>
          ) : error ? (
            <div className="text-center py-8">
              <p className="text-sm text-red-400 mb-2">{error}</p>
              <button
                onClick={onClose}
                className="text-xs text-gray-500 hover:text-white transition-colors"
              >
                Close
              </button>
            </div>
          ) : accounts.length === 0 ? (
            <p className="text-center py-8 text-sm text-gray-500">
              No ad accounts found on this Meta account.
            </p>
          ) : (
            <div className="space-y-2">
              {accounts.map((a) => {
                const isSelected = selected.has(a.id);
                return (
                  <button
                    key={a.id}
                    onClick={() => toggle(a.id)}
                    className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-all ${
                      isSelected
                        ? "bg-blue-500/[0.08] border-blue-500/25"
                        : "bg-white/[0.02] border-white/[0.06] hover:border-white/[0.12]"
                    }`}
                  >
                    {/* Checkbox */}
                    <div
                      className={`w-5 h-5 rounded-md border flex items-center justify-center shrink-0 transition-all ${
                        isSelected
                          ? "bg-blue-500 border-blue-500"
                          : "border-white/[0.15] bg-white/[0.03]"
                      }`}
                    >
                      {isSelected && <Check className="w-3 h-3 text-white" />}
                    </div>
                    {/* Account info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-medium truncate">
                        {a.name || "Unnamed Account"}
                      </p>
                      <p className="text-xs text-gray-500">
                        {a.id} &middot; {a.currency} &middot; {a.timezone_name}
                      </p>
                    </div>
                    {a.already_linked && (
                      <span className="text-[10px] font-medium text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full shrink-0">
                        Linked
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        {!loading && !error && accounts.length > 0 && (
          <div className="px-6 py-4 border-t border-white/[0.06] flex items-center justify-between">
            <p className="text-xs text-gray-500">
              {selected.size} of {accounts.length} selected
            </p>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="px-4 py-2 rounded-xl text-xs font-medium text-gray-400 hover:text-white hover:bg-white/[0.04] transition-all"
              >
                Cancel
              </button>
              <button
                onClick={handleLink}
                disabled={selected.size === 0 || linking}
                className="flex items-center gap-1.5 px-5 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all disabled:opacity-40"
              >
                {linking ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : null}
                {linking ? "Linking..." : `Link ${selected.size} Account${selected.size !== 1 ? "s" : ""}`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
