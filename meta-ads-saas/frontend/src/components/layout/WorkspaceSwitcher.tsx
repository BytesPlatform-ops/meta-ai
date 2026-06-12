"use client";

import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { Building2, ChevronDown, Check, Plus, Loader2, Pencil, X, Trash2 } from "lucide-react";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

// No constants needed — creation is now just name → redirect to settings

export function WorkspaceSwitcher() {
  const { workspaces, activeWorkspace, isLoading, switchWorkspace, refetchWorkspaces } =
    useWorkspace();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [wsName, setWsName] = useState("");
  const [saving, setSaving] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        resetCreate();
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Auto-focus input when creating
  useEffect(() => {
    if (creating) inputRef.current?.focus();
  }, [creating]);

  // Auto-focus rename input
  useEffect(() => {
    if (renamingId) renameInputRef.current?.focus();
  }, [renamingId]);

  const handleDelete = async (wsId: string) => {
    if (!confirm("Delete this workspace? This cannot be undone.")) return;
    try {
      await api.deleteWorkspace(wsId);
      await refetchWorkspaces();
      // If we deleted the active workspace, reload to pick the next one
      if (wsId === activeWorkspace?.id) {
        window.location.reload();
      }
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to delete workspace.");
    }
  };

  const handleRename = async () => {
    const name = renameValue.trim();
    if (!name || !renamingId || renameSaving) return;
    setRenameSaving(true);
    try {
      await api.updateWorkspace(renamingId, { name });
      await refetchWorkspaces();
      setRenamingId(null);
      setRenameValue("");
    } catch {
      // silently fail
    } finally {
      setRenameSaving(false);
    }
  };

  const resetCreate = () => {
    setCreating(false);
    setWsName("");
  };

  const handleCreate = async () => {
    const name = wsName.trim();
    if (!name || saving) return;
    setSaving(true);
    try {
      // 1. Create workspace with just the name
      const { data } = await api.createWorkspace({ name });

      // 2. Switch to new workspace + hard redirect to settings for onboarding
      //    Must use window.location (not router.push) so workspace context fully reinitializes
      localStorage.setItem("meta-ads-active-workspace-id", data.id);
      resetCreate();
      setOpen(false);
      window.location.href = "/dashboard/settings?onboarding=true";
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-3 py-2.5 text-xs text-gray-600">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        <span>Loading...</span>
      </div>
    );
  }

  return (
    <div className="relative" ref={ref}>
      {/* Trigger */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl hover:bg-white/[0.04] transition-all group"
      >
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-emerald-500/20 flex items-center justify-center shrink-0">
          <Building2 className="w-3.5 h-3.5 text-emerald-400" />
        </div>
        <div className="flex-1 text-left min-w-0">
          <p className="text-xs font-semibold text-white truncate">
            {activeWorkspace?.name ?? "Select Workspace"}
          </p>
          {activeWorkspace?.business_name && (
            <p className="text-[10px] text-gray-600 truncate">
              {activeWorkspace.business_name}
            </p>
          )}
        </div>
        <ChevronDown
          className={`w-3.5 h-3.5 text-gray-600 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute left-0 right-0 top-full mt-1 z-50 bg-[#12121e] border border-white/[0.08] rounded-xl shadow-2xl py-1 animate-fade-in">
          {workspaces.map((ws) => {
            const isActive = ws.id === activeWorkspace?.id;
            const isRenaming = renamingId === ws.id;

            if (isRenaming) {
              return (
                <div key={ws.id} className="px-3 py-2">
                  <input
                    ref={renameInputRef}
                    type="text"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleRename();
                      if (e.key === "Escape") { setRenamingId(null); setRenameValue(""); }
                    }}
                    className="w-full px-3 py-1.5 rounded-lg bg-white/[0.04] border border-emerald-500/30 text-white text-xs focus:outline-none transition-all"
                  />
                  <div className="flex gap-1.5 mt-1.5">
                    <button
                      onClick={handleRename}
                      disabled={!renameValue.trim() || renameSaving}
                      className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold bg-emerald-600 hover:bg-emerald-500 text-white transition-all disabled:opacity-40"
                    >
                      {renameSaving ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Check className="w-2.5 h-2.5" />}
                      {renameSaving ? "Saving..." : "Save"}
                    </button>
                    <button
                      onClick={() => { setRenamingId(null); setRenameValue(""); }}
                      className="px-2 py-1 rounded-md text-[10px] text-gray-500 hover:text-gray-300 hover:bg-white/[0.04] transition-all"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              );
            }

            return (
              <div
                key={ws.id}
                className={`flex items-center gap-2.5 px-3 py-2.5 transition-all ${
                  isActive
                    ? "bg-emerald-500/[0.08]"
                    : "hover:bg-white/[0.04]"
                }`}
              >
                <button
                  onClick={() => {
                    switchWorkspace(ws.id);
                    setOpen(false);
                  }}
                  className="flex items-center gap-2.5 flex-1 min-w-0 text-left"
                >
                  <div
                    className={`w-6 h-6 rounded-md flex items-center justify-center shrink-0 ${
                      isActive
                        ? "bg-emerald-500/20 border border-emerald-500/30"
                        : "bg-white/[0.04] border border-white/[0.06]"
                    }`}
                  >
                    {isActive ? (
                      <Check className="w-3 h-3 text-emerald-400" />
                    ) : (
                      <Building2 className="w-3 h-3 text-gray-600" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p
                      className={`text-xs font-medium truncate ${
                        isActive ? "text-emerald-400" : "text-gray-300"
                      }`}
                    >
                      {ws.name}
                    </p>
                    {ws.business_name && (
                      <p className="text-[10px] text-gray-600 truncate">
                        {ws.business_name}
                      </p>
                    )}
                  </div>
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setRenamingId(ws.id);
                    setRenameValue(ws.name);
                  }}
                  className="p-1 rounded-md hover:bg-white/[0.06] transition-all shrink-0"
                  title="Rename"
                >
                  <Pencil className="w-3 h-3 text-gray-500 hover:text-gray-300" />
                </button>
                {workspaces.length > 1 && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(ws.id);
                    }}
                    className="p-1 rounded-md hover:bg-red-500/10 transition-all shrink-0"
                    title="Delete"
                  >
                    <Trash2 className="w-3 h-3 text-gray-600 hover:text-red-400" />
                  </button>
                )}
              </div>
            );
          })}

          {/* Divider + Create New */}
          <div className="border-t border-white/[0.06] mt-1 pt-1">
            <button
              onClick={() => { setCreating(true); setOpen(false); }}
              className="w-full flex items-center gap-2.5 px-3 py-2.5 text-left hover:bg-white/[0.04] transition-all"
            >
              <div className="w-6 h-6 rounded-md bg-blue-500/10 border border-blue-500/20 flex items-center justify-center shrink-0">
                <Plus className="w-3 h-3 text-blue-400" />
              </div>
              <span className="text-xs font-medium text-blue-400">
                Create New Workspace
              </span>
            </button>
          </div>
        </div>
      )}

      {/* Create Workspace Modal — just name, then redirect to settings */}
      {creating && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-sm mx-4 glass rounded-2xl overflow-hidden animate-slide-up">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                  <Building2 className="w-4 h-4 text-emerald-400" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-white">New Workspace</p>
                  <p className="text-xs text-gray-500">Name it, then connect your accounts</p>
                </div>
              </div>
              <button onClick={resetCreate} className="p-1.5 rounded-lg hover:bg-white/[0.06] transition-colors">
                <X className="w-4 h-4 text-gray-500" />
              </button>
            </div>

            {/* Form */}
            <div className="px-6 py-5 space-y-3">
              <div>
                <label className="text-xs text-gray-400 mb-1 block">Workspace Name *</label>
                <input
                  ref={inputRef}
                  type="text"
                  value={wsName}
                  onChange={(e) => setWsName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
                  placeholder="e.g. My Coffee Shop"
                  className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-emerald-500/40 transition-all"
                />
              </div>
              <p className="text-[11px] text-gray-600 leading-relaxed">
                You&apos;ll connect your Facebook ad account, select a page, and fill in business details on the next screen.
              </p>
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-white/[0.06] flex justify-end gap-2">
              <button onClick={resetCreate}
                className="px-4 py-2 rounded-xl text-xs font-medium text-gray-400 hover:text-white hover:bg-white/[0.04] transition-all">
                Cancel
              </button>
              <button onClick={handleCreate} disabled={!wsName.trim() || saving}
                className="flex items-center gap-1.5 px-5 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white transition-all disabled:opacity-40">
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                {saving ? "Creating..." : "Create & Setup"}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
