import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";
import { TrendingUp, DollarSign, Target, ArrowUpRight, Zap, ShoppingCart, BarChart3 } from "lucide-react";
import Link from "next/link";
import { DashboardStats } from "./DashboardStats";
import { AccountAuditWidget } from "./AccountAuditWidget";

export default async function DashboardPage() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) redirect("/auth/login");

  // Check if user has connected Meta AND completed setup wizard
  const { data: accounts } = await supabase
    .from("ad_accounts")
    .select("id")
    .eq("user_id", user.id)
    .eq("is_active", true)
    .limit(1);

  const hasMetaAccount = accounts && accounts.length > 0;

  if (hasMetaAccount) {
    const { data: prefs } = await supabase
      .from("user_preferences")
      .select("setup_completed_at")
      .eq("user_id", user.id)
      .limit(1)
      .single();

    if (!prefs?.setup_completed_at) {
      redirect("/dashboard/setup");
    }
  }

  const firstName = user.email?.split("@")[0] ?? "there";

  return (
    <div className="p-8 w-full animate-fade-in">
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-1">
          Welcome back, <span className="gradient-text">{firstName}</span>
        </h1>
        <p className="text-sm text-gray-500">
          Here&apos;s an overview of your ad performance.
        </p>
      </div>

      {/* Live Stats — client component */}
      {hasMetaAccount ? (
        <DashboardStats />
      ) : (
        /* Placeholder stats when no account connected */
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          {[
            { label: "Active Campaigns", value: "—", icon: Target, iconBg: "bg-blue-500/10 text-blue-400" },
            { label: "Total Spend (30d)", value: "—", icon: DollarSign, iconBg: "bg-emerald-500/10 text-emerald-400" },
            { label: "Average ROAS", value: "—", icon: TrendingUp, iconBg: "bg-violet-500/10 text-violet-400" },
          ].map((stat) => (
            <div
              key={stat.label}
              className="glass rounded-2xl p-5 hover:bg-white/[0.04] transition-all duration-300 group"
            >
              <div className="flex items-center justify-between mb-3">
                <div className={`w-9 h-9 rounded-xl ${stat.iconBg} flex items-center justify-center`}>
                  <stat.icon className="w-[18px] h-[18px]" />
                </div>
              </div>
              <p className="text-sm text-gray-500 mb-0.5">{stat.label}</p>
              <p className="text-2xl font-bold text-white tracking-tight">{stat.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Account Audit Widget — only show when Meta is connected */}
      {hasMetaAccount && <AccountAuditWidget />}

      {/* Connect Account CTA */}
      <div className="glass rounded-2xl overflow-hidden">
        <div className="relative p-8">
          {/* Glow accent */}
          <div className="absolute top-0 right-0 w-[300px] h-[200px] bg-gradient-to-bl from-blue-500/[0.08] to-transparent rounded-bl-full pointer-events-none" />

          <div className="relative flex flex-col sm:flex-row items-start sm:items-center gap-6">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-500/20 to-violet-500/10 border border-blue-500/20 flex items-center justify-center shrink-0">
              <Zap className="w-6 h-6 text-blue-400" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-semibold text-white mb-1">
                {hasMetaAccount ? "View Your Campaigns" : "Connect Your Meta Ad Account"}
              </h2>
              <p className="text-sm text-gray-500 leading-relaxed max-w-xl">
                {hasMetaAccount
                  ? "Head to the Campaigns page to see all running ads and posts with detailed performance analysis."
                  : "Link your Facebook & Instagram Ad Accounts to unlock AI-powered campaign management, real-time analytics, and automated optimizations."}
              </p>
            </div>
            <Link
              href={hasMetaAccount ? "/dashboard/campaigns" : "/dashboard/settings"}
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 rounded-xl text-sm font-semibold transition-all glow-blue hover:scale-[1.02] active:scale-[0.98] shrink-0"
            >
              {hasMetaAccount ? "View Campaigns" : "Connect Account"}
              <ArrowUpRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
