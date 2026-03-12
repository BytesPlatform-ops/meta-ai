"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Loader2,
  DollarSign,
  Eye,
  MousePointerClick,
  TrendingUp,
  Users,
  Target,
  Sparkles,
  Activity,
  Crosshair,
} from "lucide-react";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import { api } from "@/lib/api";

/* ── Shared UI ──────────────────────────────────────────────── */

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

const VERDICT_STYLES: Record<string, { bg: string; icon: string; label: string }> = {
  scale:           { bg: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", icon: "🟢", label: "SCALE" },
  hold:            { bg: "bg-amber-500/10 text-amber-400 border-amber-500/20",       icon: "🟡", label: "HOLD" },
  underperforming: { bg: "bg-red-500/10 text-red-400 border-red-500/20",             icon: "🔴", label: "UNDERPERFORMING" },
  no_purchases:    { bg: "bg-red-500/10 text-red-400 border-red-500/20",             icon: "🔴", label: "NO PURCHASES" },
  no_results:      { bg: "bg-red-500/10 text-red-400 border-red-500/20",             icon: "🔴", label: "NO RESULTS" },
  kill:            { bg: "bg-red-500/10 text-red-400 border-red-500/20",             icon: "🔴", label: "KILL" },
  no_data:         { bg: "bg-gray-500/10 text-gray-400 border-gray-500/20",          icon: "⚪", label: "NO DATA" },
};

const DATE_PRESETS = [
  { label: "7d", value: "last_7d" },
  { label: "14d", value: "last_14d" },
  { label: "30d", value: "last_30d" },
] as const;

/* ── Types ──────────────────────────────────────────────────── */

type Summary = {
  campaign_id: string;
  campaign_name: string;
  no_data: boolean;
  spend: number;
  roas: number | null;
  impressions: number;
  reach: number;
  clicks: number;
  link_clicks: number;
  ctr: number;
  cpm: number;
  cpc: number;
  frequency: number;
  purchases: number;
  leads: number;
  results: number;
  result_type: string;
  cost_per_result: number | null;
  purchase_value: number;
  add_to_cart: number;
  initiate_checkout: number;
  date_start: string;
  date_stop: string;
};

type DailyRow = {
  date: string;
  spend: number;
  impressions: number;
  clicks: number;
  ctr: number;
  cpm: number;
  roas: number | null;
  purchases: number;
  leads: number;
  results: number;
  result_type: string;
  cost_per_result: number | null;
};

type Ad = {
  id: string;
  name: string;
  status: string;
  effective_status: string;
  thumbnail_url: string | null;
  spend: number;
  impressions: number;
  ctr: number;
  roas: number | null;
  purchases: number;
  leads: number;
  results: number;
  result_type: string;
  cost_per_result: number | null;
  verdict: string;
};

type BreakdownRow = {
  spend: number;
  impressions: number;
  clicks: number;
  ctr: number;
  results: number;
  result_type: string;
  cost_per_result: number | null;
  age?: string;
  gender?: string;
  publisher_platform?: string;
  platform_position?: string;
};

type PixelEvent = {
  event: string;
  action_type: string;
  count: number;
  value?: number;
  cost_per?: number;
};

type PixelDailyRow = {
  date: string;
  [key: string]: string | number;
};

type PixelData = {
  pixel_id: string | null;
  pixel_name: string | null;
  events: PixelEvent[];
  daily_events: PixelDailyRow[];
} | null;

type CampaignDetail = {
  summary: Summary;
  daily: DailyRow[];
  ads: Ad[];
  breakdowns: {
    by_age: BreakdownRow[];
    by_gender: BreakdownRow[];
    by_placement: BreakdownRow[];
  };
  pixel: PixelData;
};

/* ── Metric card ──────────────────────────────────────────────── */

function StatCard({ label, value, sub, icon: Icon, color }: {
  label: string; value: string; sub?: string;
  icon: typeof DollarSign; color: string;
}) {
  return (
    <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-7 h-7 rounded-lg ${color} flex items-center justify-center`}>
          <Icon className="w-3.5 h-3.5" />
        </div>
        <span className="text-xs text-gray-500">{label}</span>
      </div>
      <p className="text-xl font-bold text-white">{value}</p>
      {sub && <p className="text-[11px] text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

/* ── Page ──────────────────────────────────────────────────────── */

export default function CampaignDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const campaignId = params.id as string;
  const adAccountId = searchParams.get("ad_account_id") || "";

  const [datePreset, setDatePreset] = useState("last_7d");
  const [data, setData] = useState<CampaignDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!campaignId || !adAccountId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.getCampaignDetail(adAccountId, campaignId, datePreset)
      .then((res: { data: CampaignDetail }) => {
        if (!cancelled) {
          const d = (res as { data: CampaignDetail }).data ?? res;
          setData(d);
          setLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message || "Failed to load campaign detail");
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [campaignId, adAccountId, datePreset]);

  const s = data?.summary;
  const isLead = s?.result_type === "leads";

  return (
    <div className="p-8 w-full animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={() => router.push("/dashboard/campaigns")}
          className="w-9 h-9 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center hover:bg-white/[0.08] transition-all"
        >
          <ArrowLeft className="w-4 h-4 text-gray-400" />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-bold text-white truncate">
            {s?.campaign_name || "Campaign Detail"}
          </h1>
          {s && !s.no_data && (
            <p className="text-xs text-gray-500 mt-0.5">
              {s.date_start} to {s.date_stop}
            </p>
          )}
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

      {/* Error */}
      {error && !loading && (
        <div className="glass rounded-2xl p-6 border border-red-500/20 bg-red-500/[0.05] text-center">
          <p className="text-sm text-red-300">{error}</p>
        </div>
      )}

      {/* No data */}
      {!loading && !error && s?.no_data && (
        <div className="flex flex-col items-center justify-center py-32 text-gray-500">
          <p className="text-lg font-medium">No data available</p>
          <p className="text-sm mt-1">This campaign has no performance data for the selected period.</p>
        </div>
      )}

      {/* Content */}
      {!loading && !error && s && !s.no_data && (
        <div className="space-y-6">

          {/* ── Summary Metric Cards ───────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            <StatCard label="Spend" value={`$${s.spend.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} icon={DollarSign} color="bg-emerald-500/10 text-emerald-400" />
            <StatCard
              label={isLead ? "CPL" : "ROAS"}
              value={isLead ? (s.cost_per_result ? `$${s.cost_per_result.toFixed(2)}` : "--") : (s.roas != null ? `${s.roas.toFixed(2)}x` : "--")}
              icon={TrendingUp}
              color="bg-violet-500/10 text-violet-400"
            />
            <StatCard label={isLead ? "Leads" : "Purchases"} value={String(s.results)} icon={Target} color="bg-amber-500/10 text-amber-400" />
            <StatCard label="Impressions" value={s.impressions.toLocaleString()} icon={Eye} color="bg-blue-500/10 text-blue-400" />
            <StatCard label="CTR" value={`${s.ctr.toFixed(2)}%`} sub={`CPC: $${s.cpc.toFixed(2)}`} icon={MousePointerClick} color="bg-cyan-500/10 text-cyan-400" />
            <StatCard label="Reach" value={s.reach.toLocaleString()} sub={`Freq: ${s.frequency.toFixed(1)}`} icon={Users} color="bg-pink-500/10 text-pink-400" />
          </div>

          {/* Funnel (only if pixel events exist) */}
          {(s.add_to_cart > 0 || s.initiate_checkout > 0 || s.purchases > 0) && (
            <GlassCard>
              <h3 className="text-sm font-semibold text-gray-300 mb-3">Conversion Funnel</h3>
              <div className="flex items-center gap-4">
                {[
                  { label: "Link Clicks", val: s.link_clicks },
                  { label: "Add to Cart", val: s.add_to_cart },
                  { label: "Checkout", val: s.initiate_checkout },
                  { label: "Purchases", val: s.purchases },
                ].map((step, i, arr) => (
                  <div key={step.label} className="flex items-center gap-4">
                    <div className="text-center">
                      <p className="text-2xl font-bold text-white">{step.val}</p>
                      <p className="text-[11px] text-gray-500">{step.label}</p>
                    </div>
                    {i < arr.length - 1 && (
                      <div className="text-gray-600 text-lg">&#8594;</div>
                    )}
                  </div>
                ))}
              </div>
            </GlassCard>
          )}

          {/* ── Charts ──────────────────────────────────────────────── */}
          {data!.daily.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Spend Over Time */}
              <GlassCard className="lg:col-span-2">
                <h3 className="text-sm font-semibold text-gray-300 mb-4">Spend Over Time</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={data!.daily}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <Tooltip {...tooltipProps} />
                    <Line type="monotone" dataKey="spend" stroke="#3b82f6" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </GlassCard>

              {/* ROAS / CPL Trend */}
              <GlassCard>
                <h3 className="text-sm font-semibold text-gray-300 mb-4">
                  {isLead ? "Cost Per Lead Trend" : "ROAS Trend"}
                </h3>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={data!.daily}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <Tooltip {...tooltipProps} />
                    {!isLead && (
                      <ReferenceLine y={1.0} stroke="#ef4444" strokeDasharray="4 4" label={{ value: "Break-even", fill: "#ef4444", fontSize: 11 }} />
                    )}
                    <Line type="monotone" dataKey={isLead ? "cost_per_result" : "roas"} stroke="#8b5cf6" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </GlassCard>

              {/* CTR Trend */}
              <GlassCard>
                <h3 className="text-sm font-semibold text-gray-300 mb-4">CTR Trend</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={data!.daily}>
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
                  {isLead ? "Leads" : "Purchases"} Over Time
                </h3>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={data!.daily}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <Tooltip {...tooltipProps} />
                    <Bar dataKey="results" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </GlassCard>

              {/* Impressions Over Time */}
              <GlassCard>
                <h3 className="text-sm font-semibold text-gray-300 mb-4">Impressions Over Time</h3>
                <ResponsiveContainer width="100%" height={260}>
                  <AreaChart data={data!.daily}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                    <Tooltip {...tooltipProps} />
                    <Area type="monotone" dataKey="impressions" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.1} strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </GlassCard>
            </div>
          )}

          {/* ── Breakdowns ──────────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Age Breakdown */}
            {data!.breakdowns.by_age.length > 0 && (
              <GlassCard>
                <h3 className="text-sm font-semibold text-gray-300 mb-4">By Age</h3>
                <div className="space-y-2">
                  {data!.breakdowns.by_age
                    .sort((a, b) => b.spend - a.spend)
                    .map((row, i) => {
                      const maxSpend = data!.breakdowns.by_age[0]?.spend || 1;
                      return (
                        <div key={i} className="flex items-center gap-3 text-xs">
                          <span className="w-12 text-gray-400 font-medium shrink-0">{row.age}</span>
                          <div className="flex-1 h-5 bg-white/[0.04] rounded-full overflow-hidden">
                            <div className="h-full bg-blue-500/30 rounded-full" style={{ width: `${(row.spend / maxSpend) * 100}%` }} />
                          </div>
                          <span className="w-16 text-right text-white font-medium">${row.spend.toFixed(0)}</span>
                          <span className="w-12 text-right text-gray-500">{row.results} {isLead ? "L" : "P"}</span>
                        </div>
                      );
                    })}
                </div>
              </GlassCard>
            )}

            {/* Gender Breakdown */}
            {data!.breakdowns.by_gender.length > 0 && (
              <GlassCard>
                <h3 className="text-sm font-semibold text-gray-300 mb-4">By Gender</h3>
                <div className="space-y-2">
                  {data!.breakdowns.by_gender
                    .sort((a, b) => b.spend - a.spend)
                    .map((row, i) => {
                      const maxSpend = data!.breakdowns.by_gender[0]?.spend || 1;
                      const label = row.gender === "male" ? "Male" : row.gender === "female" ? "Female" : row.gender || "Unknown";
                      return (
                        <div key={i} className="flex items-center gap-3 text-xs">
                          <span className="w-16 text-gray-400 font-medium shrink-0">{label}</span>
                          <div className="flex-1 h-5 bg-white/[0.04] rounded-full overflow-hidden">
                            <div className="h-full bg-violet-500/30 rounded-full" style={{ width: `${(row.spend / maxSpend) * 100}%` }} />
                          </div>
                          <span className="w-16 text-right text-white font-medium">${row.spend.toFixed(0)}</span>
                          <span className="w-12 text-right text-gray-500">{row.results} {isLead ? "L" : "P"}</span>
                        </div>
                      );
                    })}
                </div>
              </GlassCard>
            )}

            {/* Placement Breakdown */}
            {data!.breakdowns.by_placement.length > 0 && (
              <GlassCard>
                <h3 className="text-sm font-semibold text-gray-300 mb-4">By Placement</h3>
                <div className="space-y-2">
                  {data!.breakdowns.by_placement
                    .sort((a, b) => b.spend - a.spend)
                    .slice(0, 10)
                    .map((row, i) => {
                      const maxSpend = data!.breakdowns.by_placement[0]?.spend || 1;
                      const label = `${row.publisher_platform} / ${row.platform_position}`;
                      return (
                        <div key={i} className="flex items-center gap-3 text-xs">
                          <span className="w-28 text-gray-400 font-medium shrink-0 truncate" title={label}>{label}</span>
                          <div className="flex-1 h-5 bg-white/[0.04] rounded-full overflow-hidden">
                            <div className="h-full bg-emerald-500/30 rounded-full" style={{ width: `${(row.spend / maxSpend) * 100}%` }} />
                          </div>
                          <span className="w-16 text-right text-white font-medium">${row.spend.toFixed(0)}</span>
                          <span className="w-12 text-right text-gray-500">{row.results} {isLead ? "L" : "P"}</span>
                        </div>
                      );
                    })}
                </div>
              </GlassCard>
            )}
          </div>

          {/* ── Pixel Analytics ──────────────────────────────────────── */}
          {data!.pixel && data!.pixel.events.length > 0 && (() => {
            const px = data!.pixel!;
            // Pick top events for the daily chart (max 4)
            const chartEvents = px.events.slice(0, 4).map((e) => e.event);
            const EVENT_COLORS: Record<string, string> = {
              Purchase: "#10b981",
              AddToCart: "#f59e0b",
              InitiateCheckout: "#8b5cf6",
              ViewContent: "#3b82f6",
              Lead: "#ec4899",
              CompleteRegistration: "#06b6d4",
              AddPaymentInfo: "#f97316",
              Search: "#6366f1",
            };
            return (
              <div className="space-y-4">
                {/* Pixel Header */}
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-xl bg-emerald-500/10 flex items-center justify-center">
                    <Crosshair className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white">Pixel Analytics</h3>
                    <p className="text-[11px] text-gray-500">
                      {px.pixel_name || "Meta Pixel"}{px.pixel_id ? ` (${px.pixel_id})` : ""}
                    </p>
                  </div>
                </div>

                {/* Pixel Event Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {px.events.map((ev) => (
                    <div key={ev.event} className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <div
                          className="w-2 h-2 rounded-full"
                          style={{ backgroundColor: EVENT_COLORS[ev.event] || "#6b7280" }}
                        />
                        <span className="text-[11px] text-gray-500">{ev.event.replace(/([A-Z])/g, " $1").trim()}</span>
                      </div>
                      <p className="text-xl font-bold text-white">{ev.count.toLocaleString()}</p>
                      <div className="flex items-center gap-3 mt-1">
                        {ev.value != null && ev.value > 0 && (
                          <span className="text-[11px] text-emerald-400">
                            ${ev.value.toLocaleString(undefined, { maximumFractionDigits: 0 })} value
                          </span>
                        )}
                        {ev.cost_per != null && ev.cost_per > 0 && (
                          <span className="text-[11px] text-gray-500">
                            ${ev.cost_per.toFixed(2)} each
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Pixel Conversion Funnel (visual) */}
                {(() => {
                  const funnelOrder = ["ViewContent", "AddToCart", "InitiateCheckout", "Purchase"];
                  const funnelEvents = funnelOrder
                    .map((name) => px.events.find((e) => e.event === name))
                    .filter(Boolean) as PixelEvent[];
                  if (funnelEvents.length >= 2) {
                    const maxCount = Math.max(...funnelEvents.map((e) => e.count));
                    return (
                      <GlassCard>
                        <h3 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
                          <Activity className="w-4 h-4 text-emerald-400" />
                          Pixel Conversion Funnel
                        </h3>
                        <div className="space-y-2">
                          {funnelEvents.map((ev, i) => {
                            const pct = maxCount > 0 ? (ev.count / maxCount) * 100 : 0;
                            const dropoff = i > 0 ? (1 - ev.count / funnelEvents[i - 1].count) * 100 : null;
                            return (
                              <div key={ev.event} className="flex items-center gap-3">
                                <span className="w-28 text-xs text-gray-400 font-medium shrink-0">
                                  {ev.event.replace(/([A-Z])/g, " $1").trim()}
                                </span>
                                <div className="flex-1 h-8 bg-white/[0.04] rounded-lg overflow-hidden relative">
                                  <div
                                    className="h-full rounded-lg transition-all duration-500"
                                    style={{
                                      width: `${pct}%`,
                                      backgroundColor: EVENT_COLORS[ev.event] || "#6b7280",
                                      opacity: 0.35,
                                    }}
                                  />
                                  <span className="absolute inset-0 flex items-center px-3 text-xs text-white font-medium">
                                    {ev.count.toLocaleString()}
                                    {ev.value != null && ev.value > 0 && (
                                      <span className="ml-2 text-emerald-400/70 text-[10px]">
                                        ${ev.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                                      </span>
                                    )}
                                  </span>
                                </div>
                                {dropoff != null && (
                                  <span className="w-16 text-right text-[10px] text-red-400/70 shrink-0">
                                    -{dropoff.toFixed(0)}%
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </GlassCard>
                    );
                  }
                  return null;
                })()}

                {/* Daily Pixel Events Chart */}
                {px.daily_events.length > 0 && (
                  <GlassCard>
                    <h3 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
                      <Activity className="w-4 h-4 text-emerald-400" />
                      Daily Pixel Events
                    </h3>
                    <ResponsiveContainer width="100%" height={280}>
                      <BarChart data={px.daily_events}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                        <XAxis dataKey="date" tick={{ fill: "#6b7280", fontSize: 12 }} />
                        <YAxis tick={{ fill: "#6b7280", fontSize: 12 }} />
                        <Tooltip {...tooltipProps} />
                        {chartEvents.map((eventName) => (
                          <Bar
                            key={eventName}
                            dataKey={eventName}
                            fill={EVENT_COLORS[eventName] || "#6b7280"}
                            radius={[2, 2, 0, 0]}
                            stackId="pixel"
                          />
                        ))}
                      </BarChart>
                    </ResponsiveContainer>
                    <div className="flex flex-wrap gap-4 mt-3">
                      {chartEvents.map((eventName) => (
                        <div key={eventName} className="flex items-center gap-1.5 text-[11px] text-gray-400">
                          <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: EVENT_COLORS[eventName] || "#6b7280" }} />
                          {eventName.replace(/([A-Z])/g, " $1").trim()}
                        </div>
                      ))}
                    </div>
                  </GlassCard>
                )}
              </div>
            );
          })()}

          {/* ── Ads Table ──────────────────────────────────────────── */}
          {data!.ads.length > 0 && (
            <GlassCard>
              <h3 className="text-sm font-semibold text-gray-300 mb-4">Ads ({data!.ads.length})</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.06]">
                      <th className="text-left text-gray-500 font-medium py-2 px-2">Ad</th>
                      <th className="text-left text-gray-500 font-medium py-2 px-2">Status</th>
                      <th className="text-right text-gray-500 font-medium py-2 px-2">Spend</th>
                      <th className="text-right text-gray-500 font-medium py-2 px-2">{isLead ? "CPL" : "ROAS"}</th>
                      <th className="text-right text-gray-500 font-medium py-2 px-2">CTR</th>
                      <th className="text-right text-gray-500 font-medium py-2 px-2">{isLead ? "Leads" : "Purchases"}</th>
                      <th className="text-right text-gray-500 font-medium py-2 px-2">Verdict</th>
                      <th className="text-right text-gray-500 font-medium py-2 px-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {data!.ads
                      .sort((a, b) => b.spend - a.spend)
                      .map((ad) => {
                        const v = VERDICT_STYLES[ad.verdict] ?? VERDICT_STYLES.no_data;
                        return (
                          <tr key={ad.id} className="border-b border-white/[0.04] hover:bg-white/[0.02]">
                            <td className="py-3 px-2">
                              <div className="flex items-center gap-2">
                                <div className="w-8 h-8 rounded-lg bg-white/[0.04] flex items-center justify-center shrink-0 overflow-hidden">
                                  {ad.thumbnail_url ? (
                                    <img src={ad.thumbnail_url} alt="" className="w-full h-full object-cover" />
                                  ) : (
                                    <Eye className="w-3 h-3 text-gray-600" />
                                  )}
                                </div>
                                <span className="text-white font-medium truncate max-w-[200px]">{ad.name}</span>
                              </div>
                            </td>
                            <td className="py-3 px-2">
                              <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold ${ad.effective_status === "ACTIVE" ? "bg-emerald-500/10 text-emerald-400" : "bg-gray-500/10 text-gray-400"}`}>
                                {ad.effective_status}
                              </span>
                            </td>
                            <td className="py-3 px-2 text-right text-white font-medium">${ad.spend.toFixed(0)}</td>
                            <td className="py-3 px-2 text-right text-white font-medium">
                              {isLead
                                ? (ad.cost_per_result && ad.cost_per_result > 0 ? `$${ad.cost_per_result.toFixed(0)}` : "--")
                                : (ad.roas != null ? `${ad.roas.toFixed(2)}x` : "--")}
                            </td>
                            <td className="py-3 px-2 text-right text-white">{ad.ctr.toFixed(2)}%</td>
                            <td className="py-3 px-2 text-right text-white font-medium">{ad.results}</td>
                            <td className="py-3 px-2 text-right">
                              <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold border ${v.bg}`}>
                                {v.icon} {v.label}
                              </span>
                            </td>
                            <td className="py-3 px-2 text-right">
                              <button
                                onClick={() => router.push(`/dashboard/copilot?ad_id=${ad.id}&campaign_id=${campaignId}&ad_name=${encodeURIComponent(ad.name)}`)}
                                className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-violet-500/10 text-violet-400 hover:bg-violet-500/20 border border-violet-500/20 transition-all"
                              >
                                <Sparkles className="w-3 h-3" />
                                AI
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
        </div>
      )}
    </div>
  );
}
