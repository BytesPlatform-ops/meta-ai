"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
} from "recharts";
import { api } from "@/lib/api";

const COLORS = ["#3b82f6", "#8b5cf6", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#06b6d4", "#84cc16"];

const DATE_PRESETS = [
  { label: "7d", value: "last_7d" },
  { label: "14d", value: "last_14d" },
  { label: "30d", value: "last_30d" },
] as const;

const tooltipProps = {
  contentStyle: {
    backgroundColor: "#1a1a2e",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: "8px",
  },
  labelStyle: { color: "#9ca3af" },
  itemStyle: { color: "#e5e7eb" },
};

function GlassCard({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white/[0.02] border border-white/[0.06] rounded-2xl p-6 ${className}`}>
      {children}
    </div>
  );
}

type DailyRowRaw = { date: string; spend: number; roas: number | null; impressions: number; ctr: number; purchases: number; leads: number; results: number; result_type: string; cpm: number };
type DailyRow = DailyRowRaw & { cost_per_result: number };
type CampaignRow = { id: string; name: string; spend: number; roas: number | null; purchases: number; leads: number; results: number; result_type: string; impressions: number; reach: number; clicks: number; ctr: number; cost_per_result: number | null };
type TimeSeriesData = { daily: DailyRow[]; by_campaign?: CampaignRow[] };

export default function AnalyticsPage() {
  const [datePreset, setDatePreset] = useState<string>("last_7d");
  const [data, setData] = useState<TimeSeriesData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // Show cached data instantly while fetching fresh
    const cacheKey = `analytics_${datePreset}`;
    try {
      const cached = sessionStorage.getItem(cacheKey);
      if (cached) { setData(JSON.parse(cached)); setLoading(false); }
    } catch { /* ignore */ }
    if (!data) setLoading(true);
    api.getDefaultTimeSeries(datePreset).then((res: { data: TimeSeriesData }) => {
      if (!cancelled) {
        const tsData = (res as { data: TimeSeriesData }).data ?? res;
        // Enrich daily rows with computed cost_per_result
        if (tsData?.daily) {
          tsData.daily = tsData.daily.map((d: DailyRowRaw & { cost_per_result?: number }) => ({
            ...d,
            cost_per_result: d.cost_per_result ?? (d.results > 0 ? Math.round(d.spend / d.results) : 0),
          }));
        }
        setData(tsData);
        setLoading(false);
        try { sessionStorage.setItem(cacheKey, JSON.stringify(tsData)); } catch { /* ignore */ }
      }
    }).catch(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [datePreset]);

  const topCampaigns = (data?.by_campaign
    ?.slice()
    .sort((a, b) => b.spend - a.spend)
    .slice(0, 10) ?? []).map(c => ({ ...c, shortName: c.name.length > 20 ? c.name.slice(0, 18) + "…" : c.name }));

  // Determine dominant result type from daily data (most common non-empty result_type)
  const dominantType = (() => {
    const types = data?.daily?.map((d) => d.result_type).filter(Boolean) ?? [];
    const leadCount = types.filter((t) => t === "leads").length;
    return leadCount > types.length / 2 ? "leads" : "purchases";
  })();

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">
            <span className="bg-gradient-to-r from-blue-400 to-violet-400 bg-clip-text text-transparent">Analytics</span>
          </h1>
          <p className="text-gray-500 text-sm mt-1">Track performance trends and campaign breakdowns.</p>
        </div>

        {/* Date range toggle */}
        <div className="flex gap-1 bg-white/[0.04] rounded-xl p-1 border border-white/[0.06]">
          {DATE_PRESETS.map((p) => (
            <button
              key={p.value}
              onClick={() => setDatePreset(p.value)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
                datePreset === p.value
                  ? "bg-blue-500/20 text-blue-400 shadow-[inset_0_0_0_1px_rgba(59,130,246,0.3)]"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-32">
          <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && (!data || !data.daily?.length) && (
        <div className="flex flex-col items-center justify-center py-32 text-gray-500">
          <p className="text-lg font-medium">No data available</p>
          <p className="text-sm mt-1">Try selecting a different date range.</p>
        </div>
      )}

      {/* Charts */}
      {!loading && data && data.daily?.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Spend Over Time */}
          <GlassCard className="lg:col-span-2">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Spend Over Time</h3>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={data.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                <Tooltip {...tooltipProps} />
                <Line type="monotone" dataKey="spend" stroke="#3b82f6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </GlassCard>

          {/* ROAS / CPL Trend */}
          <GlassCard className="lg:col-span-2">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">
              {dominantType === "leads" ? "Cost Per Lead Trend" : "ROAS Trend"}
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={data.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                <Tooltip {...tooltipProps} />
                {dominantType !== "leads" && (
                  <ReferenceLine y={1.0} stroke="#ef4444" strokeDasharray="4 4" label={{ value: "Break-even", fill: "#ef4444", fontSize: 11 }} />
                )}
                <Line type="monotone" dataKey={dominantType === "leads" ? "cost_per_result" : "roas"} stroke="#8b5cf6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </GlassCard>

          {/* CTR Trend */}
          <GlassCard>
            <h3 className="text-sm font-semibold text-gray-300 mb-4">CTR Trend</h3>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={data.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                <Tooltip {...tooltipProps} />
                <Area type="monotone" dataKey="ctr" stroke="#10b981" fill="#10b981" fillOpacity={0.15} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </GlassCard>

          {/* Results Over Time */}
          <GlassCard>
            <h3 className="text-sm font-semibold text-gray-300 mb-4">
              {dominantType === "leads" ? "Leads" : "Purchases"} Over Time
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={data.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                <Tooltip {...tooltipProps} />
                <Bar dataKey="results" fill="#f59e0b" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </GlassCard>

          {/* ── Per-Campaign Detail Cards ──────────────────────────── */}
          {(data.by_campaign?.length ?? 0) > 0 && (
            <GlassCard className="lg:col-span-2">
              <h3 className="text-sm font-semibold text-gray-300 mb-4">Campaign Performance Breakdown</h3>
              <div className="space-y-3">
                {data.by_campaign!.sort((a, b) => b.spend - a.spend).map((c, i) => {
                  const isLead = c.result_type === "leads";
                  return (
                    <div key={c.id || i} className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4 hover:bg-white/[0.04] transition-all">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                          <h4 className="text-sm font-medium text-white truncate">{c.name}</h4>
                        </div>
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${isLead ? "bg-blue-500/10 text-blue-400" : "bg-violet-500/10 text-violet-400"}`}>
                          {isLead ? "LEAD GEN" : c.result_type === "none" ? "NO DATA" : "PURCHASE"}
                        </span>
                      </div>
                      <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-xs">
                        <div>
                          <p className="text-gray-600 mb-0.5">Spend</p>
                          <p className="text-white font-semibold">${c.spend.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                        </div>
                        <div>
                          <p className="text-gray-600 mb-0.5">{isLead ? "Leads" : "Results"}</p>
                          <p className="text-white font-semibold">{c.results}</p>
                        </div>
                        <div>
                          <p className="text-gray-600 mb-0.5">{isLead ? "CPL" : "ROAS"}</p>
                          <p className={`font-semibold ${isLead ? "text-white" : ((c.roas ?? 0) >= 2 ? "text-emerald-400" : "text-amber-400")}`}>
                            {isLead ? (c.cost_per_result ? `$${c.cost_per_result.toFixed(2)}` : "—") : (c.roas != null ? `${c.roas.toFixed(2)}x` : "—")}
                          </p>
                        </div>
                        <div>
                          <p className="text-gray-600 mb-0.5">Impressions</p>
                          <p className="text-white font-semibold">{c.impressions.toLocaleString()}</p>
                        </div>
                        <div>
                          <p className="text-gray-600 mb-0.5">Reach</p>
                          <p className="text-white font-semibold">{(c.reach || 0).toLocaleString()}</p>
                        </div>
                        <div>
                          <p className="text-gray-600 mb-0.5">CTR</p>
                          <p className="text-white font-semibold">{(c.ctr || 0).toFixed(2)}%</p>
                        </div>
                      </div>
                      {/* Spend proportion bar */}
                      <div className="mt-3 h-1.5 bg-white/[0.04] rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.min((c.spend / (data.by_campaign![0]?.spend || 1)) * 100, 100)}%`, backgroundColor: COLORS[i % COLORS.length] }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </GlassCard>
          )}

          {/* Campaign Spend Breakdown */}
          {(data.by_campaign?.length ?? 0) > 0 && (
            <GlassCard>
              <h3 className="text-sm font-semibold text-gray-300 mb-4">Campaign Spend Breakdown</h3>
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={data.by_campaign}
                    dataKey="spend"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    innerRadius={50}
                  >
                    {data.by_campaign!.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip {...tooltipProps} />
                  <Legend wrapperStyle={{ color: "#9ca3af", fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            </GlassCard>
          )}

          {/* Top Campaigns */}
          {topCampaigns.length > 0 && (
          <GlassCard>
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Top Campaigns</h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={topCampaigns} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 12 }} />
                <YAxis dataKey="shortName" type="category" tick={{ fill: "#6b7280", fontSize: 11 }} width={140} />
                <Tooltip {...tooltipProps} />
                <Bar dataKey="spend" radius={[0, 4, 4, 0]}>
                  {topCampaigns.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </GlassCard>
          )}
        </div>
      )}
    </div>
  );
}
