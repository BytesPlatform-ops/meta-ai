"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";
import { BarChart3, LayoutGrid, TrendingUp, Package, Settings, LogOut, FileCheck, Zap, Sparkles } from "lucide-react";

const NAV = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutGrid },
  { label: "Drafts", href: "/dashboard/drafts", icon: FileCheck },
  { label: "Campaigns", href: "/dashboard/campaigns", icon: TrendingUp },
  { label: "Analytics", href: "/dashboard/analytics", icon: BarChart3 },
  { label: "Co-Pilot", href: "/dashboard/copilot", icon: Sparkles },
  { label: "Products", href: "/dashboard/products", icon: Package },
  { label: "Rules", href: "/dashboard/rules", icon: Zap },
  { label: "Settings", href: "/dashboard/settings", icon: Settings },
];

export function Sidebar({ email }: { email: string }) {
  const pathname = usePathname();
  const router = useRouter();

  const handleSignOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/auth/login");
  };

  return (
    <aside className="w-[240px] shrink-0 flex flex-col bg-[#0a0a0f]/80 backdrop-blur-xl border-r border-white/[0.06] h-screen sticky top-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-white/[0.06]">
        <Link href="/dashboard" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center shrink-0 glow-blue">
            <BarChart3 className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-white text-sm tracking-tight">Meta Ads AI</span>
        </Link>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        <p className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-widest text-gray-600">
          Menu
        </p>
        {NAV.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
                active
                  ? "bg-gradient-to-r from-blue-500/[0.12] to-violet-500/[0.06] text-blue-400 shadow-[inset_0_0_0_1px_rgba(59,130,246,0.15)]"
                  : "text-gray-500 hover:text-gray-300 hover:bg-white/[0.03]"
              }`}
            >
              <Icon className={`w-[18px] h-[18px] ${active ? "text-blue-400" : ""}`} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* User */}
      <div className="px-3 pb-4 border-t border-white/[0.06] pt-3">
        <div className="flex items-center gap-2.5 px-3 py-2.5">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center shrink-0">
            <span className="text-white text-xs font-bold">{email[0]?.toUpperCase()}</span>
          </div>
          <span className="text-gray-400 text-xs truncate flex-1">{email}</span>
        </div>
        <button
          onClick={handleSignOut}
          className="w-full mt-1 flex items-center gap-2.5 px-3 py-2.5 rounded-xl text-xs text-gray-600 hover:text-red-400 hover:bg-red-500/[0.06] transition-all duration-200"
        >
          <LogOut className="w-3.5 h-3.5" />
          Sign out
        </button>
      </div>
    </aside>
  );
}
