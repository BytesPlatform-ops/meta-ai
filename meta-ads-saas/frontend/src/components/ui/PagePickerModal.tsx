"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { Loader2, Check, X, Facebook, Instagram, AlertCircle, RefreshCw } from "lucide-react";

type SocialPage = {
  page_id: string;
  page_name: string;
  instagram_actor_id: string | null;
  instagram_username: string | null;
  instagram_profile_pic: string | null;
};

// Backend returns this code (HTTP 401 detail.code) when Meta has invalidated
// the workspace's access token. We render a dedicated reconnect-CTA state
// instead of a generic red error so the user can act without leaving the
// modal.
const META_TOKEN_EXPIRED_CODE = "META_TOKEN_EXPIRED";

type ErrorState =
  | { kind: "generic"; message: string }
  // ``token_expired`` covers both "Meta said the access token is dead"
  // (HTTP 401, code=META_TOKEN_EXPIRED) AND "no active ad account is
  // attached to this workspace" (HTTP 404). Both resolve via the same
  // user action — start the Meta OAuth flow — so we collapse them into
  // a single "needs (re)connection" state with slightly different copy.
  | { kind: "token_expired"; message: string; firstTime?: boolean };

export function PagePickerModal({
  open,
  onClose,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const { activeWorkspace, refetchWorkspaces } = useWorkspace();
  const [pages, setPages] = useState<SocialPage[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ErrorState | null>(null);
  const [reconnecting, setReconnecting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError(null);
    api
      .fetchSocialIdentities()
      .then(({ data }) => {
        const list = data.pages || [];
        setPages(list);
        // Pre-select the workspace's current page if set
        const currentPageId = activeWorkspace?.meta_page_id;
        if (currentPageId && list.some((p) => p.page_id === currentPageId)) {
          setSelectedId(currentPageId);
        } else if (list.length === 1) {
          setSelectedId(list[0].page_id);
        }
      })
      .catch((err) => {
        // Three failure modes the backend can return for this endpoint —
        // all of them resolve via the same user action (start the Meta
        // OAuth flow), so we route them to one Reconnect/Connect CTA:
        //
        //   1. 401 + detail.code === META_TOKEN_EXPIRED
        //         → Meta invalidated the token (re-auth needed)
        //   2. 404 + "No active ad account..."
        //         → workspace has no Meta connection yet OR the account
        //           was previously marked inactive
        //   3. Anything else → generic red error.
        const status = err?.response?.status;
        const detail = err?.response?.data?.detail;
        const detailMessage =
          (typeof detail === "string" && detail) || detail?.message || "";

        const isTokenExpired =
          status === 401 &&
          typeof detail === "object" &&
          detail?.code === META_TOKEN_EXPIRED_CODE;
        const isNoActiveAccount =
          status === 404 &&
          /no active ad account/i.test(detailMessage);

        if (isTokenExpired) {
          setError({
            kind: "token_expired",
            firstTime: false,
            message:
              detail.message ||
              "Your Meta connection has expired. Reconnect to continue.",
          });
        } else if (isNoActiveAccount) {
          setError({
            kind: "token_expired",
            firstTime: true,
            message:
              "No active Meta ad account is attached to this workspace. Connect Meta to continue.",
          });
        } else {
          const message =
            detailMessage || err?.message || "Failed to fetch pages from Meta.";
          setError({ kind: "generic", message });
        }
      })
      .finally(() => setLoading(false));
  }, [open, activeWorkspace?.meta_page_id]);

  const handleReconnect = async () => {
    setReconnecting(true);
    try {
      const { data } = await api.getMetaAuthUrl();
      // Send the user to Meta's consent screen. After OAuth they'll come
      // back to /dashboard/settings via the existing callback flow.
      window.location.href = data.authorization_url;
    } catch {
      setError({
        kind: "generic",
        message:
          "Could not start Meta reconnect flow. Visit Settings and click Connect.",
      });
      setReconnecting(false);
    }
  };

  const handleSave = async () => {
    if (!selectedId || !activeWorkspace) return;
    const page = pages.find((p) => p.page_id === selectedId);
    if (!page) return;

    setSaving(true);
    try {
      await api.updateWorkspace(activeWorkspace.id, {
        meta_page_id: page.page_id,
        meta_ig_actor_id: page.instagram_actor_id || null,
      });
      await refetchWorkspaces();
      onSaved?.();
      onClose();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError({
        kind: "generic",
        message:
          (typeof detail === "string" && detail) ||
          detail?.message ||
          err?.message ||
          "Failed to save page selection.",
      });
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-lg mx-4 glass rounded-2xl overflow-hidden animate-slide-up">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-pink-500/10 border border-pink-500/20 flex items-center justify-center">
              <Facebook className="w-4 h-4 text-pink-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">
                Choose Facebook Page
              </p>
              <p className="text-xs text-gray-500">
                Select the page for this workspace&apos;s ads
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
              Fetching pages from Meta...
            </div>
          ) : error?.kind === "token_expired" ? (
            <div className="text-center py-8 px-2">
              <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto mb-3">
                {error.firstTime ? (
                  <Facebook className="w-5 h-5 text-amber-400" />
                ) : (
                  <AlertCircle className="w-5 h-5 text-amber-400" />
                )}
              </div>
              <p className="text-sm text-white font-medium mb-1">
                {error.firstTime ? "Connect Meta for this workspace" : "Meta connection expired"}
              </p>
              <p className="text-xs text-gray-500 mb-5 max-w-xs mx-auto leading-relaxed">
                {error.message}
              </p>
              <div className="flex items-center justify-center gap-2">
                <button
                  onClick={onClose}
                  className="px-4 py-2 rounded-xl text-xs font-medium text-gray-400 hover:text-white hover:bg-white/[0.04] transition-all"
                >
                  Cancel
                </button>
                <button
                  onClick={handleReconnect}
                  disabled={reconnecting}
                  className="flex items-center gap-1.5 px-5 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all disabled:opacity-40"
                >
                  {reconnecting ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3.5 h-3.5" />
                  )}
                  {reconnecting
                    ? "Redirecting…"
                    : error.firstTime
                    ? "Connect Meta"
                    : "Reconnect Meta"}
                </button>
              </div>
            </div>
          ) : error ? (
            <div className="text-center py-8">
              <p className="text-sm text-red-400 mb-2">{error.message}</p>
              <button
                onClick={onClose}
                className="text-xs text-gray-500 hover:text-white transition-colors"
              >
                Close
              </button>
            </div>
          ) : pages.length === 0 ? (
            <p className="text-center py-8 text-sm text-gray-500">
              No Facebook Pages found on this account.
            </p>
          ) : (
            <div className="space-y-2">
              {pages.map((p) => {
                const isSelected = selectedId === p.page_id;
                return (
                  <button
                    key={p.page_id}
                    onClick={() => setSelectedId(p.page_id)}
                    className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-all ${
                      isSelected
                        ? "bg-blue-500/[0.08] border-blue-500/25"
                        : "bg-white/[0.02] border-white/[0.06] hover:border-white/[0.12]"
                    }`}
                  >
                    {/* Radio */}
                    <div
                      className={`w-5 h-5 rounded-full border-2 flex items-center justify-center shrink-0 transition-all ${
                        isSelected
                          ? "border-blue-500"
                          : "border-white/[0.15]"
                      }`}
                    >
                      {isSelected && (
                        <div className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                      )}
                    </div>
                    {/* Page info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <Facebook className="w-4 h-4 text-blue-400 shrink-0" />
                        <p className="text-sm text-white font-medium truncate">
                          {p.page_name}
                        </p>
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">
                        ID: {p.page_id}
                      </p>
                    </div>
                    {/* IG info */}
                    {p.instagram_actor_id ? (
                      <div className="flex items-center gap-2 shrink-0">
                        {p.instagram_profile_pic && (
                          <img
                            src={p.instagram_profile_pic}
                            alt=""
                            className="w-6 h-6 rounded-full"
                          />
                        )}
                        <div className="text-right">
                          <p className="text-xs text-white">
                            {p.instagram_username
                              ? `@${p.instagram_username}`
                              : "IG linked"}
                          </p>
                          <div className="flex items-center gap-1 justify-end">
                            <Instagram className="w-3 h-3 text-pink-400" />
                            <span className="text-[10px] text-emerald-400">
                              connected
                            </span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <span className="text-[10px] text-gray-600 shrink-0">
                        No IG linked
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        {!loading && !error && pages.length > 0 && (
          <div className="px-6 py-4 border-t border-white/[0.06] flex items-center justify-end gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-medium text-gray-400 hover:text-white hover:bg-white/[0.04] transition-all"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!selectedId || saving}
              className="flex items-center gap-1.5 px-5 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all disabled:opacity-40"
            >
              {saving ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Check className="w-3.5 h-3.5" />
              )}
              {saving ? "Saving..." : "Use This Page"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
