"use client";

import { WorkspaceProvider } from "@/contexts/WorkspaceContext";
import type { ReactNode } from "react";

export function WorkspaceShell({ children }: { children: ReactNode }) {
  return <WorkspaceProvider>{children}</WorkspaceProvider>;
}
