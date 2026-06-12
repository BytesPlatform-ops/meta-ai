"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import {
  Crosshair,
  Plus,
  CheckCircle2,
  Loader2,
  Activity,
  Code2,
  Copy,
  Check,
  RefreshCw,
  AlertCircle,
  X,
} from "lucide-react";

type Pixel = { id: string; name: string };
type PixelEvent = { event: string; count: number };
type PixelStatus = {
  events: PixelEvent[];
  last_fired_time: string | null;
  is_unavailable: boolean;
};

const formatRelativeTime = (iso: string | null): string => {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (isNaN(then)) return "never";
  const diff = Date.now() - then;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} min ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} hr ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
};

const isRecentFire = (iso: string | null): boolean => {
  if (!iso) return false;
  const then = new Date(iso).getTime();
  if (isNaN(then)) return false;
  return Date.now() - then < 24 * 3_600_000; // last 24h
};

const baseSnippet = (pixelId: string) => `<!-- Meta Pixel Code -->
<script>
!function(f,b,e,v,n,t,s)
{if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};
if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];
s.parentNode.insertBefore(t,s)}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '${pixelId}');
fbq('track', 'PageView');
</script>
<noscript><img height="1" width="1" style="display:none"
  src="https://www.facebook.com/tr?id=${pixelId}&ev=PageView&noscript=1"
/></noscript>
<!-- End Meta Pixel Code -->`;

type EventTemplate = {
  event: string;
  label: string;
  whereToUse: string;
  example: string;
  noteForUser?: string;
};

const EVENT_TEMPLATES: EventTemplate[] = [
  {
    event: "CompleteRegistration",
    label: "Sign-up / Registration",
    whereToUse: "Place on the signup-success page (after a user creates an account)",
    example: `<script>
  fbq('track', 'CompleteRegistration', {
    content_name: 'Account Created',
    status: true
  });
</script>`,
    noteForUser: "Best paired with the OUTCOME_LEADS objective + COMPLETE_REGISTRATION conversion event.",
  },
  {
    event: "Lead",
    label: "Lead form submission",
    whereToUse: "Place on the form-submission thank-you page (or fire on submit)",
    example: `<script>
  fbq('track', 'Lead', {
    content_name: 'Contact Form',
    value: 0.00,
    currency: 'USD'
  });
</script>`,
    noteForUser: "Use this for contact forms, demo requests, newsletter signups.",
  },
  {
    event: "Purchase",
    label: "Purchase / Order completed",
    whereToUse: "Place on the order-confirmation page — replace the value with the actual order total",
    example: `<script>
  fbq('track', 'Purchase', {
    value: 49.99,
    currency: 'USD',
    content_ids: ['SKU-123'],
    content_type: 'product'
  });
</script>`,
    noteForUser: "Required for OUTCOME_SALES + PURCHASE conversion event campaigns. Pass the dynamic order total, not a hardcoded number.",
  },
  {
    event: "InitiateCheckout",
    label: "Initiate Checkout",
    whereToUse: "Place on the checkout page (when a user starts checkout)",
    example: `<script>
  fbq('track', 'InitiateCheckout', {
    num_items: 1,
    value: 49.99,
    currency: 'USD'
  });
</script>`,
  },
  {
    event: "AddToCart",
    label: "Add to Cart",
    whereToUse: "Fire on the 'Add to Cart' button click",
    example: `<script>
  fbq('track', 'AddToCart', {
    content_ids: ['SKU-123'],
    content_type: 'product',
    value: 49.99,
    currency: 'USD'
  });
</script>`,
  },
  {
    event: "ViewContent",
    label: "View Content",
    whereToUse: "Place on product detail / important content pages",
    example: `<script>
  fbq('track', 'ViewContent', {
    content_ids: ['SKU-123'],
    content_type: 'product',
    value: 49.99,
    currency: 'USD'
  });
</script>`,
  },
  {
    event: "Subscribe",
    label: "Subscribe",
    whereToUse: "Place on the subscription-confirmation page",
    example: `<script>
  fbq('track', 'Subscribe', {
    value: 9.99,
    currency: 'USD',
    predicted_ltv: 120.00
  });
</script>`,
  },
  {
    event: "Contact",
    label: "Contact",
    whereToUse: "Fire when a user contacts your business (chat opened, call clicked, email link clicked)",
    example: `<script>
  fbq('track', 'Contact');
</script>`,
  },
  {
    event: "Schedule",
    label: "Schedule (booking)",
    whereToUse: "Place on the booking-confirmation page",
    example: `<script>
  fbq('track', 'Schedule');
</script>`,
  },
  {
    event: "AddPaymentInfo",
    label: "Add Payment Info",
    whereToUse: "Fire when a user adds payment details during checkout",
    example: `<script>
  fbq('track', 'AddPaymentInfo', {
    currency: 'USD'
  });
</script>`,
  },
];

export default function PixelsPage() {
  const [pixels, setPixels] = useState<Pixel[]>([]);
  const [activePixelId, setActivePixelId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create modal
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Per-pixel state
  const [savingId, setSavingId] = useState<string | null>(null);
  const [statusById, setStatusById] = useState<Record<string, PixelStatus>>({});
  const [loadingEventsId, setLoadingEventsId] = useState<string | null>(null);
  const [snippetOpenId, setSnippetOpenId] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [pixRes, statsRes] = await Promise.all([
        api.listPixels(),
        api.getAudienceStats().catch(() => ({ data: { pixel_id: null } })),
      ]);
      setPixels(pixRes.data.pixels || []);
      const stats = (statsRes as { data: { pixel_id: string | null } }).data;
      setActivePixelId(stats?.pixel_id || null);
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail || err?.message || "Failed to load pixels");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    setCreating(true);
    setCreateError(null);
    try {
      const { data } = await api.createPixel(newName.trim() || undefined);
      const newId = (data as { pixel_id?: string; id?: string })?.pixel_id || (data as { id?: string })?.id;
      setShowCreate(false);
      setNewName("");
      await load();
      // Auto-select newly created pixel as active (the create endpoint already saves it)
      if (newId) setActivePixelId(newId);
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setCreateError(err?.response?.data?.detail || err?.message || "Pixel creation failed");
    } finally {
      setCreating(false);
    }
  };

  const handleSetActive = async (pixelId: string) => {
    setSavingId(pixelId);
    try {
      await api.savePixel(pixelId);
      setActivePixelId(pixelId);
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail || err?.message || "Could not save active pixel");
    } finally {
      setSavingId(null);
    }
  };

  const handleClearActive = async () => {
    setSavingId("__clear__");
    try {
      await api.savePixel(null);
      setActivePixelId(null);
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail || err?.message || "Could not clear active pixel");
    } finally {
      setSavingId(null);
    }
  };

  const loadEvents = async (pixelId: string) => {
    if (statusById[pixelId]) return;
    setLoadingEventsId(pixelId);
    try {
      const { data } = await api.getPixelEvents(pixelId);
      setStatusById((prev) => ({
        ...prev,
        [pixelId]: {
          events: data.events || [],
          last_fired_time: data.last_fired_time || null,
          is_unavailable: !!data.is_unavailable,
        },
      }));
    } catch {
      setStatusById((prev) => ({
        ...prev,
        [pixelId]: { events: [], last_fired_time: null, is_unavailable: false },
      }));
    } finally {
      setLoadingEventsId(null);
    }
  };

  const copyToClipboard = (key: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1500);
  };

  return (
    <div className="p-8 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Crosshair className="w-5 h-5 text-blue-400" /> Pixels
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage Meta Pixels for this workspace. The active pixel is used for conversion-optimized ads and audience tracking.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium bg-white/[0.03] border border-white/[0.06] text-gray-400 hover:text-white hover:bg-white/[0.06] transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all glow-blue"
          >
            <Plus className="w-3.5 h-3.5" />
            Create Pixel
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl bg-red-500/[0.06] border border-red-500/20">
          <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
          <p className="text-xs text-red-300">{error}</p>
        </div>
      )}

      {/* Active pixel highlight */}
      {activePixelId && (
        <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.04] p-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/15 border border-emerald-500/20 flex items-center justify-center shrink-0">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-wider text-emerald-400 font-semibold mb-0.5">Active pixel</p>
              <p className="text-sm text-white font-medium truncate">
                {pixels.find((p) => p.id === activePixelId)?.name || "(name unavailable)"}
              </p>
              <p className="text-[11px] text-gray-500 font-mono">{activePixelId}</p>
            </div>
          </div>
          <button
            onClick={handleClearActive}
            disabled={savingId === "__clear__"}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-500 hover:text-red-400 bg-white/[0.03] hover:bg-red-500/[0.06] border border-white/[0.06] hover:border-red-500/20 transition-all disabled:opacity-50"
          >
            {savingId === "__clear__" ? <Loader2 className="w-3 h-3 animate-spin" /> : <X className="w-3 h-3" />}
            Unset
          </button>
        </div>
      )}

      {/* Pixels list */}
      <div className="space-y-3">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-600 px-1">All pixels on this ad account</p>

        {loading ? (
          <div className="flex items-center gap-2 text-gray-500 text-sm py-6 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading pixels...
          </div>
        ) : pixels.length === 0 ? (
          <div className="rounded-2xl border border-white/[0.06] bg-[#0a0a0f]/60 p-8 text-center">
            <Crosshair className="w-8 h-8 text-gray-700 mx-auto mb-3" />
            <p className="text-sm text-gray-400 font-medium mb-1">No pixels yet</p>
            <p className="text-xs text-gray-600 mb-4">Create your first Meta Pixel to track conversions and build audiences.</p>
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-blue-600 to-violet-600 text-white"
            >
              <Plus className="w-3.5 h-3.5" />
              Create Pixel
            </button>
          </div>
        ) : (
          pixels.map((pixel) => {
            const isActive = pixel.id === activePixelId;
            const status = statusById[pixel.id];
            const events = status?.events;
            const eventsOpen = !!status;
            return (
              <div
                key={pixel.id}
                className={`rounded-2xl border p-4 transition-all ${
                  isActive
                    ? "border-emerald-500/20 bg-emerald-500/[0.02]"
                    : "border-white/[0.06] bg-[#0a0a0f]/60 hover:border-white/[0.10]"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
                      isActive
                        ? "bg-emerald-500/15 border border-emerald-500/20"
                        : "bg-white/[0.04] border border-white/[0.06]"
                    }`}>
                      <Crosshair className={`w-4 h-4 ${isActive ? "text-emerald-400" : "text-gray-500"}`} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm text-white font-medium truncate">{pixel.name}</p>
                        {isActive && (
                          <span className="px-1.5 py-0.5 rounded-md bg-emerald-500/15 text-[10px] text-emerald-400 font-semibold uppercase tracking-wider">
                            Active
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-gray-500 font-mono">{pixel.id}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        if (eventsOpen) {
                          setStatusById((prev) => {
                            const next = { ...prev };
                            delete next[pixel.id];
                            return next;
                          });
                        } else {
                          loadEvents(pixel.id);
                        }
                      }}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] transition-all"
                    >
                      {loadingEventsId === pixel.id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Activity className="w-3 h-3" />
                      )}
                      Events
                    </button>
                    <button
                      onClick={() => setSnippetOpenId(snippetOpenId === pixel.id ? null : pixel.id)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-gray-400 hover:text-white bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] transition-all"
                    >
                      <Code2 className="w-3 h-3" />
                      Install
                    </button>
                    {!isActive && (
                      <button
                        onClick={() => handleSetActive(pixel.id)}
                        disabled={savingId === pixel.id}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 transition-all disabled:opacity-50"
                      >
                        {savingId === pixel.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                        Set Active
                      </button>
                    )}
                  </div>
                </div>

                {/* Events panel */}
                {eventsOpen && status && (
                  <div className="mt-4 pt-4 border-t border-white/[0.06] space-y-3">
                    {/* Heartbeat row — last_fired_time is real-time, /stats lags */}
                    <div className="flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-white/[0.02] border border-white/[0.06]">
                      <div className="flex items-center gap-2">
                        <span className={`relative flex w-2 h-2`}>
                          {isRecentFire(status.last_fired_time) && (
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                          )}
                          <span className={`relative inline-flex rounded-full h-2 w-2 ${
                            isRecentFire(status.last_fired_time) ? "bg-emerald-400"
                              : status.last_fired_time ? "bg-amber-400" : "bg-gray-600"
                          }`}></span>
                        </span>
                        <span className="text-[11px] text-gray-400 font-medium">
                          {status.is_unavailable
                            ? "Pixel unavailable"
                            : status.last_fired_time
                              ? `Last fired ${formatRelativeTime(status.last_fired_time)}`
                              : "Pixel has never fired"}
                        </span>
                      </div>
                      {status.last_fired_time && (
                        <span className="text-[10px] text-gray-600 font-mono">
                          {new Date(status.last_fired_time).toLocaleString()}
                        </span>
                      )}
                    </div>

                    {/* Aggregated stats — laggy by 2-24 hr per Meta */}
                    {events && events.length === 0 ? (
                      isRecentFire(status.last_fired_time) ? (
                        <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-blue-500/[0.06] border border-blue-500/20">
                          <Activity className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
                          <div>
                            <p className="text-[11px] font-medium text-blue-300">Pixel is firing — aggregated stats catching up</p>
                            <p className="text-[10px] text-blue-400/70 mt-0.5 leading-snug">
                              Meta&apos;s <code className="px-1 py-0.5 rounded bg-blue-500/10 text-blue-300">/stats</code> aggregation endpoint has a 2–24 hr lag for newly-firing pixels. The heartbeat above is real-time and confirms events are reaching Meta. Aggregated counts will appear here within a day.
                            </p>
                          </div>
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500 text-center py-2">
                          No events recorded yet. Install the snippet on your site and trigger a PageView.
                        </p>
                      )
                    ) : events && events.length > 0 ? (
                      <>
                        <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">Last 30 days · aggregated</p>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                          {events.map((ev) => (
                            <div key={ev.event} className="px-3 py-2 rounded-lg bg-white/[0.03] border border-white/[0.06]">
                              <p className="text-[11px] text-gray-500 mb-0.5">{ev.event}</p>
                              <div className="flex items-baseline gap-2">
                                <span className="text-base font-bold text-white">{(ev.count ?? 0).toLocaleString()}</span>
                                <span className="text-[10px] text-gray-600">events</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : null}
                  </div>
                )}

                {/* Install snippet panel */}
                {snippetOpenId === pixel.id && (
                  <div className="mt-4 pt-4 border-t border-white/[0.06] space-y-5">
                    {/* Step 1 — Base pixel */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wider text-blue-400 mb-0.5">Step 1 — Base pixel</p>
                          <p className="text-[11px] text-gray-500">
                            Paste this inside the <code className="px-1 py-0.5 rounded bg-white/[0.05] text-violet-300 text-[10px]">&lt;head&gt;</code> tag of every page on your site. This loads the pixel and fires PageView automatically.
                          </p>
                        </div>
                        <button
                          onClick={() => copyToClipboard(`base:${pixel.id}`, baseSnippet(pixel.id))}
                          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-white/[0.05] hover:bg-white/[0.08] text-gray-300 border border-white/[0.06] transition-all shrink-0"
                        >
                          {copiedKey === `base:${pixel.id}` ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                          {copiedKey === `base:${pixel.id}` ? "Copied" : "Copy"}
                        </button>
                      </div>
                      <pre className="p-3 rounded-lg bg-black/40 border border-white/[0.06] text-[10px] text-gray-300 overflow-auto max-h-64 leading-snug font-mono">
                        {baseSnippet(pixel.id)}
                      </pre>
                    </div>

                    {/* Step 2 — Conversion events */}
                    <div className="space-y-3">
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-violet-400 mb-0.5">Step 2 — Conversion events</p>
                        <p className="text-[11px] text-gray-500">
                          Add these on specific pages where the action happens — signup success, checkout, order confirmation, etc. Each one tells Meta a specific conversion fired so it can optimize your ads.
                        </p>
                      </div>
                      <div className="space-y-2">
                        {EVENT_TEMPLATES.map((tpl) => {
                          const key = `evt:${pixel.id}:${tpl.event}`;
                          return (
                            <div key={tpl.event} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                              <div className="flex items-start justify-between gap-3 mb-1.5">
                                <div className="min-w-0">
                                  <p className="text-xs font-semibold text-white">{tpl.label}</p>
                                  <p className="text-[10px] text-gray-500">
                                    Event: <code className="px-1 py-0.5 rounded bg-violet-500/10 text-violet-300 font-mono">{tpl.event}</code>
                                  </p>
                                </div>
                                <button
                                  onClick={() => copyToClipboard(key, tpl.example)}
                                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-white/[0.05] hover:bg-white/[0.08] text-gray-300 border border-white/[0.06] transition-all shrink-0"
                                >
                                  {copiedKey === key ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                                  {copiedKey === key ? "Copied" : "Copy"}
                                </button>
                              </div>
                              <p className="text-[11px] text-gray-400 mb-1.5 italic">{tpl.whereToUse}</p>
                              <p className="text-[10px] uppercase tracking-wider text-gray-600 mb-1">Inline (base loader already on page)</p>
                              <pre className="p-2.5 rounded-lg bg-black/40 border border-white/[0.06] text-[10px] text-gray-300 overflow-auto leading-snug font-mono">
                                {tpl.example}
                              </pre>
                              <div className="flex items-center justify-between gap-2 mt-2 mb-1">
                                <p className="text-[10px] uppercase tracking-wider text-gray-600">Standalone (base loader + event in one paste — for single-page install)</p>
                                <button
                                  onClick={() => copyToClipboard(`combo:${pixel.id}:${tpl.event}`, baseSnippet(pixel.id) + "\n\n" + tpl.example)}
                                  className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium bg-violet-500/10 hover:bg-violet-500/15 text-violet-300 border border-violet-500/20 transition-all"
                                >
                                  {copiedKey === `combo:${pixel.id}:${tpl.event}` ? <Check className="w-2.5 h-2.5 text-emerald-400" /> : <Copy className="w-2.5 h-2.5" />}
                                  Copy Combo
                                </button>
                              </div>
                              <pre className="p-2.5 rounded-lg bg-violet-500/[0.04] border border-violet-500/15 text-[10px] text-gray-300 overflow-auto leading-snug font-mono max-h-32">
                                {baseSnippet(pixel.id) + "\n\n" + tpl.example}
                              </pre>
                              {tpl.noteForUser && (
                                <p className="text-[10px] text-gray-600 mt-1.5 leading-snug">💡 {tpl.noteForUser}</p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Create Pixel Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => !creating && setShowCreate(false)}>
          <div
            className="w-full max-w-md rounded-2xl bg-[#0a0a0f] border border-white/[0.08] p-6 m-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-5">
              <div>
                <h2 className="text-base font-bold text-white">Create new Pixel</h2>
                <p className="text-xs text-gray-500 mt-0.5">A fresh Meta Pixel will be created on the active ad account and set as active.</p>
              </div>
              <button
                onClick={() => !creating && setShowCreate(false)}
                disabled={creating}
                className="text-gray-500 hover:text-white transition-colors disabled:opacity-30"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <label className="block text-[10px] font-semibold uppercase tracking-widest text-gray-500 mb-2">Pixel Name</label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Quantiva Web Pixel"
              maxLength={100}
              className="w-full px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-blue-500/40 transition-all mb-3"
            />
            <p className="text-[11px] text-gray-600 mb-5">Leave blank to use the default name "AI Pixel".</p>
            {createError && (
              <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-500/[0.06] border border-red-500/20 mb-4">
                <AlertCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
                <p className="text-xs text-red-300">{createError}</p>
              </div>
            )}
            <div className="flex items-center gap-2">
              <button
                onClick={handleCreate}
                disabled={creating}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all glow-blue disabled:opacity-50"
              >
                {creating ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  <>
                    <Plus className="w-4 h-4" />
                    Create Pixel
                  </>
                )}
              </button>
              <button
                onClick={() => setShowCreate(false)}
                disabled={creating}
                className="px-4 py-2.5 rounded-xl text-sm font-medium text-gray-400 hover:text-white bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] transition-all disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
