"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import {
  Users,
  Upload,
  FileSpreadsheet,
  Loader2,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  Trash2,
  Database,
  Zap,
  Radio,
  Eye,
  ShoppingCart,
  MousePointerClick,
  UserPlus,
  Activity,
  TrendingUp,
  Info,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────────── */

type NicheStats = {
  niche: string;
  count: number;
  lal_ready: boolean;
};

type PixelEvent = {
  event: string;
  count: number;
  is_conversion: boolean;
  lal_ready: boolean;
};

type AttributedResults = {
  registrations: number;
  purchases: number;
  leads: number;
  total_results: number;
  result_type: string;
};

type AudienceStats = {
  niches: NicheStats[];
  total_db_customers: number;
  db_lal_ready_count: number;
  pixel_id: string | null;
  pixel_events: PixelEvent[];
  total_pixel_events: number;
  pixel_lal_ready: boolean;
  any_lal_ready: boolean;
  pixel_days: number;
  attributed_results: AttributedResults;
};

/* ── Event icon helper ─────────────────────────────────────────────────────── */

const EVENT_ICONS: Record<string, typeof Eye> = {
  PageView: Eye,
  ViewContent: Eye,
  CompleteRegistration: UserPlus,
  Purchase: ShoppingCart,
  Lead: UserPlus,
  AddToCart: ShoppingCart,
  InitiateCheckout: ShoppingCart,
  Subscribe: UserPlus,
};

const EVENT_COLORS: Record<string, string> = {
  CompleteRegistration: "text-emerald-400",
  Purchase: "text-amber-400",
  Lead: "text-blue-400",
  PageView: "text-gray-400",
  ViewContent: "text-violet-400",
  AddToCart: "text-orange-400",
  InitiateCheckout: "text-orange-400",
  Subscribe: "text-cyan-400",
};

/* ── Page ──────────────────────────────────────────────────────────────────── */

export default function AudiencesPage() {
  // CSV upload state
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvHeaders, setCsvHeaders] = useState<string[]>([]);
  const [csvRows, setCsvRows] = useState<string[][]>([]);
  const [emailCol, setEmailCol] = useState<string>("");
  const [phoneCol, setPhoneCol] = useState<string>("");
  const [niche, setNiche] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ success: boolean; message: string } | null>(null);

  // Audience stats (combined)
  const [stats, setStats] = useState<AudienceStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);

  // ── Load stats ──────────────────────────────────────────────────────────
  const loadStats = useCallback(async () => {
    setLoadingStats(true);
    try {
      const res = await api.getAudienceStats();
      setStats(res.data);
    } catch {
      setStats(null);
    } finally {
      setLoadingStats(false);
    }
  }, []);

  useEffect(() => { loadStats(); }, [loadStats]);

  // ── Parse CSV ───────────────────────────────────────────────────────────
  const handleFileSelect = (file: File) => {
    setCsvFile(file);
    setUploadResult(null);
    setEmailCol("");
    setPhoneCol("");

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (!text) return;

      const lines = text.split(/\r?\n/).filter((l) => l.trim());
      if (lines.length < 2) {
        setUploadResult({ success: false, message: "CSV must have a header row and at least 1 data row." });
        return;
      }

      const headers = lines[0].split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
      const rows = lines.slice(1).map((l) => l.split(",").map((c) => c.trim().replace(/^"|"$/g, "")));

      setCsvHeaders(headers);
      setCsvRows(rows);

      const emailGuess = headers.find((h) => /email|e-mail|mail/i.test(h));
      const phoneGuess = headers.find((h) => /phone|mobile|cell|whatsapp|number/i.test(h));
      if (emailGuess) setEmailCol(emailGuess);
      if (phoneGuess) setPhoneCol(phoneGuess);
    };
    reader.readAsText(file);
  };

  // ── Upload ──────────────────────────────────────────────────────────────
  const handleUpload = async () => {
    if (!niche.trim()) {
      setUploadResult({ success: false, message: "Niche is required. E.g. 'Honey', 'Website', 'BytesCart'" });
      return;
    }
    if (!emailCol && !phoneCol) {
      setUploadResult({ success: false, message: "Map at least one column — email or phone." });
      return;
    }

    const emailIdx = emailCol ? csvHeaders.indexOf(emailCol) : -1;
    const phoneIdx = phoneCol ? csvHeaders.indexOf(phoneCol) : -1;

    const customers = csvRows
      .map((row) => ({
        email: emailIdx >= 0 ? row[emailIdx]?.trim() || null : null,
        phone: phoneIdx >= 0 ? row[phoneIdx]?.trim() || null : null,
      }))
      .filter((c) => c.email || c.phone);

    if (customers.length === 0) {
      setUploadResult({ success: false, message: "No valid rows found. Check your column mapping." });
      return;
    }

    setUploading(true);
    setUploadResult(null);

    try {
      const res = await api.uploadCustomers({ customers, niche: niche.trim() });
      const inserted = res.data.inserted || customers.length;
      setUploadResult({
        success: true,
        message: `${inserted} customers uploaded for "${niche.trim()}". ${inserted >= 100 ? "LAL is ready!" : `${100 - inserted} more needed for LAL activation.`}`,
      });
      setCsvFile(null);
      setCsvHeaders([]);
      setCsvRows([]);
      setEmailCol("");
      setPhoneCol("");
      setNiche("");
      loadStats();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      setUploadResult({ success: false, message: msg });
    } finally {
      setUploading(false);
    }
  };

  // ── Derived values ─────────────────────────────────────────────────────
  const totalDbCustomers = stats?.total_db_customers ?? 0;
  const totalPixelEvents = stats?.total_pixel_events ?? 0;
  const nicheStats = stats?.niches ?? [];
  const pixelEvents = stats?.pixel_events ?? [];
  const pixelLalReady = stats?.pixel_lal_ready ?? false;
  const dbLalReadyCount = stats?.db_lal_ready_count ?? 0;
  const anyLalReady = stats?.any_lal_ready ?? false;
  const pixelId = stats?.pixel_id;
  const conversionEvents = pixelEvents.filter((e) => e.is_conversion);
  const pixelLalReadyCount = pixelEvents.filter((e) => e.lal_ready).length;
  const pixelDays = stats?.pixel_days ?? 30;
  const attributed = stats?.attributed_results;
  const attrTotal = attributed?.total_results ?? 0;
  const attrLabel = attributed?.result_type === "registrations"
    ? "Registrations" : attributed?.result_type === "purchases"
    ? "Purchases" : attributed?.result_type === "leads"
    ? "Leads" : "Results";

  return (
    <div className="p-8 space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <Users className="w-5 h-5 text-blue-400" /> Audiences
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Combined view of your Pixel data and uploaded customer lists. We automatically use either source to build Lookalike Audiences when 100+ signals are available.
        </p>
      </div>

      {/* ── Top Stats Cards ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Card 1: Ad-Attributed Results (all-time) */}
        <div className="rounded-2xl border border-blue-500/20 bg-blue-500/[0.03] p-4">
          <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2">
            <TrendingUp className="w-3.5 h-3.5 text-blue-400" /> Ad-Attributed {attrLabel}
            <span className="relative group ml-auto">
              <Info className="w-3 h-3 text-gray-600 cursor-help" />
              <span className="absolute bottom-full right-0 mb-1.5 w-56 px-2.5 py-2 rounded-lg bg-gray-900 border border-white/10 text-[10px] text-gray-400 leading-relaxed opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto transition-opacity z-50">
                Total conversions attributed to your ads by Meta (all-time). Includes view-through and click-through attribution.
              </span>
            </span>
          </div>
          <div className="text-2xl font-bold text-white">
            {loadingStats ? <Loader2 className="w-5 h-5 animate-spin text-gray-600" /> : attrTotal.toLocaleString()}
          </div>
          <p className="text-[10px] text-gray-600 mt-1">All-time campaign insights</p>
        </div>

        {/* Card 2: Pixel Events (last 30 days) */}
        <div className={`rounded-2xl border p-4 ${
          pixelId
            ? "border-violet-500/20 bg-violet-500/[0.03]"
            : "border-white/[0.06] bg-[#0a0a0f]/60"
        }`}>
          <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2">
            <Radio className="w-3.5 h-3.5 text-violet-400" /> Raw Pixel Events
            <span className="relative group ml-auto">
              <Info className="w-3 h-3 text-gray-600 cursor-help" />
              <span className="absolute bottom-full right-0 mb-1.5 w-56 px-2.5 py-2 rounded-lg bg-gray-900 border border-white/10 text-[10px] text-gray-400 leading-relaxed opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto transition-opacity z-50">
                Actual pixel fires on your site in the last {pixelDays} days. LAL audiences are built from these raw events.
              </span>
            </span>
          </div>
          <div className="text-2xl font-bold text-white">
            {loadingStats ? (
              <Loader2 className="w-5 h-5 animate-spin text-gray-600" />
            ) : pixelId ? (
              totalPixelEvents.toLocaleString()
            ) : (
              <span className="text-gray-600 text-lg">No pixel</span>
            )}
          </div>
          <p className="text-[10px] text-gray-600 mt-1">
            {pixelId ? `Last ${pixelDays} days` : "Connect a pixel in Settings"}
          </p>
        </div>

        {/* Card 3: DB Customers */}
        <div className="rounded-2xl border border-white/[0.06] bg-[#0a0a0f]/60 p-4">
          <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2">
            <Database className="w-3.5 h-3.5" /> DB Customers
          </div>
          <div className="text-2xl font-bold text-white">
            {loadingStats ? <Loader2 className="w-5 h-5 animate-spin text-gray-600" /> : totalDbCustomers.toLocaleString()}
          </div>
          <p className="text-[10px] text-gray-600 mt-1">CSV / Webhook uploads</p>
        </div>
      </div>

      {/* ── Secondary Row: LAL + Funnel ────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4">
        {/* LAL Sources Ready */}
        <div className="rounded-2xl border border-white/[0.06] bg-[#0a0a0f]/60 p-4">
          <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2">
            <Activity className="w-3.5 h-3.5" /> LAL Sources
          </div>
          <div className={`text-2xl font-bold ${anyLalReady ? "text-emerald-400" : "text-gray-600"}`}>
            {loadingStats ? (
              <Loader2 className="w-5 h-5 animate-spin text-gray-600" />
            ) : (
              `${dbLalReadyCount + pixelLalReadyCount}`
            )}
          </div>
          <p className="text-[10px] text-gray-600 mt-1">
            {dbLalReadyCount > 0 && `${dbLalReadyCount} niche${dbLalReadyCount > 1 ? "s" : ""}`}
            {dbLalReadyCount > 0 && pixelLalReadyCount > 0 && " + "}
            {pixelLalReadyCount > 0 && `${pixelLalReadyCount} pixel event${pixelLalReadyCount > 1 ? "s" : ""}`}
            {!dbLalReadyCount && !pixelLalReadyCount && "Need 100+ signals"}
          </p>
        </div>

        {/* Overall Funnel Status */}
        <div className={`rounded-2xl border p-4 ${
          anyLalReady
            ? "border-emerald-500/20 bg-emerald-500/[0.03]"
            : "border-white/[0.06] bg-[#0a0a0f]/60"
        }`}>
          <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2">
            <Zap className="w-3.5 h-3.5" /> Funnel Status
          </div>
          {loadingStats ? (
            <Loader2 className="w-5 h-5 animate-spin text-gray-600" />
          ) : anyLalReady ? (
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              <span className="text-sm font-semibold text-emerald-400">LAL Active</span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <AlertCircle className="w-5 h-5 text-amber-400" />
              <span className="text-sm font-semibold text-amber-400">Cold Start</span>
            </div>
          )}
          <p className="text-[10px] text-gray-600 mt-1">
            {anyLalReady
              ? "Campaigns auto-use 1% Lookalike"
              : "Using interest-based targeting"}
          </p>
        </div>
      </div>

      {/* ── Data Source Explainer ───────────────────────────────────────────── */}
      {!loadingStats && attrTotal > 0 && totalPixelEvents !== attrTotal && (
        <div className="rounded-xl border border-blue-500/10 bg-blue-500/[0.02] px-4 py-3 flex items-start gap-2.5">
          <Info className="w-4 h-4 text-blue-400 mt-0.5 shrink-0" />
          <p className="text-xs text-gray-500 leading-relaxed">
            <span className="text-gray-400 font-medium">Why do the numbers differ?</span>{" "}
            Ad-Attributed {attrLabel} ({attrTotal.toLocaleString()}) come from Meta&apos;s campaign attribution across all time.
            Raw Pixel Events ({totalPixelEvents.toLocaleString()}) are actual pixel fires on your site in the last {pixelDays} days.
            Lookalike Audiences are built using raw pixel events, which may differ from ad attribution totals.
          </p>
        </div>
      )}

      {/* ── Pixel Events Breakdown ──────────────────────────────────────────── */}
      {pixelId && pixelEvents.length > 0 && (
        <div className="rounded-2xl border border-violet-500/10 bg-[#0a0a0f]/60 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <Radio className="w-4 h-4 text-violet-400" /> Meta Pixel Events
              <span className="text-[10px] font-normal text-gray-600">(Last {pixelDays} days)</span>
            </h2>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20 font-mono">
              {pixelId}
            </span>
          </div>
          <div className="space-y-2">
            {pixelEvents.map((evt) => {
              const Icon = EVENT_ICONS[evt.event] || MousePointerClick;
              const color = EVENT_COLORS[evt.event] || "text-gray-400";
              return (
                <div key={evt.event} className="flex items-center gap-3">
                  <Icon className={`w-4 h-4 ${color} shrink-0`} />
                  <span className="text-sm text-gray-300 w-44 truncate">{evt.event}</span>
                  <div className="flex-1 h-2 rounded-full bg-white/[0.06] overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${
                        evt.lal_ready ? "bg-emerald-500" : evt.is_conversion ? "bg-violet-500/60" : "bg-white/10"
                      }`}
                      style={{ width: `${Math.min((evt.count / Math.max(...pixelEvents.map(e => e.count), 1)) * 100, 100)}%` }}
                    />
                  </div>
                  <span className={`text-xs font-mono w-20 text-right ${evt.lal_ready ? "text-emerald-400" : "text-gray-500"}`}>
                    {evt.count.toLocaleString()}
                  </span>
                  {evt.lal_ready && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium shrink-0">
                      LAL READY
                    </span>
                  )}
                  {evt.is_conversion && !evt.lal_ready && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 border border-violet-500/20 font-medium shrink-0">
                      {100 - evt.count > 0 ? `${100 - evt.count} more` : ""}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-gray-600 mt-3">
            Conversion events with 100+ fires in the last {pixelDays} days automatically generate Lookalike Audiences for new campaigns.
          </p>
        </div>
      )}

      {/* ── No Pixel Connected Banner ───────────────────────────────────────── */}
      {!loadingStats && !pixelId && (
        <div className="rounded-2xl border border-amber-500/10 bg-amber-500/[0.03] p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-amber-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm text-amber-300 font-medium">No Meta Pixel connected</p>
            <p className="text-xs text-gray-500 mt-1">
              Connect a Meta Pixel in Settings or attach one to your product to unlock pixel-based Lookalike Audiences. Without a pixel, only CSV/webhook customer data can generate LALs.
            </p>
          </div>
        </div>
      )}

      {/* ── Niche Breakdown (DB Customers) ──────────────────────────────────── */}
      {nicheStats.length > 0 && (
        <div className="rounded-2xl border border-white/[0.06] bg-[#0a0a0f]/60 p-5">
          <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <Database className="w-4 h-4 text-blue-400" /> Database Customers by Niche
          </h2>
          <div className="space-y-2">
            {nicheStats.map((n) => (
              <div key={n.niche} className="flex items-center gap-3">
                <span className="text-sm text-gray-300 w-32 truncate">{n.niche}</span>
                <div className="flex-1 h-2 rounded-full bg-white/[0.06] overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${n.lal_ready ? "bg-emerald-500" : "bg-blue-500/60"}`}
                    style={{ width: `${Math.min((n.count / 100) * 100, 100)}%` }}
                  />
                </div>
                <span className={`text-xs font-mono w-20 text-right ${n.lal_ready ? "text-emerald-400" : "text-gray-500"}`}>
                  {n.count} / 100
                </span>
                {n.lal_ready && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                    LAL ACTIVE
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* CSV Upload Section */}
      <div className="rounded-2xl border border-white/[0.06] bg-[#0a0a0f]/60 p-5">
        <h2 className="text-sm font-semibold text-white mb-1 flex items-center gap-2">
          <FileSpreadsheet className="w-4 h-4 text-blue-400" /> Upload Customer CSV
        </h2>
        <p className="text-xs text-gray-600 mb-4">
          Upload a CSV of your past customers (from Shopify, WooCommerce, Mailchimp, WhatsApp exports, etc.)
        </p>

        {/* Step 1: File Select */}
        {!csvFile ? (
          <label className="flex flex-col items-center justify-center w-full h-40 rounded-xl border-2 border-dashed border-white/[0.08] hover:border-blue-500/30 bg-white/[0.02] cursor-pointer transition-all group">
            <Upload className="w-8 h-8 text-gray-600 group-hover:text-blue-400 transition-colors mb-2" />
            <span className="text-sm text-gray-500 group-hover:text-gray-400">
              Drop CSV here or click to browse
            </span>
            <span className="text-[10px] text-gray-700 mt-1">Supports .csv files</span>
            <input
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFileSelect(f);
              }}
            />
          </label>
        ) : (
          <div className="space-y-4">
            {/* File info */}
            <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-blue-500/[0.06] border border-blue-500/10">
              <div className="flex items-center gap-2">
                <FileSpreadsheet className="w-4 h-4 text-blue-400" />
                <span className="text-sm text-blue-300">{csvFile.name}</span>
                <span className="text-xs text-gray-500">({csvRows.length} rows)</span>
              </div>
              <button
                onClick={() => {
                  setCsvFile(null);
                  setCsvHeaders([]);
                  setCsvRows([]);
                  setEmailCol("");
                  setPhoneCol("");
                  setUploadResult(null);
                }}
                className="text-gray-600 hover:text-red-400 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Step 2: Column Mapping */}
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Email Column</label>
                <div className="relative">
                  <select
                    value={emailCol}
                    onChange={(e) => setEmailCol(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-sm text-white appearance-none cursor-pointer"
                  >
                    <option value="">-- None --</option>
                    {csvHeaders.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                  <ChevronDown className="w-3.5 h-3.5 text-gray-600 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Phone Column</label>
                <div className="relative">
                  <select
                    value={phoneCol}
                    onChange={(e) => setPhoneCol(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-sm text-white appearance-none cursor-pointer"
                  >
                    <option value="">-- None --</option>
                    {csvHeaders.map((h) => (
                      <option key={h} value={h}>{h}</option>
                    ))}
                  </select>
                  <ChevronDown className="w-3.5 h-3.5 text-gray-600 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">
                  Niche <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={niche}
                  onChange={(e) => setNiche(e.target.value)}
                  placeholder="e.g. Honey, BytesCart, Website"
                  className="w-full px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-sm text-white placeholder:text-gray-700"
                />
              </div>
            </div>

            {/* Preview Table */}
            {csvRows.length > 0 && (
              <div className="rounded-lg border border-white/[0.06] overflow-hidden">
                <div className="px-3 py-2 bg-white/[0.02] border-b border-white/[0.06]">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-600">
                    Preview (first 5 rows)
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-white/[0.04]">
                        {csvHeaders.map((h) => (
                          <th
                            key={h}
                            className={`px-3 py-2 text-left font-medium ${
                              h === emailCol
                                ? "text-blue-400 bg-blue-500/[0.06]"
                                : h === phoneCol
                                ? "text-emerald-400 bg-emerald-500/[0.06]"
                                : "text-gray-600"
                            }`}
                          >
                            {h}
                            {h === emailCol && " (email)"}
                            {h === phoneCol && " (phone)"}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {csvRows.slice(0, 5).map((row, i) => (
                        <tr key={i} className="border-b border-white/[0.03]">
                          {row.map((cell, j) => (
                            <td
                              key={j}
                              className={`px-3 py-1.5 ${
                                csvHeaders[j] === emailCol
                                  ? "text-blue-300"
                                  : csvHeaders[j] === phoneCol
                                  ? "text-emerald-300"
                                  : "text-gray-500"
                              }`}
                            >
                              {cell || "\u2014"}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {csvRows.length > 5 && (
                  <div className="px-3 py-1.5 text-[10px] text-gray-700 bg-white/[0.01]">
                    ... {csvRows.length - 5} more rows
                  </div>
                )}
              </div>
            )}

            {/* Upload Button */}
            <button
              onClick={handleUpload}
              disabled={uploading || (!emailCol && !phoneCol) || !niche.trim()}
              className="w-full py-2.5 rounded-xl text-sm font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white flex items-center justify-center gap-2"
            >
              {uploading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Uploading...
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4" /> Upload {csvRows.length} customers to &quot;{niche || "..."}&quot;
                </>
              )}
            </button>
          </div>
        )}

        {/* Result Message */}
        {uploadResult && (
          <div className={`mt-3 flex items-start gap-2 px-3 py-2.5 rounded-lg text-sm ${
            uploadResult.success
              ? "bg-emerald-500/[0.06] border border-emerald-500/10 text-emerald-400"
              : "bg-red-500/[0.06] border border-red-500/10 text-red-400"
          }`}>
            {uploadResult.success ? (
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            )}
            {uploadResult.message}
          </div>
        )}
      </div>

      {/* How it works — updated for dual-source */}
      <div className="rounded-2xl border border-white/[0.06] bg-[#0a0a0f]/60 p-5">
        <h2 className="text-sm font-semibold text-white mb-3">How Lookalike Audiences Work</h2>
        <div className="grid grid-cols-3 gap-4 text-xs text-gray-500">
          <div className="space-y-1">
            <div className="w-8 h-8 rounded-lg bg-violet-500/10 flex items-center justify-center mb-2">
              <Radio className="w-4 h-4 text-violet-400" />
            </div>
            <p className="text-white font-medium">1. Data Sources</p>
            <p>Your Meta Pixel tracks visitor actions automatically. You can also upload past customer CSVs or connect webhooks.</p>
          </div>
          <div className="space-y-1">
            <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center mb-2">
              <Database className="w-4 h-4 text-blue-400" />
            </div>
            <p className="text-white font-medium">2. Reach 100+</p>
            <p>Once any source has 100+ signals, LAL auto-activates. Meta finds people similar to your best performers.</p>
          </div>
          <div className="space-y-1">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center mb-2">
              <Zap className="w-4 h-4 text-emerald-400" />
            </div>
            <p className="text-white font-medium">3. Funnel Campaigns</p>
            <p>New campaigns auto-split: 80% prospecting (LAL cold traffic) + 20% retargeting (warm pixel visitors).</p>
          </div>
        </div>
      </div>
    </div>
  );
}
