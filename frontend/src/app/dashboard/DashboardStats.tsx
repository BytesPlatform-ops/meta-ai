"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  TrendingUp,
  DollarSign,
  Target,
  ArrowUpRight,
  ShoppingCart,
  Loader2,
} from "lucide-react";

type Overview = {
  active_campaigns: number;
  spend_30d: number;
  roas_30d: number | null;
  purchases_30d: number;
  leads_30d: number;
  results_30d: number;
  result_type_30d: string;
  cost_per_result_30d: number | null;
  currency: string;
};

export function DashboardStats() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data: overview } = await api.getDefaultOverview();
        setData(overview);
      } catch (err) {
        console.error("Failed to fetch overview:", err);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="glass rounded-2xl p-5 animate-pulse">
            <div className="w-9 h-9 rounded-xl bg-white/[0.04] mb-3" />
            <div className="h-3 w-24 bg-white/[0.04] rounded mb-2" />
            <div className="h-7 w-16 bg-white/[0.04] rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const isLeadCampaign = data.result_type_30d === "leads";
  const roas = data.roas_30d;
  const cpr = data.cost_per_result_30d;

  // Dynamic 3rd card: ROAS for purchase campaigns, CPL for lead campaigns
  const performanceCard = isLeadCampaign
    ? {
        label: "Cost per Lead (30d)",
        value: cpr != null ? `${cpr.toLocaleString()} ${data.currency}` : "—",
        icon: Target,
        iconBg: "bg-violet-500/10 text-violet-400",
        change: null,  // No hardcoded judgment — baselines-driven verdicts shown in audit
      }
    : {
        label: "ROAS (30d)",
        value: roas != null ? `${roas.toFixed(2)}x` : "—",
        icon: TrendingUp,
        iconBg: "bg-violet-500/10 text-violet-400",
        change: roas != null && roas >= 3 ? "Scaling" : roas != null && roas >= 1.5 ? "Profitable" : null,
      };

  // Dynamic 4th card: show whichever result type exists
  const resultsLabel = isLeadCampaign ? "Leads (30d)" : data.results_30d > 0 ? "Results (30d)" : "Purchases (30d)";
  const resultsValue = data.results_30d > 0 ? String(data.results_30d) : String(data.purchases_30d);

  const stats = [
    {
      label: "Active Campaigns",
      value: String(data.active_campaigns),
      icon: Target,
      iconBg: "bg-blue-500/10 text-blue-400",
      change: null,
    },
    {
      label: "Spend (30d)",
      value: `${data.spend_30d.toLocaleString()} ${data.currency}`,
      icon: DollarSign,
      iconBg: "bg-emerald-500/10 text-emerald-400",
      change: null,
    },
    {
      ...performanceCard,
    },
    {
      label: resultsLabel,
      value: resultsValue,
      icon: ShoppingCart,
      iconBg: "bg-amber-500/10 text-amber-400",
      change: null,
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="glass rounded-2xl p-5 hover:bg-white/[0.04] transition-all duration-300 group"
        >
          <div className="flex items-center justify-between mb-3">
            <div className={`w-9 h-9 rounded-xl ${stat.iconBg} flex items-center justify-center`}>
              <stat.icon className="w-[18px] h-[18px]" />
            </div>
            {stat.change && (
              <span className="flex items-center gap-0.5 text-xs text-emerald-400 font-medium">
                <ArrowUpRight className="w-3 h-3" />
                {stat.change}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 mb-0.5">{stat.label}</p>
          <p className="text-2xl font-bold text-white tracking-tight">{stat.value}</p>
        </div>
      ))}
    </div>
  );
}
