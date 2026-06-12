"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import {
  TrendingUp,
  DollarSign,
  Target,
  ArrowUpRight,
  ShoppingCart,
  Globe,
  FileText,
} from "lucide-react";
import DateRangePicker, { type DateRangeValue } from "@/components/DateRangePicker";

type Metrics = {
  spend: number;
  impressions: number;
  clicks: number;
  ctr: number;
  purchases: number;
  leads: number;
  results: number;
  result_type: string;
  cost_per_result: number | null;
  roas: number | null;
  results_breakdown: Record<string, number>;
};

type DashboardData = {
  account_name: string;
  currency: string;
  active_campaigns: number;
  total_account_metrics: Metrics;
  workspace_page_metrics: Metrics | null;
  page_id: string | null;
};

const BREAKDOWN_LABELS: Record<string, string> = {
  purchases: "Purchases", registrations: "Registrations", leads: "Leads",
  conversations: "Chats", replies: "Replies", clicks: "Clicks", page_views: "Page Views",
};

function MetricsRow({
  label,
  icon: Icon,
  iconBg,
  metrics,
  currency,
  periodLabel,
}: {
  label: string;
  icon: typeof Globe;
  iconBg: string;
  metrics: Metrics;
  currency: string;
  periodLabel: string;
}) {
  const isLeadCampaign = metrics.result_type === "leads";
  const roas = metrics.roas;
  const cpr = metrics.cost_per_result;

  const performanceCard = isLeadCampaign
    ? {
        label: `Cost/Result (${periodLabel})`,
        value: cpr != null ? `${cpr.toLocaleString()} ${currency}` : "—",
        icon: Target,
        iconBg: "bg-violet-500/10 text-violet-400",
        change: null,
      }
    : {
        label: `ROAS (${periodLabel})`,
        value: roas != null ? `${roas.toFixed(2)}x` : "—",
        icon: TrendingUp,
        iconBg: "bg-violet-500/10 text-violet-400",
        change: roas != null && roas >= 3 ? "Scaling" : roas != null && roas >= 1.5 ? "Profitable" : null,
      };

  const breakdownCards = Object.entries(metrics.results_breakdown || {})
    .filter(([, count]) => count > 0)
    .map(([type, count]) => ({
      label: `${BREAKDOWN_LABELS[type] || type}`,
      value: String(count),
      icon: ShoppingCart,
      iconBg: "bg-amber-500/10 text-amber-400",
      change: null,
    }));

  const cards = [
    {
      label: `Spend (${periodLabel})`,
      value: `${metrics.spend.toLocaleString()} ${currency}`,
      icon: DollarSign,
      iconBg: "bg-emerald-500/10 text-emerald-400",
      change: null,
    },
    performanceCard,
    ...breakdownCards,
  ];

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <div className={`w-7 h-7 rounded-lg ${iconBg} flex items-center justify-center`}>
          <Icon className="w-3.5 h-3.5" />
        </div>
        <h3 className="text-sm font-semibold text-white">{label}</h3>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        {cards.map((stat) => (
          <div
            key={stat.label}
            className="glass rounded-xl p-4 hover:bg-white/[0.04] transition-all duration-300"
          >
            <div className="flex items-center justify-between mb-2">
              <div className={`w-7 h-7 rounded-lg ${stat.iconBg} flex items-center justify-center`}>
                <stat.icon className="w-3.5 h-3.5" />
              </div>
              {stat.change && (
                <span className="flex items-center gap-0.5 text-[10px] text-emerald-400 font-medium">
                  <ArrowUpRight className="w-3 h-3" />
                  {stat.change}
                </span>
              )}
            </div>
            <p className="text-[11px] text-gray-500 mb-0.5">{stat.label}</p>
            <p className="text-lg font-bold text-white tracking-tight">{stat.value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DashboardStats() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [datePreset, setDatePreset] = useState("maximum");
  const [since, setSince] = useState<string | undefined>();
  const [until, setUntil] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<"active" | "all">("active");

  const handleDateChange = (v: DateRangeValue) => {
    if (v.preset) { setDatePreset(v.preset); setSince(undefined); setUntil(undefined); }
    else { setSince(v.since); setUntil(v.until); setDatePreset("custom"); }
  };

  const fetchMetrics = useCallback(async (showLoader = true) => {
    try {
      if (showLoader) setLoading(true);
      const { data: metrics } = await api.getDashboardMetrics(datePreset, since, until, statusFilter);
      setData(metrics);
    } catch (err) {
      console.error("Failed to fetch dashboard metrics:", err);
    } finally {
      setLoading(false);
    }
  }, [datePreset, since, until, statusFilter]);

  useEffect(() => { fetchMetrics(); }, [fetchMetrics]);
  useAutoRefresh(() => fetchMetrics(false));

  if (loading) {
    return (
      <div className="space-y-6 mb-8">
        {[0, 1].map((i) => (
          <div key={i}>
            <div className="h-4 w-32 bg-white/[0.04] rounded mb-3" />
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {Array.from({ length: 4 }).map((_, j) => (
                <div key={j} className="glass rounded-xl p-4 animate-pulse">
                  <div className="w-7 h-7 rounded-lg bg-white/[0.04] mb-2" />
                  <div className="h-3 w-20 bg-white/[0.04] rounded mb-2" />
                  <div className="h-6 w-14 bg-white/[0.04] rounded" />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (!data) return null;

  const periodLabel = since && until
    ? `${since.slice(5).replace("-", "/")}–${until.slice(5).replace("-", "/")}`
    : datePreset === "last_7d" ? "7d"
    : datePreset === "last_14d" ? "14d"
    : datePreset === "last_30d" ? "30d"
    : datePreset === "today" ? "Today"
    : datePreset === "maximum" ? "All"
    : "30d";

  return (
    <div className="mb-8 space-y-6">
      {/* Header with date picker + active campaigns */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center">
            <Target className="w-[18px] h-[18px]" />
          </div>
          <div>
            <p className="text-sm text-gray-500">{statusFilter === "all" ? "Campaigns" : "Active Campaigns"}</p>
            <p className="text-xl font-bold text-white">{data.active_campaigns}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center bg-white/[0.04] rounded-lg p-0.5">
            <button
              onClick={() => setStatusFilter("active")}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                statusFilter === "active"
                  ? "bg-blue-500/20 text-blue-400"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              Active
            </button>
            <button
              onClick={() => setStatusFilter("all")}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                statusFilter === "all"
                  ? "bg-blue-500/20 text-blue-400"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              All
            </button>
          </div>
          <DateRangePicker datePreset={datePreset} since={since} until={until} onChange={handleDateChange} />
        </div>
      </div>

      {/* Total Ad Account Metrics */}
      <MetricsRow
        label="Total Ad Account"
        icon={Globe}
        iconBg="bg-blue-500/10 text-blue-400"
        metrics={data.total_account_metrics}
        currency={data.currency}
        periodLabel={periodLabel}
      />

      {/* Workspace Page Metrics */}
      {data.workspace_page_metrics && (
        <MetricsRow
          label="This Workspace (Page)"
          icon={FileText}
          iconBg="bg-violet-500/10 text-violet-400"
          metrics={data.workspace_page_metrics}
          currency={data.currency}
          periodLabel={periodLabel}
        />
      )}

      {/* No page linked hint */}
      {!data.page_id && (
        <div className="glass rounded-xl p-4 flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-amber-500/10 text-amber-400 flex items-center justify-center">
            <FileText className="w-3.5 h-3.5" />
          </div>
          <p className="text-xs text-gray-500">
            No Facebook Page linked to this workspace. Go to <span className="text-amber-400">Settings</span> to connect a page and see page-specific metrics.
          </p>
        </div>
      )}
    </div>
  );
}
