"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { apiClient } from "@/lib/api";

/* ── Types ──────────────────────────────────────────────────── */

export type Workspace = {
  id: string;
  user_id: string;
  name: string;
  meta_ad_account_id: string | null;
  meta_page_id: string | null;
  meta_pixel_id: string | null;
  meta_ig_actor_id: string | null;
  business_name: string | null;
  website_url: string | null;
  target_country: string | null;
  industry_niche: string | null;
  tracking_mode: string | null;
  is_active: boolean;
  created_at: string;
};

type WorkspaceContextValue = {
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  isLoading: boolean;
  switchWorkspace: (workspaceId: string) => void;
  refetchWorkspaces: () => Promise<void>;
};

const STORAGE_KEY = "meta-ads-active-workspace-id";

const WorkspaceContext = createContext<WorkspaceContextValue>({
  workspaces: [],
  activeWorkspace: null,
  isLoading: true,
  switchWorkspace: () => {},
  refetchWorkspaces: async () => {},
});

export const useWorkspace = () => useContext(WorkspaceContext);

/* ── Provider ───────────────────────────────────────────────── */

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeWorkspace, setActiveWorkspace] = useState<Workspace | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchWorkspaces = useCallback(async () => {
    try {
      const { data } = await apiClient.get("/api/v1/workspaces/");
      const list: Workspace[] = data.workspaces ?? [];
      setWorkspaces(list);

      if (list.length === 0) {
        setActiveWorkspace(null);
        return;
      }

      // Restore last-used workspace from localStorage
      const savedId =
        typeof window !== "undefined"
          ? localStorage.getItem(STORAGE_KEY)
          : null;
      const saved = savedId ? list.find((w) => w.id === savedId) : null;
      const chosen = saved ?? list[0];
      setActiveWorkspace(chosen);
      // Always persist so the api interceptor can read it synchronously
      if (chosen && typeof window !== "undefined") {
        localStorage.setItem(STORAGE_KEY, chosen.id);
      }
    } catch {
      // Auth may not be ready yet — silently ignore
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  const switchWorkspace = useCallback(
    (workspaceId: string) => {
      const ws = workspaces.find((w: Workspace) => w.id === workspaceId);
      if (!ws) return;
      setActiveWorkspace(ws);
      localStorage.setItem(STORAGE_KEY, workspaceId);
      // Clear all cached data so new workspace gets fresh data
      try { sessionStorage.clear(); } catch { /* ignore */ }
      // Force full reload so all pages re-fetch with new workspace header
      window.location.reload();
    },
    [workspaces],
  );

  return (
    <WorkspaceContext.Provider
      value={{
        workspaces,
        activeWorkspace,
        isLoading,
        switchWorkspace,
        refetchWorkspaces: fetchWorkspaces,
      }}
    >
      {children}
    </WorkspaceContext.Provider>
  );
}
