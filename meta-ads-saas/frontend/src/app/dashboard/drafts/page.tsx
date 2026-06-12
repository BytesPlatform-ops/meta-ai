"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, resolveImageUrl } from "@/lib/api";
import { useWorkspace } from "@/contexts/WorkspaceContext";
import {
  CheckCircle2,
  XCircle,
  RefreshCw,
  FileText,
  DollarSign,
  Clock,
  Sparkles,
  ImageIcon,
  Target,
  Loader2,
  Inbox,
  Filter,
  Wand2,
  Upload,
  X,
  Maximize2,
  Zap,
  Plus,
  ChevronDown,
  MessageCircle,
  ClipboardList,
  Phone,
  MessagesSquare,
  GripVertical,
  Copy,
  Check,
  ChevronRight,
  Code,
} from "lucide-react";

/* ── Types ────────────────────────────────────────────────── */

type AbVariants = {
  headline_a?: string;
  headline_b?: string;
  body_text_a?: string;
  body_text_b?: string;
};

type TargetingSpec = {
  target_country?: string;
  validated_interests?: { id: string; name: string; audience_size?: number }[];
  validated_behaviors?: { id: string; name: string; audience_size?: number }[];
  suggested_keywords?: string[];
  advantage_plus_expanded?: boolean;
};

type TargetingDiff = {
  severity: "clean" | "partial" | "heavy" | "total_strip" | "no_interests_sent";
  sent_count: number;
  kept_count: number;
  stripped_count: number;
  stripped_interests: { id: string; name: string }[];
  kept_interests: { id: string; name: string }[];
  advantage_audience_active: boolean;
  reconciled_at: string;
};

type MediaItem = {
  type: "image" | "video";
  url: string;
  thumbnail_url?: string;
};

type Draft = {
  id: string;
  draft_type: "organic" | "paid";
  status: "pending" | "approved" | "rejected" | "publishing" | "active" | "failed";
  headline: string | null;
  body_text: string;
  image_url: string | null;
  cta_type: string | null;
  proposed_budget: number | null;
  targeting: Record<string, unknown>;
  targeting_spec: TargetingSpec | string | null;
  target_country: string | null;
  ai_reasoning: string | null;
  error_message: string | null;
  meta_ad_id: string | null;
  scheduled_for: string | null;
  ab_variants: AbVariants | string | null;
  product_id: string | null;
  destination_url: string | null;
  pixel_id: string | null;
  conversion_event: string | null;
  thumbnail_url: string | null;
  destination_type: string | null;
  campaign_objective: string | null;
  is_carousel?: boolean | null;
  whatsapp_number: string | null;
  media_items: MediaItem[] | null;
  lead_form_id: string | null;
  selected_messaging_apps: string[] | null;
  call_phone_number: string | null;
  special_ad_category: string | null;
  special_ad_category_confidence: number | null;
  special_ad_category_reasoning: string | null;
  // Post-publish reconciliation against Meta's actual applied targeting.
  // Populated by sac_reconciler ~30s after a successful SAC publish.
  actual_targeting: Record<string, unknown> | null;
  targeting_diff: TargetingDiff | null;
  // Phase B SAC auto-recovery state — populated by sac_recovery when the
  // reconciler sees severity=heavy/total_strip and replacement interests
  // are PATCHed onto the live ad set.
  auto_recovery_status: string | null;       // pending | recovered | no_alternatives | llm_failed | patch_failed
  auto_recovery_attempts: number | null;
  recovered_interests: { id: string; name: string }[] | null;
  created_at: string;
};

// Meta SAC code → human label + tailwind color class.
// Tier-2 (HEC) categories use red/amber; Financial uses indigo; auth-required uses violet.
const SAC_DISPLAY: Record<string, { label: string; color: string }> = {
  HOUSING: { label: "Housing", color: "bg-amber-500/10 text-amber-300 border-amber-500/30" },
  EMPLOYMENT: { label: "Employment", color: "bg-amber-500/10 text-amber-300 border-amber-500/30" },
  CREDIT: { label: "Credit", color: "bg-amber-500/10 text-amber-300 border-amber-500/30" },
  FINANCIAL_PRODUCTS_SERVICES: { label: "Financial Products", color: "bg-indigo-500/10 text-indigo-300 border-indigo-500/30" },
  ISSUES_ELECTIONS_POLITICS: { label: "Politics / Issues", color: "bg-violet-500/10 text-violet-300 border-violet-500/30" },
  ONLINE_GAMBLING_AND_GAMING: { label: "Gambling", color: "bg-violet-500/10 text-violet-300 border-violet-500/30" },
};

type FilterTab = "all" | "pending" | "approved" | "active" | "rejected";

const FILTER_TABS: { value: FilterTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "active", label: "Active" },
  { value: "rejected", label: "Rejected" },
];

/* ── Helpers ──────────────────────────────────────────────── */

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function isVideoUrl(url: string | null): boolean {
  if (!url) return false;
  return /\.(mp4|mov|avi|mkv|webm)$/i.test(url) || url.includes("video/");
}

function getMediaItems(draft: Draft): MediaItem[] {
  if (draft.media_items && draft.media_items.length > 0) return draft.media_items;
  if (!draft.image_url) return [];
  return [{ type: isVideoUrl(draft.image_url) ? "video" : "image", url: draft.image_url }];
}

function parseAbVariants(ab_variants: AbVariants | string | null): AbVariants | null {
  if (!ab_variants) return null;
  if (typeof ab_variants === "string") {
    try { return JSON.parse(ab_variants); } catch { return null; }
  }
  return ab_variants;
}

function parseTargetingSpec(spec: TargetingSpec | string | null): TargetingSpec | null {
  if (!spec) return null;
  if (typeof spec === "string") {
    try { return JSON.parse(spec); } catch { return null; }
  }
  return spec;
}

const COUNTRY_NAMES: Record<string, string> = {
  PK: "Pakistan", US: "United States", GB: "United Kingdom",
  AE: "UAE", SA: "Saudi Arabia", IN: "India", CA: "Canada",
  AU: "Australia", DE: "Germany", FR: "France", TR: "Turkey",
  MY: "Malaysia", NG: "Nigeria", KE: "Kenya", BD: "Bangladesh",
};

/* ── Status badge ─────────────────────────────────────────── */

function StatusBadge({ status }: { status: Draft["status"] }) {
  const styles: Record<string, string> = {
    pending: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    approved: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    publishing: "bg-violet-500/10 text-violet-400 border-violet-500/20",
    active: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    rejected: "bg-gray-500/10 text-gray-400 border-gray-500/20",
    failed: "bg-red-500/10 text-red-400 border-red-500/20",
  };
  const isTransitional = status === "approved" || status === "publishing";
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold uppercase tracking-wide border ${styles[status]} ${isTransitional ? "animate-pulse" : ""}`}>
      {isTransitional && <Loader2 className="w-3 h-3 animate-spin" />}
      {status === "publishing" ? "Publishing..." : status}
    </span>
  );
}

/* ── Type badge ────────────────────────────────────────────── */

function TypeBadge({ type, onToggle }: { type: "organic" | "paid"; onToggle?: () => void }) {
  const isPaid = type === "paid";
  const base = onToggle ? "cursor-pointer hover:scale-105 active:scale-95 transition-all" : "";
  if (isPaid) {
    return (
      <span onClick={onToggle} title={onToggle ? "Click to switch to Organic (Page Post)" : undefined}
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold uppercase tracking-wide bg-violet-500/10 text-violet-400 border border-violet-500/20 ${base}`}>
        <DollarSign className="w-3 h-3" /> Paid Ad
      </span>
    );
  }
  return (
    <span onClick={onToggle} title={onToggle ? "Click to switch to Paid Ad" : undefined}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold uppercase tracking-wide bg-blue-500/10 text-blue-400 border border-blue-500/20 ${base}`}>
      <FileText className="w-3 h-3" /> Page Post
    </span>
  );
}

/* ── Conversion Events ─────────────────────────────────── */

const CONVERSION_EVENTS = [
  { value: "PURCHASE", label: "Purchase (Best for E-commerce)", desc: "Optimize for completed sales" },
  { value: "LEAD", label: "Lead (Best for Services/Forms)", desc: "Optimize for lead form submissions" },
  { value: "COMPLETE_REGISTRATION", label: "Complete Registration (Sign-ups)", desc: "Optimize for sign-ups and account creation" },
  { value: "ADD_TO_CART", label: "Add to Cart", desc: "Optimize for cart additions" },
  { value: "INITIATE_CHECKOUT", label: "Initiate Checkout", desc: "Optimize for checkout starts" },
  { value: "CONTACT", label: "Contact (Clicks to call/email)", desc: "Optimize for contact actions" },
];

const EVENT_SNIPPETS: Record<string, { code: string; page: string }> = {
  PURCHASE: { code: "fbq('track', 'Purchase', {value: 0.00, currency: 'USD'});", page: "order confirmation / thank-you page" },
  LEAD: { code: "fbq('track', 'Lead');", page: "form submission success page" },
  COMPLETE_REGISTRATION: { code: "fbq('track', 'CompleteRegistration');", page: "registration success / welcome page" },
  ADD_TO_CART: { code: "fbq('track', 'AddToCart');", page: "add-to-cart button click handler" },
  INITIATE_CHECKOUT: { code: "fbq('track', 'InitiateCheckout');", page: "checkout page load" },
  CONTACT: { code: "fbq('track', 'Contact');", page: "contact form success page" },
};

/* ── Pixel Attach Modal ───────────────────────────────── */

function PixelAttachModal({
  onClose,
  onAttach,
  currentPixelId,
  currentEvent,
}: {
  onClose: () => void;
  onAttach: (pixelId: string, pixelName: string, event: string) => void;
  currentPixelId: string | null;
  currentEvent: string | null;
}) {
  const [tab, setTab] = useState<"select" | "create">("select");
  const [pixels, setPixels] = useState<{ id: string; name: string }[]>([]);
  const [loadingPixels, setLoadingPixels] = useState(true);
  const [selectedPixel, setSelectedPixel] = useState<string>(currentPixelId || "");
  const [selectedEvent, setSelectedEvent] = useState<string>(currentEvent || "PURCHASE");
  const [newPixelName, setNewPixelName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [pixelBaseCode, setPixelBaseCode] = useState<string | null>(null);
  const [showTrackingCodes, setShowTrackingCodes] = useState(false);
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);

  const copySnippet = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSnippet(key);
    setTimeout(() => setCopiedSnippet(null), 2000);
  };

  const fetchPixels = useCallback(async () => {
    setLoadingPixels(true);
    try {
      const res = await api.listPixels();
      const list = (res as unknown as { data: { pixels: { id: string; name: string }[] } }).data?.pixels
        || (res as unknown as { pixels: { id: string; name: string }[] }).pixels || [];
      setPixels(list);
      if (!selectedPixel && list.length > 0) {
        setSelectedPixel(currentPixelId || list[0].id);
      }
    } catch { /* empty */ }
    setLoadingPixels(false);
  }, [currentPixelId, selectedPixel]);

  useEffect(() => { fetchPixels(); }, [fetchPixels]);

  const handleCreate = async () => {
    if (!newPixelName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const res = await api.createPixel(newPixelName.trim());
      const data = (res as unknown as { data: { pixel_id?: string; id?: string; name?: string; pixel_name?: string; already_existed?: boolean; base_code?: string } }).data;
      const pixelId = data?.pixel_id || data?.id;
      const pixelName = data?.name || data?.pixel_name || newPixelName;
      if (pixelId) {
        setSelectedPixel(pixelId);
        setPixels((prev) => [...prev, { id: pixelId, name: pixelName }]);
        setPixelBaseCode(data?.base_code || null);
        setTab("select");
        setNewPixelName("");
      } else {
        setCreateError("Pixel creation returned no ID. Try again.");
      }
    } catch {
      setCreateError("Failed to create pixel. Check your Meta connection.");
    }
    setCreating(false);
  };

  const selectedPixelName = pixels.find((p) => p.id === selectedPixel)?.name || selectedPixel;
  const selectedEventLabel = CONVERSION_EVENTS.find((e) => e.value === selectedEvent)?.label?.split(" (")[0] || selectedEvent;

  // Generate base code from pixel ID (standard Meta Pixel template)
  const baseCodeForPixel = selectedPixel ? `<!-- Meta Pixel Code -->
<script>
!function(f,b,e,v,n,t,s)
{f.fbq||(n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)},
f._fbq||(f._fbq=n),n.push=n,n.loaded=!0,n.version='2.0',
n.queue=[],t=b.createElement(e),t.async=!0,
t.src=v,s=b.getElementsByTagName(e)[0],
s.parentNode.insertBefore(t,s))}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '${selectedPixel}');
fbq('track', 'PageView');
</script>
<noscript><img height="1" width="1" style="display:none"
src="https://www.facebook.com/tr?id=${selectedPixel}&ev=PageView&noscript=1"
/></noscript>
<!-- End Meta Pixel Code -->` : null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-[#141418] border border-white/[0.08] rounded-2xl overflow-hidden animate-slide-up max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06] shrink-0">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-semibold text-white">Attach Meta Pixel</h3>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-white/[0.06] shrink-0">
          <button onClick={() => setTab("select")}
            className={`flex-1 px-4 py-2.5 text-xs font-medium transition-all ${tab === "select" ? "text-amber-400 border-b-2 border-amber-400 bg-amber-500/[0.05]" : "text-gray-500 hover:text-gray-300"}`}>
            Select Existing
          </button>
          <button onClick={() => setTab("create")}
            className={`flex-1 px-4 py-2.5 text-xs font-medium transition-all ${tab === "create" ? "text-amber-400 border-b-2 border-amber-400 bg-amber-500/[0.05]" : "text-gray-500 hover:text-gray-300"}`}>
            Create New
          </button>
        </div>

        {/* Scrollable content */}
        <div className="overflow-y-auto flex-1 min-h-0">
          <div className="px-5 py-5 space-y-5">
            {tab === "select" ? (
              <>
                {/* Pixel selector */}
                {loadingPixels ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-5 h-5 animate-spin text-gray-500" />
                  </div>
                ) : pixels.length === 0 ? (
                  <div className="text-center py-6">
                    <p className="text-sm text-gray-400 mb-2">No pixels found on this account.</p>
                    <button onClick={() => setTab("create")} className="text-xs text-amber-400 hover:text-amber-300 font-medium">
                      Create your first pixel
                    </button>
                  </div>
                ) : (
                  <div>
                    <label className="text-xs text-gray-500 mb-1.5 block">Select Pixel</label>
                    <div className="relative">
                      <select value={selectedPixel} onChange={(e) => setSelectedPixel(e.target.value)}
                        className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-all appearance-none">
                        {pixels.map((p) => (
                          <option key={p.id} value={p.id}>{p.name} ({p.id})</option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none" />
                    </div>
                  </div>
                )}

                {/* ─── AREA 1: Global Website Tracking (collapsible) ─── */}
                {selectedPixel && (
                  <div className="rounded-xl border border-white/[0.06] overflow-hidden">
                    <button
                      onClick={() => setShowTrackingCodes(!showTrackingCodes)}
                      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-white/[0.02] transition-all"
                    >
                      <div className="w-6 h-6 rounded-lg bg-blue-500/10 flex items-center justify-center shrink-0">
                        <Code className="w-3.5 h-3.5 text-blue-400" />
                      </div>
                      <div className="flex-1 text-left">
                        <p className="text-xs font-semibold text-white">1. Website Tracking Codes</p>
                        <p className="text-[10px] text-gray-500">Base pixel + all event snippets for your site</p>
                      </div>
                      <ChevronRight className={`w-3.5 h-3.5 text-gray-500 transition-transform ${showTrackingCodes ? "rotate-90" : ""}`} />
                    </button>

                    {showTrackingCodes && (
                      <div className="border-t border-white/[0.06] px-4 py-3 space-y-3">
                        <p className="text-[10px] text-gray-500">
                          Install the <span className="text-blue-300">Base Code</span> on every page. Add <span className="text-amber-300">Event Codes</span> on pages where each action happens.
                        </p>

                        {/* Base Pixel Code — always available when a pixel is selected */}
                        {baseCodeForPixel && (
                          <div className="rounded-lg bg-[#0d1117] border border-white/[0.08] overflow-hidden">
                            <div className="flex items-center justify-between px-3 py-1.5 border-b border-white/[0.06]">
                              <p className="text-[10px] font-medium text-blue-400">Base Pixel Code — install on ALL pages</p>
                              <button onClick={() => copySnippet(baseCodeForPixel, "base")}
                                className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-white px-1.5 py-0.5 rounded bg-white/[0.06]">
                                {copiedSnippet === "base" ? <Check className="w-2.5 h-2.5 text-emerald-400" /> : <Copy className="w-2.5 h-2.5" />}
                                {copiedSnippet === "base" ? "Copied!" : "Copy"}
                              </button>
                            </div>
                            <pre className="px-3 py-2 text-[9px] text-gray-500 leading-relaxed overflow-x-auto max-h-24 overflow-y-auto">{baseCodeForPixel}</pre>
                          </div>
                        )}

                        {/* All Event Snippets */}
                        <div className="space-y-1">
                          {Object.entries(EVENT_SNIPPETS).map(([key, snippet]) => (
                            <div key={key} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
                              <div className="flex-1 min-w-0">
                                <p className="text-[10px] font-medium text-amber-300/90">{CONVERSION_EVENTS.find((e) => e.value === key)?.label?.split(" (")[0] || key}</p>
                                <code className="text-[10px] font-mono text-gray-400 block truncate">{snippet.code}</code>
                                <p className="text-[9px] text-gray-600">Install on: {snippet.page}</p>
                              </div>
                              <button onClick={() => copySnippet(snippet.code, key)}
                                className="shrink-0 flex items-center gap-1 text-[10px] text-gray-500 hover:text-white px-2 py-1 rounded bg-white/[0.04]">
                                {copiedSnippet === key ? <Check className="w-2.5 h-2.5 text-emerald-400" /> : <Copy className="w-2.5 h-2.5" />}
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* ─── AREA 2: Campaign Optimization Goal ─── */}
                {selectedPixel && (
                  <div className="rounded-xl border border-amber-500/10 bg-amber-500/[0.02] overflow-hidden">
                    <div className="px-4 py-3 border-b border-amber-500/10">
                      <div className="flex items-center gap-2 mb-1">
                        <div className="w-6 h-6 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0">
                          <Target className="w-3.5 h-3.5 text-amber-400" />
                        </div>
                        <p className="text-xs font-semibold text-white">2. Optimization Goal for this Ad</p>
                      </div>
                      <p className="text-[10px] text-gray-500 ml-8">
                        Choose ONE goal. Meta&apos;s AI will find people most likely to take this action.
                      </p>
                    </div>
                    <div className="px-4 py-3">
                      <div className="grid grid-cols-2 gap-1.5">
                        {CONVERSION_EVENTS.map((ev) => (
                          <label key={ev.value}
                            className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all border ${
                              selectedEvent === ev.value
                                ? "bg-amber-500/10 border-amber-500/30 text-white"
                                : "bg-white/[0.02] border-white/[0.06] text-gray-400 hover:bg-white/[0.04] hover:text-gray-200"
                            }`}>
                            <input type="radio" name="conv_event" value={ev.value} checked={selectedEvent === ev.value}
                              onChange={(e) => setSelectedEvent(e.target.value)} className="hidden" />
                            <div className={`w-3 h-3 rounded-full border-2 flex items-center justify-center shrink-0 ${
                              selectedEvent === ev.value ? "border-amber-400" : "border-gray-600"
                            }`}>
                              {selectedEvent === ev.value && <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />}
                            </div>
                            <span className="text-xs font-medium leading-tight">{ev.label.split(" (")[0]}</span>
                          </label>
                        ))}
                      </div>
                      {/* Dynamic confirmation text */}
                      {selectedEvent && (
                        <p className="text-[10px] text-amber-400/70 mt-2.5 ml-0.5">
                          Meta will optimize this ad to get you more <span className="font-semibold text-amber-300">{selectedEventLabel}s</span>. Make sure the {selectedEventLabel} tracking code is installed on your website.
                        </p>
                      )}
                    </div>
                  </div>
                )}
              </>
            ) : (
              /* Create New tab */
              <div className="space-y-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1.5 block">Pixel Name</label>
                  <input type="text" value={newPixelName} onChange={(e) => setNewPixelName(e.target.value)}
                    placeholder="e.g. My Store Pixel"
                    className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-amber-500/40 transition-all" />
                </div>
                {createError && <p className="text-xs text-red-400">{createError}</p>}
                <button onClick={handleCreate} disabled={creating || !newPixelName.trim()}
                  className="flex items-center justify-center gap-2 w-full px-4 py-2.5 rounded-xl text-sm font-semibold bg-amber-500/90 hover:bg-amber-500 text-black transition-all disabled:opacity-40">
                  {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                  Create Pixel
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-5 py-4 border-t border-white/[0.06] shrink-0">
          <button onClick={onClose} className="flex-1 px-4 py-2.5 rounded-xl text-sm text-gray-400 bg-white/[0.03] border border-white/[0.06] hover:text-white transition-all">
            Cancel
          </button>
          <button onClick={() => { if (selectedPixel) onAttach(selectedPixel, selectedPixelName, selectedEvent); }}
            disabled={!selectedPixel}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-amber-500 to-orange-500 text-black transition-all disabled:opacity-40">
            <Zap className="w-3.5 h-3.5" />
            Attach Pixel
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Lead Form Types ─────────────────────────────────────── */

const FIELD_TYPE_LABELS: Record<string, string> = {
  FULL_NAME: "Full Name", EMAIL: "Email", PHONE: "Phone Number",
  CITY: "City", COMPANY_NAME: "Company Name", JOB_TITLE: "Job Title",
  STATE: "State", ZIP: "ZIP Code", STREET_ADDRESS: "Street Address",
  DATE_OF_BIRTH: "Date of Birth", CUSTOM: "Custom Question",
};

const STANDARD_FIELD_OPTIONS = [
  { type: "FULL_NAME", key: "full_name" },
  { type: "EMAIL", key: "email" },
  { type: "PHONE", key: "phone_number" },
  { type: "CITY", key: "city" },
  { type: "COMPANY_NAME", key: "company_name" },
  { type: "JOB_TITLE", key: "job_title" },
];

type LeadFormQuestion = { type: string; key: string; label?: string };
type SavedLeadForm = { id: string; meta_form_id: string; form_name: string; questions: LeadFormQuestion[]; page_id: string; created_at: string; source?: string; status?: string };

/* ── Lead Form Builder Modal (AI-First) ─────────────────── */

function LeadFormBuilder({
  onClose,
  onFormCreated,
  currentFormId,
  draftId,
}: {
  onClose: () => void;
  onFormCreated: (formId: string, formName: string) => void;
  currentFormId: string | null;
  draftId?: string;
}) {
  const { activeWorkspace } = useWorkspace();
  const wsPageId = activeWorkspace?.meta_page_id || "";
  const [tab, setTab] = useState<"ai" | "select" | "manual">("ai");
  const [savedForms, setSavedForms] = useState<SavedLeadForm[]>([]);
  const [loadingForms, setLoadingForms] = useState(true);
  const [selectedFormId, setSelectedFormId] = useState<string>(currentFormId || "");

  // AI draft state
  const [aiLoading, setAiLoading] = useState(false);
  const [aiFormName, setAiFormName] = useState("");
  const [aiQuestions, setAiQuestions] = useState<LeadFormQuestion[]>([]);
  const [aiReasoning, setAiReasoning] = useState("");
  const [aiGenerated, setAiGenerated] = useState(false);

  // Manual/shared create state
  const [formName, setFormName] = useState("");
  const [questions, setQuestions] = useState<LeadFormQuestion[]>([]);
  const [newCustomLabel, setNewCustomLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Page ID — auto-select workspace page
  const [pages, setPages] = useState<{ page_id: string; page_name: string }[]>([]);
  const [selectedPage, setSelectedPage] = useState("");

  // Load pages + saved forms on mount — prefer workspace's linked page
  useEffect(() => {
    api.fetchSocialIdentities()
      .then((res: unknown) => {
        const data = (res as { data: { pages: { page_id: string; page_name: string }[] } }).data;
        const pageList = data?.pages || [];
        setPages(pageList);
        if (pageList.length > 0 && !selectedPage) {
          // Auto-select the workspace's linked page if available
          const wsMatch = wsPageId ? pageList.find((p: { page_id: string }) => p.page_id === wsPageId) : null;
          setSelectedPage(wsMatch ? wsMatch.page_id : pageList[0].page_id);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    setLoadingForms(true);
    api.listLeadForms()
      .then((res: unknown) => {
        const raw = (res as { data: SavedLeadForm[] | SavedLeadForm }).data;
        const data = Array.isArray(raw) ? raw : raw ? [raw] : [];
        setSavedForms(data);
        if (!selectedFormId && data.length > 0) {
          setSelectedFormId(currentFormId || data[0].meta_form_id);
        }
      })
      .catch(() => {})
      .finally(() => setLoadingForms(false));
  }, []);

  // Auto-generate AI draft on mount
  useEffect(() => {
    if (tab === "ai" && !aiGenerated) {
      handleAiGenerate();
    }
  }, []);

  const handleAiGenerate = async () => {
    setAiLoading(true);
    setCreateError(null);
    try {
      const res = await api.generateLeadFormDraft({ draft_id: draftId || undefined });
      const data = res.data;
      setAiFormName(data.form_name || "Lead Form");
      setAiQuestions(data.questions || []);
      setAiReasoning(data.reasoning || "");
      setAiGenerated(true);
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || "AI generation failed — try manual mode.");
      // Set defaults so user can still proceed
      setAiFormName("Lead Form");
      setAiQuestions([
        { type: "FULL_NAME", key: "full_name" },
        { type: "PHONE", key: "phone_number" },
        { type: "EMAIL", key: "email" },
      ]);
      setAiGenerated(true);
    }
    setAiLoading(false);
  };

  const removeAiQuestion = (idx: number) => {
    setAiQuestions((prev) => prev.filter((_, i) => i !== idx));
  };

  const addStandardField = (type: string, key: string) => {
    if (tab === "ai") {
      if (!aiQuestions.find((q) => q.key === key)) {
        setAiQuestions((prev) => [...prev, { type, key }]);
      }
    } else {
      if (!questions.find((q) => q.key === key)) {
        setQuestions((prev) => [...prev, { type, key }]);
      }
    }
  };

  const addCustomQuestion = () => {
    if (!newCustomLabel.trim()) return;
    const key = newCustomLabel.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "");
    const q: LeadFormQuestion = { type: "CUSTOM", key, label: newCustomLabel.trim() };
    if (tab === "ai") {
      setAiQuestions((prev) => [...prev, q]);
    } else {
      setQuestions((prev) => [...prev, q]);
    }
    setNewCustomLabel("");
  };

  const handleCreateOnMeta = async (name: string, qs: LeadFormQuestion[]) => {
    if (!name.trim() || !selectedPage || qs.length === 0) return;
    setCreating(true);
    setCreateError(null);
    try {
      const res = await api.createLeadForm({
        page_id: selectedPage,
        form_name: name.trim(),
        questions: qs,
        save_form: true,
      });
      const data = (res as { data: { form_id: string; form_name: string } }).data;
      if (data?.form_id) {
        onFormCreated(data.form_id, data.form_name);
      } else {
        setCreateError("No form ID returned from Meta.");
      }
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || "Failed to create form on Meta.");
    }
    setCreating(false);
  };

  const selectedFormName = savedForms.find((f) => f.meta_form_id === selectedFormId)?.form_name || selectedFormId;

  // Drag-to-reorder state
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);

  const handleReorder = (qs: LeadFormQuestion[], fromIdx: number, toIdx: number) => {
    if (fromIdx === toIdx) return;
    const updated = [...qs];
    const [moved] = updated.splice(fromIdx, 1);
    updated.splice(toIdx, 0, moved);
    if (tab === "ai") setAiQuestions(updated);
    else setQuestions(updated);
  };

  // Shared question editor component with drag-to-reorder
  const renderQuestionList = (qs: LeadFormQuestion[], onRemove: (i: number) => void) => (
    <div className="space-y-1.5">
      {qs.map((q, i) => (
        <div key={`${q.key}-${i}`}
          draggable
          onDragStart={() => { setDragIdx(i); }}
          onDragOver={(e) => { e.preventDefault(); setDragOverIdx(i); }}
          onDragEnd={() => { if (dragIdx !== null && dragOverIdx !== null) handleReorder(qs, dragIdx, dragOverIdx); setDragIdx(null); setDragOverIdx(null); }}
          className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-white/[0.03] border transition-all group cursor-grab active:cursor-grabbing ${
            dragOverIdx === i && dragIdx !== null && dragIdx !== i
              ? "border-cyan-500/40 bg-cyan-500/[0.05]"
              : "border-white/[0.06]"
          } ${dragIdx === i ? "opacity-40" : ""}`}>
          <GripVertical className="w-3.5 h-3.5 text-gray-600 shrink-0" />
          <div className="w-5 h-5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-[10px] font-bold text-cyan-400">
            {i + 1}
          </div>
          <div className="flex-1 min-w-0">
            <span className="text-sm text-white">{q.label || FIELD_TYPE_LABELS[q.type] || q.key}</span>
            <span className="text-[10px] text-gray-600 ml-2">{q.type}</span>
          </div>
          <button onClick={() => onRemove(i)}
            className="text-gray-600 hover:text-red-400 transition-colors p-0.5 opacity-0 group-hover:opacity-100">
            <X className="w-3 h-3" />
          </button>
        </div>
      ))}
    </div>
  );

  // Add field dropdown
  const renderAddField = () => {
    const currentQs = tab === "ai" ? aiQuestions : questions;
    const usedKeys = new Set(currentQs.map((q) => q.key));
    const available = STANDARD_FIELD_OPTIONS.filter((f) => !usedKeys.has(f.key));

    return (
      <div className="space-y-2 pt-2 border-t border-white/[0.04]">
        {available.length > 0 && (
          <div>
            <p className="text-[10px] text-gray-600 mb-1.5">Add standard field:</p>
            <div className="flex flex-wrap gap-1.5">
              {available.map((f) => (
                <button key={f.key} onClick={() => addStandardField(f.type, f.key)}
                  className="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-white/[0.04] border border-white/[0.08] text-gray-400 hover:text-cyan-400 hover:border-cyan-500/20 transition-all">
                  + {FIELD_TYPE_LABELS[f.type]}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="flex gap-2">
          <input type="text" value={newCustomLabel} onChange={(e) => setNewCustomLabel(e.target.value)}
            placeholder="Add custom question..."
            onKeyDown={(e) => e.key === "Enter" && addCustomQuestion()}
            className="flex-1 px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-cyan-500/40 transition-all" />
          <button onClick={addCustomQuestion} disabled={!newCustomLabel.trim()}
            className="px-3 py-2 rounded-xl text-xs font-medium bg-white/[0.06] border border-white/[0.08] text-gray-300 hover:bg-white/[0.1] transition-all disabled:opacity-40">
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md bg-[#141418] border border-white/[0.08] rounded-2xl overflow-hidden animate-slide-up max-h-[85vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06] sticky top-0 bg-[#141418] z-10">
          <div className="flex items-center gap-2">
            <ClipboardList className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-semibold text-white">Lead Form</h3>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-white/[0.06]">
          <button onClick={() => setTab("ai")}
            className={`flex-1 px-3 py-2.5 text-xs font-medium transition-all flex items-center justify-center gap-1.5 ${tab === "ai" ? "text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/[0.05]" : "text-gray-500 hover:text-gray-300"}`}>
            <Sparkles className="w-3 h-3" /> AI Build
          </button>
          <button onClick={() => setTab("select")}
            className={`flex-1 px-3 py-2.5 text-xs font-medium transition-all ${tab === "select" ? "text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/[0.05]" : "text-gray-500 hover:text-gray-300"}`}>
            Saved ({savedForms.length})
          </button>
          <button onClick={() => setTab("manual")}
            className={`flex-1 px-3 py-2.5 text-xs font-medium transition-all ${tab === "manual" ? "text-cyan-400 border-b-2 border-cyan-400 bg-cyan-500/[0.05]" : "text-gray-500 hover:text-gray-300"}`}>
            Manual
          </button>
        </div>

        <div className="px-5 py-5 space-y-4">
          {/* ── AI Tab ── */}
          {tab === "ai" && (
            <>
              {aiLoading ? (
                <div className="space-y-3 py-4">
                  <div className="flex items-center justify-center gap-2 mb-4">
                    <Sparkles className="w-4 h-4 text-cyan-400 animate-pulse" />
                    <span className="text-sm text-cyan-400 animate-pulse">AI is analyzing your ad...</span>
                  </div>
                  {/* Skeleton shimmer */}
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-12 rounded-xl bg-white/[0.03] border border-white/[0.06] animate-pulse" />
                  ))}
                </div>
              ) : (
                <>
                  {/* AI reasoning */}
                  {aiReasoning && (
                    <div className="flex items-start gap-2 bg-cyan-500/[0.05] border border-cyan-500/10 rounded-xl px-3 py-2.5">
                      <Sparkles className="w-3.5 h-3.5 text-cyan-400 mt-0.5 shrink-0" />
                      <p className="text-[11px] text-gray-400 leading-relaxed">{aiReasoning}</p>
                    </div>
                  )}

                  {/* Page — auto-selected from workspace, read-only */}
                  {pages.length > 0 && (
                    <div>
                      <label className="text-xs text-gray-500 mb-1.5 block">Facebook Page</label>
                      <div className="px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm flex items-center gap-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                        {pages.find(p => p.page_id === selectedPage)?.page_name || selectedPage}
                      </div>
                    </div>
                  )}

                  {/* Editable form name */}
                  <div>
                    <label className="text-xs text-gray-500 mb-1.5 block">Form Name</label>
                    <input type="text" value={aiFormName} onChange={(e) => setAiFormName(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-cyan-500/40 transition-all" />
                  </div>

                  {/* Editable AI-generated fields */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <label className="text-xs text-gray-500">Form Fields</label>
                      <span className="text-[10px] text-gray-600">{aiQuestions.length} fields</span>
                    </div>
                    {renderQuestionList(aiQuestions, removeAiQuestion)}
                    {renderAddField()}
                  </div>

                  {createError && <p className="text-xs text-red-400">{createError}</p>}

                  {/* Action buttons */}
                  <div className="flex gap-2 pt-1">
                    <button onClick={() => handleCreateOnMeta(aiFormName, aiQuestions)}
                      disabled={creating || !aiFormName.trim() || !selectedPage || aiQuestions.length === 0}
                      className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-cyan-500 to-blue-500 text-white transition-all disabled:opacity-40 hover:scale-[1.02] active:scale-[0.98]">
                      {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                      Approve & Create
                    </button>
                    <button onClick={handleAiGenerate} disabled={aiLoading}
                      className="px-3 py-2.5 rounded-xl text-xs font-medium text-gray-400 bg-white/[0.03] border border-white/[0.06] hover:text-white transition-all disabled:opacity-40">
                      <RefreshCw className={`w-3.5 h-3.5 ${aiLoading ? "animate-spin" : ""}`} />
                    </button>
                  </div>
                </>
              )}
            </>
          )}

          {/* ── Select Existing Tab ── */}
          {tab === "select" && (
            <>
              {loadingForms ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin text-gray-500" />
                </div>
              ) : savedForms.length === 0 ? (
                <div className="text-center py-6">
                  <p className="text-sm text-gray-400 mb-2">No saved lead forms yet.</p>
                  <button onClick={() => setTab("ai")} className="text-xs text-cyan-400 hover:text-cyan-300 font-medium">
                    Generate one with AI
                  </button>
                </div>
              ) : (
                <div className="space-y-2">
                  {savedForms.map((form) => (
                    <label key={form.meta_form_id}
                      className={`flex items-center gap-3 px-3 py-3 rounded-xl cursor-pointer transition-all border ${selectedFormId === form.meta_form_id ? "bg-cyan-500/[0.08] border-cyan-500/20" : "bg-white/[0.02] border-white/[0.06] hover:bg-white/[0.04]"}`}>
                      <input type="radio" name="lead_form" value={form.meta_form_id} checked={selectedFormId === form.meta_form_id}
                        onChange={(e) => setSelectedFormId(e.target.value)} className="hidden" />
                      <div className={`w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center ${selectedFormId === form.meta_form_id ? "border-cyan-400" : "border-gray-600"}`}>
                        {selectedFormId === form.meta_form_id && <div className="w-1.5 h-1.5 rounded-full bg-cyan-400" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-white block truncate">{form.form_name}</span>
                          {form.source === "meta" && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 shrink-0">Meta</span>
                          )}
                        </div>
                        <span className="text-[10px] text-gray-500">
                          {(form.questions || []).length > 0
                            ? (form.questions || []).map((q: LeadFormQuestion) => FIELD_TYPE_LABELS[q.type] || q.label || q.key).join(", ")
                            : form.source === "meta" ? "Live form from Meta" : "No fields"}
                        </span>
                      </div>
                    </label>
                  ))}
                </div>
              )}
            </>
          )}

          {/* ── Manual Build Tab ── */}
          {tab === "manual" && (
            <div className="space-y-4">
              {/* Page — auto-selected from workspace */}
              {pages.length > 0 && (
                <div>
                  <label className="text-xs text-gray-500 mb-1.5 block">Facebook Page</label>
                  <div className="px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm flex items-center gap-2">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                    {pages.find(p => p.page_id === selectedPage)?.page_name || selectedPage}
                  </div>
                </div>
              )}

              <div>
                <label className="text-xs text-gray-500 mb-1.5 block">Form Name</label>
                <input type="text" value={formName} onChange={(e) => setFormName(e.target.value)}
                  placeholder="e.g. Product Inquiry Form"
                  className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-cyan-500/40 transition-all" />
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs text-gray-500">Form Fields</label>
                  <span className="text-[10px] text-gray-600">{questions.length} fields</span>
                </div>
                {questions.length > 0 && renderQuestionList(questions, (i) => setQuestions((prev) => prev.filter((_, idx) => idx !== i)))}
                {renderAddField()}
              </div>

              {createError && <p className="text-xs text-red-400">{createError}</p>}

              <button onClick={() => handleCreateOnMeta(formName, questions)}
                disabled={creating || !formName.trim() || !selectedPage || questions.length === 0}
                className="flex items-center justify-center gap-2 w-full px-4 py-2.5 rounded-xl text-sm font-semibold bg-cyan-500/90 hover:bg-cyan-500 text-white transition-all disabled:opacity-40">
                {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ClipboardList className="w-3.5 h-3.5" />}
                Create Lead Form on Meta
              </button>
            </div>
          )}
        </div>

        {/* Footer — select tab only */}
        {tab === "select" && savedForms.length > 0 && (
          <div className="flex gap-2 px-5 py-4 border-t border-white/[0.06]">
            <button onClick={onClose} className="flex-1 px-4 py-2.5 rounded-xl text-sm text-gray-400 bg-white/[0.03] border border-white/[0.06] hover:text-white transition-all">
              Cancel
            </button>
            <button onClick={() => { if (selectedFormId) onFormCreated(selectedFormId, selectedFormName); }}
              disabled={!selectedFormId}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-cyan-500 to-blue-500 text-white transition-all disabled:opacity-40">
              <ClipboardList className="w-3.5 h-3.5" />
              Use This Form
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Draft Detail Modal ──────────────────────────────────── */

const CTA_OPTIONS = ["SHOP_NOW", "LEARN_MORE", "SIGN_UP", "CONTACT_US", "GET_OFFER", "WHATSAPP_MESSAGE"];

const BUDGET_CURRENCIES = [
  { value: "USD", symbol: "$" },
  { value: "PKR", symbol: "₨" },
  { value: "EUR", symbol: "€" },
  { value: "GBP", symbol: "£" },
  { value: "AED", symbol: "AED" },
  { value: "INR", symbol: "₹" },
];

function DraftDetailModal({
  draft,
  onClose,
  onApprove,
  onReject,
  onPause,
  onDraftUpdate,
  loading,
  budgetCurrency: initialCurrency,
}: {
  draft: Draft;
  onClose: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onPause: (id: string) => void;
  onDraftUpdate: (id: string, fields: Record<string, unknown>) => void;
  loading: string | null;
  budgetCurrency: string;
}) {
  const isPending = draft.status === "pending";
  const [editing, setEditing] = useState(false);
  const [headline, setHeadline] = useState(draft.headline ?? "");
  const [bodyText, setBodyText] = useState(draft.body_text);
  const [ctaType, setCtaType] = useState(draft.cta_type ?? "SHOP_NOW");
  const [budget, setBudget] = useState(String(draft.proposed_budget ?? ""));
  const [budgetCurrency, setBudgetCurrency] = useState(initialCurrency);
  const [draftPlacement, setDraftPlacement] = useState<string>(
    (draft.targeting as Record<string, string>)?.placements ?? "BOTH"
  );
  const [imageUrlInput, setImageUrlInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [destinationUrl, setDestinationUrl] = useState(draft.destination_url ?? "");
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const [campaignDest, setCampaignDest] = useState<string>(draft.destination_type || "WEBSITE");
  const [conversionEvent, setConversionEvent] = useState<string>(draft.conversion_event || "PURCHASE");
  const [campaignObjective, setCampaignObjective] = useState<string>(draft.campaign_objective || "");
  const [waNumber, setWaNumber] = useState(draft.whatsapp_number ?? "");
  const [showLeadFormModal, setShowLeadFormModal] = useState(false);
  const [attachedLeadFormName, setAttachedLeadFormName] = useState<string | null>(null);
  const [msgApps, setMsgApps] = useState<string[]>(draft.selected_messaging_apps || []);
  const [callPhone, setCallPhone] = useState(draft.call_phone_number ?? "");

  // Fetch lead form name if draft has lead_form_id
  useEffect(() => {
    if (draft.lead_form_id) {
      api.listLeadForms()
        .then((res: unknown) => {
          const forms = (res as { data: { meta_form_id: string; form_name: string }[] }).data || [];
          const match = forms.find((f: { meta_form_id: string }) => f.meta_form_id === draft.lead_form_id);
          if (match) setAttachedLeadFormName(match.form_name);
          else setAttachedLeadFormName(draft.lead_form_id);
        })
        .catch(() => setAttachedLeadFormName(draft.lead_form_id));
    }
  }, [draft.lead_form_id]);

  // Pre-fill WhatsApp number from preferences if draft doesn't have one
  useEffect(() => {
    if (!waNumber) {
      api.getPreferences().then((res: { data?: { whatsapp_number?: string } }) => {
        if (res?.data?.whatsapp_number) setWaNumber(res.data.whatsapp_number);
      }).catch(() => {});
    }
  }, []);
  const [showPixelModal, setShowPixelModal] = useState(false);
  const [attachedPixelName, setAttachedPixelName] = useState<string | null>(null);

  // Fetch pixel name if draft has pixel_id
  useEffect(() => {
    if (draft.pixel_id) {
      api.listPixels()
        .then((res: unknown) => {
          const list = (res as { data: { pixels: { id: string; name: string }[] } }).data?.pixels
            || (res as { pixels: { id: string; name: string }[] }).pixels || [];
          const match = list.find((p: { id: string }) => p.id === draft.pixel_id);
          if (match) setAttachedPixelName(match.name);
          else setAttachedPixelName(draft.pixel_id);
        })
        .catch(() => setAttachedPixelName(draft.pixel_id));
    }
  }, [draft.pixel_id]);

  useEffect(() => {
    if (draft.product_id) {
      api.getProduct(draft.product_id)
        .then((res: { data: { landing_url?: string } }) => {
          const url = res.data?.landing_url || (res as unknown as { landing_url?: string }).landing_url;
          if (url) setFallbackUrl(url);
        })
        .catch(() => {});
    }
  }, [draft.product_id]);

  const [profitMargin, setProfitMargin] = useState(
    String((draft.targeting as Record<string, unknown>)?.profit_margin ?? "")
  );
  const [showProfitTooltip, setShowProfitTooltip] = useState(false);

  // Geo targeting state — draft-level override, fall back to preferences
  const _specGeo = parseTargetingSpec(draft.targeting_spec);
  const _draftCountry = (draft.targeting as Record<string, string>)?.target_country
    || _specGeo?.target_country || draft.target_country || "";
  const _draftCities = ((draft.targeting as Record<string, unknown>)?.target_cities as string[] ?? []).join(", ");
  const [editCountry, setEditCountry] = useState(_draftCountry);
  const [editCities, setEditCities] = useState(_draftCities);
  const [prefsCountry, setPrefsCountry] = useState("");
  const [prefsCities, setprefsCities] = useState("");

  // Fetch preferences defaults for geo display
  useEffect(() => {
    api.getPreferences().then((res: { data?: { target_country?: string; target_cities?: string[] } }) => {
      const pc = res?.data?.target_country || "PK";
      const pCities = (res?.data?.target_cities || []).join(", ");
      setPrefsCountry(pc);
      setprefsCities(pCities);
      if (!_draftCountry) setEditCountry(pc);
      if (!_draftCities && pCities) setEditCities(pCities);
    }).catch(() => {});
  }, []);

  // Effective initial values (for dirty-checking on save)
  const _initCountry = _draftCountry || prefsCountry;
  const _initCities = _draftCities || prefsCities;

  const mediaItems = getMediaItems(draft);
  const [activeMediaIdx, setActiveMediaIdx] = useState(0);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setUploading(true);
    setUploadError(null);
    try {
      const currentItems: MediaItem[] = [...(draft.media_items || [])];
      for (let i = 0; i < files.length; i++) {
        if (currentItems.length >= 10) break;
        const file = files[i];
        const { data } = await api.uploadProductImage(file);
        const mtype = file.type.startsWith("video/") ? "video" : "image";
        currentItems.push({ type: mtype as "image" | "video", url: data.url });
      }
      const updates: Record<string, unknown> = { media_items: currentItems, image_url: currentItems[0]?.url || null };
      if (draft.status === "failed") { updates.status = "pending"; updates.error_message = null; }
      onDraftUpdate(draft.id, updates);
    } catch { setUploadError("Failed to upload file."); }
    finally { setUploading(false); e.target.value = ""; }
  };

  const handleRemoveMedia = (idx: number) => {
    const currentItems = [...(draft.media_items || mediaItems)];
    currentItems.splice(idx, 1);
    onDraftUpdate(draft.id, {
      media_items: currentItems.length > 0 ? currentItems : null,
      image_url: currentItems[0]?.url || null,
    });
    if (activeMediaIdx >= currentItems.length) setActiveMediaIdx(Math.max(0, currentItems.length - 1));
  };

  const handleSaveEdits = async () => {
    setSaving(true);
    const fields: Record<string, unknown> = {};
    if (headline !== (draft.headline ?? "")) fields.headline = headline;
    if (bodyText !== draft.body_text) fields.body_text = bodyText;
    if (ctaType !== (draft.cta_type ?? "")) fields.cta_type = ctaType;
    if (budget !== String(draft.proposed_budget ?? "")) fields.proposed_budget = parseFloat(budget) || undefined;
    if (destinationUrl !== (draft.destination_url ?? "")) fields.destination_url = destinationUrl || null;
    const existingTargeting = (draft.targeting || {}) as Record<string, string>;
    const existingPlacement = existingTargeting.placements;
    const parsedMargin = parseFloat(profitMargin) || undefined;
    const existingMargin = (existingTargeting as Record<string, unknown>).profit_margin;
    if (
      draftPlacement !== (existingPlacement ?? "BOTH") ||
      budgetCurrency !== (existingTargeting.budget_currency ?? initialCurrency) ||
      parsedMargin !== existingMargin
    ) {
      fields.targeting = {
        ...existingTargeting,
        placements: draftPlacement,
        budget_currency: budgetCurrency,
        ...(parsedMargin ? { profit_margin: parsedMargin } : { profit_margin: null }),
      };
    }
    // Geo targeting overrides — write to BOTH the targeting JSON (for legacy
    // readers) and the dedicated target_country column (what ad_executor reads
    // as highest priority for multi-country support).
    const citiesArr = editCities.split(",").map(c => c.trim()).filter(Boolean);
    if (editCountry !== _initCountry || editCities !== _initCities) {
      const base = (fields.targeting as Record<string, unknown>) || { ...existingTargeting, placements: draftPlacement, budget_currency: budgetCurrency };
      fields.targeting = {
        ...base,
        ...(editCountry ? { target_country: editCountry } : {}),
        target_cities: citiesArr.length > 0 ? citiesArr : null,
      };
      // Also persist to the column itself — ad_executor reads this directly.
      (fields as Record<string, unknown>).target_country = editCountry || null;
    }
    if (campaignDest !== (draft.destination_type || "WEBSITE")) fields.destination_type = campaignDest;
    // Save campaign objective override (empty string = auto-detect)
    const objValue = campaignObjective || null;
    if (objValue !== (draft.campaign_objective || null)) fields.campaign_objective = objValue;
    // Save destination-specific fields & rigidly clear irrelevant data
    if (campaignDest === "WEBSITE") {
      fields.whatsapp_number = "";
      fields.selected_messaging_apps = null;
      fields.call_phone_number = null;
      if (draft.lead_form_id) fields.lead_form_id = null;
      if (conversionEvent !== (draft.conversion_event || "PURCHASE")) fields.conversion_event = conversionEvent;
    } else if (campaignDest === "INSTANT_FORM") {
      fields.whatsapp_number = "";
      fields.selected_messaging_apps = null;
      fields.call_phone_number = null;
      if (draft.conversion_event) fields.conversion_event = null;
    } else if (campaignDest === "MESSAGING") {
      fields.selected_messaging_apps = msgApps;
      fields.call_phone_number = null;
      if (draft.lead_form_id) fields.lead_form_id = null;
      if (draft.conversion_event) fields.conversion_event = null;
      // Save WhatsApp number if WhatsApp is one of the selected apps
      if (msgApps.includes("WHATSAPP") && waNumber !== (draft.whatsapp_number ?? "")) {
        fields.whatsapp_number = waNumber;
      } else if (!msgApps.includes("WHATSAPP")) {
        fields.whatsapp_number = "";
      }
    } else if (campaignDest === "PHONE_CALL") {
      if (callPhone !== (draft.call_phone_number ?? "")) fields.call_phone_number = callPhone;
      fields.whatsapp_number = "";
      fields.selected_messaging_apps = null;
      if (draft.lead_form_id) fields.lead_form_id = null;
      if (draft.conversion_event) fields.conversion_event = null;
    } else if (campaignDest === "INSTAGRAM_DM") {
      fields.whatsapp_number = "";
      fields.selected_messaging_apps = null;
      fields.call_phone_number = null;
      if (draft.conversion_event) fields.conversion_event = null;
      if (draft.lead_form_id) fields.lead_form_id = null;
    } else {
      // WHATSAPP (legacy single-app)
      if (waNumber !== (draft.whatsapp_number ?? "")) fields.whatsapp_number = waNumber;
      fields.selected_messaging_apps = null;
      fields.call_phone_number = null;
      if (draft.conversion_event) fields.conversion_event = null;
      if (draft.lead_form_id) fields.lead_form_id = null;
    }
    if (Object.keys(fields).length > 0) {
      await onDraftUpdate(draft.id, fields);
    }
    setSaving(false);
    setEditing(false);
  };

  const ab = parseAbVariants(draft.ab_variants);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl glass-strong rounded-2xl overflow-hidden animate-slide-up max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] sticky top-0 bg-[#0a0a0f]/95 backdrop-blur-sm z-10">
          <div className="flex items-center gap-2.5">
            <TypeBadge type={draft.draft_type} onToggle={isPending ? () => {
              const newType = draft.draft_type === "paid" ? "organic" : "paid";
              const updates: Record<string, unknown> = { draft_type: newType };
              if (newType === "paid" && !draft.proposed_budget) {
                updates.proposed_budget = 10;
                setBudget("10");
              }
              onDraftUpdate(draft.id, updates);
            } : undefined} />
            <StatusBadge status={draft.status} />
            {isPending && <span className="text-[10px] text-gray-600">click badge to switch</span>}
          </div>
          <div className="flex items-center gap-2">
            {isPending && !editing && (
              <button onClick={() => setEditing(true)} className="text-xs text-violet-400 hover:text-violet-300 font-medium px-3 py-1.5 rounded-lg bg-violet-500/10 border border-violet-500/20 transition-all">
                Edit Draft
              </button>
            )}
            <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors p-1">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Media section — multi-media gallery */}
        <div className="relative w-full h-64 bg-black/30 border-b border-white/[0.06]">
          {mediaItems.length > 0 ? (
            <>
              {/* Active media preview */}
              {mediaItems[activeMediaIdx]?.type === "video" || isVideoUrl(mediaItems[activeMediaIdx]?.url) ? (
                <video src={resolveImageUrl(mediaItems[activeMediaIdx]?.url)} controls className="w-full h-full object-contain" />
              ) : (
                <img src={resolveImageUrl(mediaItems[activeMediaIdx]?.url)} alt={draft.headline ?? "Ad creative"} className="w-full h-full object-contain" />
              )}

              {/* Media count badge */}
              {mediaItems.length > 1 && (
                <div className="absolute top-3 left-3 px-2 py-1 rounded-lg bg-black/60 backdrop-blur-sm text-[10px] font-medium text-white border border-white/10">
                  {activeMediaIdx + 1} / {mediaItems.length}
                </div>
              )}

              {/* Thumbnail strip */}
              {mediaItems.length > 1 && (
                <div className="absolute bottom-3 left-3 flex gap-1.5">
                  {mediaItems.map((m, i) => (
                    <button key={i} onClick={() => setActiveMediaIdx(i)}
                      className={`w-10 h-10 rounded-lg overflow-hidden border-2 transition-all ${i === activeMediaIdx ? "border-violet-500" : "border-white/20 opacity-60 hover:opacity-100"}`}>
                      {m.type === "video" || isVideoUrl(m.url) ? (
                        <div className="w-full h-full bg-gray-800 flex items-center justify-center text-[8px] text-white">VID</div>
                      ) : (
                        <img src={resolveImageUrl(m.url)} alt="" className="w-full h-full object-cover" />
                      )}
                    </button>
                  ))}
                </div>
              )}

              {/* Add more / Replace buttons */}
              {isPending && (
                <div className="absolute bottom-3 right-3 flex gap-2">
                  {mediaItems.length < 10 && (
                    <label className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium bg-black/60 backdrop-blur-sm text-white hover:bg-black/80 transition-all cursor-pointer border border-white/10">
                      <Plus className="w-3 h-3" /> Add ({mediaItems.length}/10)
                      <input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" multiple onChange={handleFileUpload} className="hidden" />
                    </label>
                  )}
                  <button onClick={() => handleRemoveMedia(activeMediaIdx)}
                    className="flex items-center gap-1 px-2 py-1.5 rounded-lg text-[11px] font-medium bg-red-500/20 text-red-300 hover:bg-red-500/30 transition-all border border-red-500/20">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <ImageIcon className="w-10 h-10 text-gray-600" />
              {isPending && (
                <div className="flex gap-2">
                  <label className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-white/[0.05] border border-dashed border-white/[0.12] text-gray-300 hover:bg-white/[0.08] transition-all cursor-pointer">
                    {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
                    Upload Media (1-10 files)
                    <input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" multiple onChange={handleFileUpload} className="hidden" />
                  </label>
                </div>
              )}
              {uploadError && <p className="text-[11px] text-red-400">{uploadError}</p>}
              <div className="flex gap-2 w-64">
                <input type="text" value={imageUrlInput} onChange={(e) => setImageUrlInput(e.target.value)}
                  placeholder="Or paste image URL..." className="flex-1 px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-white text-xs placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" />
                <button onClick={() => {
                  if (imageUrlInput.trim()) {
                    const url = imageUrlInput.trim();
                    const mtype = isVideoUrl(url) ? "video" : "image";
                    const updates: Record<string, unknown> = { media_items: [{ type: mtype, url }], image_url: url };
                    if (draft.status === "failed") { updates.status = "pending"; updates.error_message = null; }
                    onDraftUpdate(draft.id, updates);
                    setImageUrlInput("");
                  }
                }} disabled={!imageUrlInput.trim()} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-600/80 text-white disabled:opacity-40 transition-all">
                  Save
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Carousel toggle — only meaningful with 2+ media items */}
        {isPending && mediaItems.length >= 2 && (
          <div className="px-6 pt-3">
            <label className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-violet-500/[0.06] border border-violet-500/15 cursor-pointer">
              <span className="flex flex-col">
                <span className="text-sm text-white font-medium">Carousel ad</span>
                <span className="text-[11px] text-gray-400">
                  {draft.is_carousel
                    ? `One swipeable ad with ${mediaItems.length} cards`
                    : `${mediaItems.length} separate ads (A/B test)`}
                </span>
              </span>
              <input
                type="checkbox"
                checked={!!draft.is_carousel}
                onChange={(e) => onDraftUpdate(draft.id, { is_carousel: e.target.checked })}
                className="w-5 h-5 accent-violet-500"
              />
            </label>
          </div>
        )}

        {/* Body */}
        <div className="px-6 py-6 space-y-5">
          {editing ? (
            /* ── Edit Mode ───────────────── */
            <>
              <div>
                <label className="text-xs text-gray-500 mb-1.5 block">Headline</label>
                <input type="text" value={headline} onChange={(e) => setHeadline(e.target.value)} maxLength={40}
                  className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all"
                  placeholder="Short punchy headline" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1.5 block">Ad Copy</label>
                <textarea value={bodyText} onChange={(e) => setBodyText(e.target.value)} rows={5}
                  className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all resize-none" />
              </div>
              {/* Campaign Destination Toggle */}
              {draft.draft_type === "paid" && (
                <div>
                  <label className="text-xs text-gray-500 mb-1.5 block">Campaign Destination</label>
                  <div className="grid grid-cols-2 gap-2">
                    <button type="button" onClick={() => setCampaignDest("WEBSITE")}
                      className={`px-3 py-2.5 rounded-xl text-xs font-medium border transition-all ${campaignDest === "WEBSITE" ? "bg-violet-500/10 border-violet-500/30 text-violet-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500 hover:text-gray-300"}`}>
                      Website (Pixel)
                    </button>
                    <button type="button" onClick={() => setCampaignDest("INSTANT_FORM")}
                      className={`px-3 py-2.5 rounded-xl text-xs font-medium border transition-all flex items-center justify-center gap-1.5 ${campaignDest === "INSTANT_FORM" ? "bg-cyan-500/10 border-cyan-500/30 text-cyan-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500 hover:text-gray-300"}`}>
                      <ClipboardList className="w-3 h-3" /> Instant Form
                    </button>
                    <button type="button" onClick={() => { setCampaignDest("PHONE_CALL"); }}
                      className={`px-3 py-2.5 rounded-xl text-xs font-medium border transition-all flex items-center justify-center gap-1.5 ${campaignDest === "PHONE_CALL" ? "bg-orange-500/10 border-orange-500/30 text-orange-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500 hover:text-gray-300"}`}>
                      <Phone className="w-3 h-3" /> Phone Calls
                    </button>
                    <button type="button" onClick={() => { setCampaignDest("MESSAGING"); if (msgApps.length === 0) setMsgApps(["MESSENGER"]); }}
                      className={`px-3 py-2.5 rounded-xl text-xs font-medium border transition-all flex items-center justify-center gap-1.5 ${campaignDest === "MESSAGING" ? "bg-blue-500/10 border-blue-500/30 text-blue-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500 hover:text-gray-300"}`}>
                      <MessagesSquare className="w-3 h-3" /> Messaging
                    </button>
                  </div>

                  {/* MESSAGING — multi-select checkboxes */}
                  {campaignDest === "MESSAGING" && (
                    <div className="mt-2 space-y-2">
                      <div className="px-3 py-2.5 rounded-xl bg-blue-500/[0.05] border border-blue-500/15">
                        <p className="text-[11px] text-blue-400 font-medium mb-2">Select Messaging Apps</p>
                        <div className="space-y-1.5">
                          {[
                            { key: "MESSENGER", label: "Facebook Messenger", color: "blue" },
                            { key: "INSTAGRAM_DM", label: "Instagram Direct", color: "pink" },
                            { key: "WHATSAPP", label: "WhatsApp", color: "emerald" },
                          ].map((app) => (
                            <label key={app.key} className="flex items-center gap-2 cursor-pointer">
                              <input type="checkbox" checked={msgApps.includes(app.key)}
                                onChange={(e) => {
                                  if (e.target.checked) setMsgApps([...msgApps, app.key]);
                                  else setMsgApps(msgApps.filter((a) => a !== app.key));
                                }}
                                className={`w-3.5 h-3.5 rounded border-white/20 bg-white/[0.04] text-${app.color}-500 focus:ring-${app.color}-500/20`} />
                              <span className="text-xs text-gray-300">{app.label}</span>
                            </label>
                          ))}
                        </div>
                        {msgApps.length === 0 && (
                          <p className="text-[10px] text-red-400 mt-1">Select at least one messaging app.</p>
                        )}
                      </div>
                      {msgApps.includes("WHATSAPP") && (
                        <div>
                          <input type="text" value={waNumber} onChange={(e) => setWaNumber(e.target.value)}
                            placeholder="WhatsApp number, e.g. 923001234567"
                            className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-emerald-500/40 transition-all" />
                          <p className="mt-1 text-[10px] text-gray-500">Required for WhatsApp routing</p>
                        </div>
                      )}
                      <p className="text-[10px] text-gray-500">Meta will route conversations to all selected apps. Users choose their preferred app.</p>
                    </div>
                  )}

                  {/* PHONE CALL */}
                  {campaignDest === "PHONE_CALL" && (
                    <div className="mt-2">
                      <input type="text" value={callPhone} onChange={(e) => setCallPhone(e.target.value)}
                        placeholder="Phone number with country code, e.g. +923001234567"
                        className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-orange-500/40 transition-all" />
                      <p className="mt-1 text-[10px] text-gray-500">Users will see a &quot;Call Now&quot; button. Optimizes for call leads.</p>
                    </div>
                  )}

                  {/* INSTANT FORM */}
                  {campaignDest === "INSTANT_FORM" && (
                    <div className="mt-2 space-y-2">
                      <div className="px-3 py-2.5 rounded-xl bg-cyan-500/[0.05] border border-cyan-500/15">
                        <p className="text-[11px] text-cyan-400 font-medium mb-1">Lead Generation Form</p>
                        <p className="text-[10px] text-gray-500">Collect leads directly on Meta — no landing page needed. Form opens in-app when user taps the ad.</p>
                      </div>
                      {draft.lead_form_id ? (
                        <div className="flex items-center justify-between px-3 py-2 rounded-xl bg-cyan-500/[0.08] border border-cyan-500/20">
                          <div className="flex items-center gap-2">
                            <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400" />
                            <span className="text-xs text-cyan-300">{attachedLeadFormName || draft.lead_form_id}</span>
                          </div>
                          <button onClick={() => setShowLeadFormModal(true)} className="text-[10px] text-cyan-400 hover:text-cyan-300 font-medium">Change</button>
                        </div>
                      ) : (
                        <button onClick={() => setShowLeadFormModal(true)}
                          className="w-full flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl text-xs font-medium bg-cyan-500/[0.08] border border-dashed border-cyan-500/25 text-cyan-400 hover:bg-cyan-500/[0.12] transition-all">
                          <ClipboardList className="w-3 h-3" />
                          Create or Select Lead Form
                        </button>
                      )}
                    </div>
                  )}

                  {/* WEBSITE — conversion event picker */}
                  {campaignDest === "WEBSITE" && (
                    <div className="mt-2">
                      <label className="text-[11px] text-gray-500 mb-1 block">Optimization Event</label>
                      <select value={conversionEvent} onChange={(e) => setConversionEvent(e.target.value)}
                        className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all">
                        {CONVERSION_EVENTS.map((ev) => (
                          <option key={ev.value} value={ev.value}>{ev.label}</option>
                        ))}
                      </select>
                      <p className="mt-1 text-[10px] text-gray-500">Choose the specific action you want Meta to find people for.</p>
                    </div>
                  )}
                </div>
              )}

              {/* Campaign Objective */}
              {draft.draft_type === "paid" && (
                <div>
                  <label className="text-[11px] text-gray-500 mb-1 block">Campaign Objective</label>
                  <select value={campaignObjective} onChange={(e) => setCampaignObjective(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all">
                    <option value="">Auto-detect</option>
                    <option value="OUTCOME_LEADS">Leads</option>
                    <option value="OUTCOME_SALES">Sales</option>
                    <option value="OUTCOME_TRAFFIC">Traffic</option>
                    <option value="OUTCOME_ENGAGEMENT">Engagement</option>
                    <option value="OUTCOME_AWARENESS">Awareness</option>
                  </select>
                  <p className="mt-1 text-[10px] text-gray-500">
                    {campaignObjective
                      ? `Will use ${campaignObjective.replace("OUTCOME_", "")} objective`
                      : (() => {
                          const _LE = ["LEAD", "COMPLETE_REGISTRATION", "CONTACT", "SCHEDULE"];
                          const dest = campaignDest;
                          const evt = conversionEvent;
                          if (dest === "INSTAGRAM_DM") return "Auto: Engagement (IG DM)";
                          if (dest === "INSTANT_FORM") return "Auto: Leads (Instant Form)";
                          if (dest === "WHATSAPP") return "Auto: Traffic (WhatsApp)";
                          if (dest === "MESSAGING") return "Auto: Engagement (Messaging)";
                          if (dest === "PHONE_CALL") return "Auto: Leads (Phone)";
                          if (draft.pixel_id) return _LE.includes(evt) ? "Auto: Leads (pixel + event)" : "Auto: Sales (pixel + event)";
                          return "Auto: Traffic (no pixel)";
                        })()
                    }
                  </p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1.5 block">CTA Button</label>
                  <select value={ctaType} onChange={(e) => setCtaType(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all">
                    {CTA_OPTIONS.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
                  </select>
                </div>
                {draft.draft_type === "paid" && (
                  <div>
                    <label className="text-xs text-gray-500 mb-1.5 block">Budget / day</label>
                    <div className="flex gap-1.5">
                      <select value={budgetCurrency} onChange={(e) => setBudgetCurrency(e.target.value)}
                        className="w-24 px-2 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all">
                        {BUDGET_CURRENCIES.map((c) => <option key={c.value} value={c.value}>{c.symbol} {c.value}</option>)}
                      </select>
                      <input type="number" value={budget} onChange={(e) => setBudget(e.target.value)} min={1}
                        className="flex-1 px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all" />
                    </div>
                  </div>
                )}
                {draft.draft_type === "paid" && (
                  <div>
                    <label className="text-xs text-gray-500 mb-1.5 block">Ad Placement</label>
                    <select value={draftPlacement} onChange={(e) => setDraftPlacement(e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all">
                      <option value="BOTH">Auto / Both (Recommended)</option>
                      <option value="INSTAGRAM_ONLY">Instagram Only</option>
                      <option value="FACEBOOK_ONLY">Facebook Only</option>
                    </select>
                  </div>
                )}
              </div>
              {draft.draft_type === "paid" && (
                <div className="col-span-2">
                  <label className="text-xs text-gray-500 mb-1.5 block">Destination URL (optional)</label>
                  <input type="url" value={destinationUrl} onChange={(e) => setDestinationUrl(e.target.value)}
                    placeholder={fallbackUrl ? `Default: ${fallbackUrl}` : "Override link for this ad"}
                    className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" />
                  {destinationUrl ? (
                    <p className="mt-1 text-[10px] text-emerald-400">This ad will link to: {destinationUrl}</p>
                  ) : fallbackUrl ? (
                    <p className="mt-1 text-[10px] text-gray-500">Using product URL: <span className="text-violet-400">{fallbackUrl}</span></p>
                  ) : null}
                </div>
              )}
              {draft.draft_type === "paid" && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <label className="text-xs text-gray-500">Profit Margin / Sale (optional)</label>
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => setShowProfitTooltip(!showProfitTooltip)}
                        className="w-4 h-4 rounded-full bg-white/[0.06] border border-white/[0.1] text-gray-500 hover:text-gray-300 text-[10px] font-bold flex items-center justify-center transition-colors"
                      >?</button>
                      {showProfitTooltip && (
                        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-72 p-3 rounded-xl bg-[#1a1a2e] border border-white/[0.1] text-[11px] text-gray-300 leading-relaxed shadow-xl z-20">
                          Why we ask: By knowing your profit per sale, our AI can set a &apos;Cost Cap&apos; on Meta. This prevents the algorithm from spending your budget on expensive clicks that don&apos;t result in profitable sales. It acts as a safety net for your budget.
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-1.5">
                    <span className="flex items-center px-2.5 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-gray-400 text-sm">
                      {BUDGET_CURRENCIES.find(c => c.value === budgetCurrency)?.symbol || "$"}
                    </span>
                    <input type="number" value={profitMargin} onChange={(e) => setProfitMargin(e.target.value)} min={0}
                      placeholder="e.g. 400 — leave blank for Highest Volume"
                      className="flex-1 px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" />
                  </div>
                  {parseFloat(profitMargin) > 0 && parseFloat(profitMargin) < 100 && (
                    <p className="mt-1.5 text-[11px] text-amber-400 bg-amber-500/[0.08] border border-amber-500/15 rounded-lg px-2.5 py-1.5">
                      Note: A very low profit goal might prevent your ads from showing if the market is competitive. Consider leaving it blank for the first 3 days to gather data.
                    </p>
                  )}
                  {parseFloat(profitMargin) >= 100 && (
                    <p className="mt-1.5 text-[11px] text-gray-500">
                      Cost Cap will be set to {BUDGET_CURRENCIES.find(c => c.value === budgetCurrency)?.symbol || "$"}{Math.round(parseFloat(profitMargin) * 0.7)} (70% of margin)
                    </p>
                  )}
                </div>
              )}
              {/* Geo Targeting Override */}
              {draft.draft_type === "paid" && (
                <div className="bg-blue-500/[0.04] border border-blue-500/10 rounded-xl px-4 py-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <Target className="w-4 h-4 text-blue-400" />
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-blue-400">Geo Targeting (Override)</p>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-gray-500 mb-1.5 block">
                        Target Countries
                        <span className="text-[10px] text-gray-600 ml-1">(select multiple — Meta will target all)</span>
                      </label>
                      {(() => {
                        const selectedCodes = editCountry
                          ? editCountry.split(",").map((c) => c.trim()).filter(Boolean)
                          : [];
                        const removeCountry = (code: string) => {
                          const next = selectedCodes.filter((c) => c !== code);
                          setEditCountry(next.join(","));
                        };
                        const addCountry = (code: string) => {
                          if (!code || selectedCodes.includes(code)) return;
                          setEditCountry([...selectedCodes, code].join(","));
                        };
                        return (
                          <div className="space-y-2">
                            {/* Selected chips */}
                            {selectedCodes.length > 0 && (
                              <div className="flex flex-wrap gap-1.5 p-2 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                                {selectedCodes.map((code) => (
                                  <span
                                    key={code}
                                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-blue-500/15 border border-blue-500/30 text-[11px] text-blue-300 font-medium"
                                  >
                                    {COUNTRY_NAMES[code as keyof typeof COUNTRY_NAMES] || code}
                                    <button
                                      onClick={() => removeCountry(code)}
                                      className="text-blue-400 hover:text-red-400 transition-colors"
                                      type="button"
                                    >
                                      ×
                                    </button>
                                  </span>
                                ))}
                              </div>
                            )}
                            {/* Add country dropdown */}
                            <select
                              value=""
                              onChange={(e) => { addCountry(e.target.value); e.target.value = ""; }}
                              className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all"
                            >
                              <option value="">
                                {selectedCodes.length === 0 ? "Use default — pick countries..." : "+ Add another country..."}
                              </option>
                              {Object.entries(COUNTRY_NAMES)
                                .filter(([code]) => !selectedCodes.includes(code))
                                .map(([code, name]) => (
                                  <option key={code} value={code}>{name}</option>
                                ))}
                            </select>
                          </div>
                        );
                      })()}
                    </div>
                    <div>
                      <label className="text-xs text-gray-500 mb-1.5 block">Target Cities (optional)</label>
                      <input type="text" value={editCities} onChange={(e) => setEditCities(e.target.value)}
                        placeholder="e.g. Lahore, Karachi, Islamabad"
                        className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" />
                    </div>
                  </div>
                  <p className="text-[10px] text-gray-500">Leave cities blank to target the entire country. Separate cities with commas.</p>
                </div>
              )}
              <div className="flex gap-2 pt-1">
                <button onClick={handleSaveEdits} disabled={saving}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500 text-white transition-all disabled:opacity-50">
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  Save Changes
                </button>
                <button onClick={() => { setEditing(false); setHeadline(draft.headline ?? ""); setBodyText(draft.body_text); setCtaType(draft.cta_type ?? "SHOP_NOW"); setBudget(String(draft.proposed_budget ?? "")); setEditCountry(_initCountry); setEditCities(_initCities); }}
                  className="px-4 py-2.5 rounded-xl text-sm text-gray-400 hover:text-white bg-white/[0.03] border border-white/[0.06] transition-all">
                  Cancel
                </button>
              </div>
            </>
          ) : (
            /* ── View Mode ───────────────── */
            <>
              {draft.headline && <h2 className="text-xl font-bold text-white leading-tight">{draft.headline}</h2>}
              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">{draft.body_text}</p>

              <div className="flex flex-wrap items-center gap-4 text-xs text-gray-500">
                {draft.draft_type === "paid" && draft.proposed_budget && (
                  <span className="flex items-center gap-1"><DollarSign className="w-3.5 h-3.5" />{(BUDGET_CURRENCIES.find(c => c.value === ((draft.targeting as Record<string,string>)?.budget_currency ?? budgetCurrency))?.symbol || "$")}{draft.proposed_budget}/day</span>
                )}
                {draft.cta_type && (
                  <span className="flex items-center gap-1"><Target className="w-3.5 h-3.5" />{draft.cta_type.replace(/_/g, " ")}</span>
                )}
                <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" />{new Date(draft.created_at).toLocaleString()}</span>
              </div>
              {draft.destination_url && (
                <div className="flex items-center gap-2 text-xs text-gray-500 bg-white/[0.02] border border-white/[0.06] rounded-lg px-3 py-2">
                  <span className="text-gray-600">Destination:</span>
                  <a href={draft.destination_url} target="_blank" rel="noopener noreferrer" className="text-violet-400 hover:text-violet-300 truncate">{draft.destination_url}</a>
                </div>
              )}

              {draft.ai_reasoning && (
                <div className="flex items-start gap-2.5 bg-violet-500/[0.05] border border-violet-500/10 rounded-xl px-4 py-3">
                  <Sparkles className="w-4 h-4 text-violet-400 mt-0.5 shrink-0" />
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-violet-400 mb-1">AI Reasoning</p>
                    <p className="text-xs text-gray-400 leading-relaxed">{draft.ai_reasoning}</p>
                  </div>
                </div>
              )}

              {draft.status === "failed" && draft.error_message && (
                <div className="flex items-start gap-2 bg-red-500/[0.05] border border-red-500/10 rounded-xl px-4 py-3">
                  <XCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
                  <p className="text-sm text-red-300">{draft.error_message}</p>
                </div>
              )}

              {draft.status === "active" && draft.meta_ad_id && (
                <div className="flex items-center justify-between gap-2 bg-emerald-500/[0.05] border border-emerald-500/10 rounded-xl px-4 py-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <p className="text-sm text-emerald-300">Live on Meta — Ad ID: {draft.meta_ad_id}</p>
                  </div>
                  <button
                    onClick={() => onPause(draft.id)}
                    disabled={loading === draft.id}
                    className="text-xs font-medium text-amber-400 hover:text-amber-300 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/15 transition-all disabled:opacity-50"
                  >
                    {loading === draft.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Pause & Edit"}
                  </button>
                </div>
              )}

              {/* Geo-Cultural Targeting Spec (Detail View) */}
              {draft.draft_type === "paid" && (() => {
                const spec = parseTargetingSpec(draft.targeting_spec);
                const draftTgt2 = (draft.targeting || {}) as Record<string, unknown>;
                const country = (draftTgt2.target_country as string) || spec?.target_country || draft.target_country;
                const viewCities = (draftTgt2.target_cities as string[]) || [];
                const interests = spec?.validated_interests;
                if (!country && !interests?.length) return null;
                return (
                  <div className="bg-blue-500/[0.04] border border-blue-500/10 rounded-xl px-4 py-4 space-y-2">
                    <div className="flex items-center gap-2">
                      <Target className="w-4 h-4 text-blue-400" />
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-blue-400">
                        Geo-Cultural Targeting: {country ? COUNTRY_NAMES[country] || country : ""}
                        {viewCities.length > 0 && ` — ${viewCities.join(", ")}`}
                      </p>
                    </div>
                    {interests && interests.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {interests.map((interest: { id: string; name: string; audience_size?: number }) => (
                          <span key={interest.id} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-blue-500/10 text-xs text-blue-300 border border-blue-500/15">
                            {interest.name}
                            {interest.audience_size && (
                              <span className="text-[9px] text-blue-400/50">
                                ({interest.audience_size > 1000000 ? `${(interest.audience_size / 1000000).toFixed(1)}M` : `${(interest.audience_size / 1000).toFixed(0)}K`})
                              </span>
                            )}
                          </span>
                        ))}
                        {spec?.validated_behaviors?.map((b: { id: string; name: string; audience_size?: number }) => (
                          <span key={b.id} className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-amber-500/10 text-xs text-amber-300 border border-amber-500/15">
                            ⊙ {b.name}
                            {b.audience_size && (
                              <span className="text-[9px] text-amber-400/50">
                                ({b.audience_size > 1000000 ? `${(b.audience_size / 1000000).toFixed(1)}M` : `${(b.audience_size / 1000).toFixed(0)}K`})
                              </span>
                            )}
                          </span>
                        ))}
                      </div>
                    )}
                    {spec?.advantage_plus_expanded && (
                      <div className="flex items-center gap-2 mt-1">
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-gradient-to-r from-purple-500/15 to-blue-500/15 text-purple-300 border border-purple-500/20">
                          <span className="text-sm">✨</span> Advantage+ Auto-Expansion ON
                        </span>
                        <span className="text-[10px] text-gray-500 italic">
                          Highly specific niche — Meta AI expands beyond these interests to find ideal matches
                        </span>
                      </div>
                    )}
                    {spec?.suggested_keywords && spec.suggested_keywords.length > 0 && (
                      <p className="text-[10px] text-gray-500">
                        AI suggested: {spec.suggested_keywords.join(", ")}
                      </p>
                    )}
                  </div>
                );
              })()}

              {/* Tracking & Optimization */}
              {draft.draft_type === "paid" && (
                <div className="bg-amber-500/[0.04] border border-amber-500/10 rounded-xl px-4 py-4 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Zap className="w-4 h-4 text-amber-400" />
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-400">Tracking & Optimization</p>
                    </div>
                    {isPending && !["WHATSAPP", "INSTAGRAM_DM", "INSTANT_FORM", "MESSAGING", "PHONE_CALL"].includes(draft.destination_type || "") && (
                      <button onClick={() => setShowPixelModal(true)}
                        className="text-[11px] text-amber-400 hover:text-amber-300 font-medium px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 transition-all">
                        {draft.pixel_id ? "Change" : "Attach Pixel"}
                      </button>
                    )}
                  </div>
                  {draft.destination_type === "MESSAGING" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-xs text-blue-400 border border-blue-500/15">
                        <MessagesSquare className="w-3 h-3" />
                        Messaging
                      </span>
                      {(draft.selected_messaging_apps || []).map((app: string) => (
                        <span key={app} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-white/[0.04] text-[10px] text-gray-300 border border-white/[0.08]">
                          {app === "INSTAGRAM_DM" ? "IG Direct" : app === "WHATSAPP" ? "WhatsApp" : "Messenger"}
                        </span>
                      ))}
                      {draft.selected_messaging_apps?.includes("WHATSAPP") && draft.whatsapp_number && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-xs text-emerald-400 border border-emerald-500/15">
                          WA: {draft.whatsapp_number}
                        </span>
                      )}
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-xs text-blue-400 border border-blue-500/15">
                        <Target className="w-3 h-3" />
                        Optimize for: Conversations
                      </span>
                    </div>
                  ) : draft.destination_type === "PHONE_CALL" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-orange-500/10 text-xs text-orange-400 border border-orange-500/15">
                        <Phone className="w-3 h-3" />
                        Phone Calls
                      </span>
                      {draft.call_phone_number && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-xs text-emerald-400 border border-emerald-500/15">
                          <CheckCircle2 className="w-3 h-3" />
                          {draft.call_phone_number}
                        </span>
                      )}
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-xs text-blue-400 border border-blue-500/15">
                        <Target className="w-3 h-3" />
                        Optimize for: Leads
                      </span>
                    </div>
                  ) : draft.destination_type === "WHATSAPP" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-xs text-emerald-400 border border-emerald-500/15">
                        <CheckCircle2 className="w-3 h-3" />
                        WhatsApp: {draft.whatsapp_number || "Not set"}
                      </span>
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-xs text-blue-400 border border-blue-500/15">
                        <Target className="w-3 h-3" />
                        Optimize for: Conversations
                      </span>
                    </div>
                  ) : draft.destination_type === "INSTAGRAM_DM" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-pink-500/10 text-xs text-pink-400 border border-pink-500/15">
                        <MessageCircle className="w-3 h-3" />
                        Instagram DM
                      </span>
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-xs text-blue-400 border border-blue-500/15">
                        <Target className="w-3 h-3" />
                        Optimize for: Conversations
                      </span>
                    </div>
                  ) : draft.destination_type === "INSTANT_FORM" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-cyan-500/10 text-xs text-cyan-400 border border-cyan-500/15">
                        <ClipboardList className="w-3 h-3" />
                        Instant Form
                      </span>
                      {draft.lead_form_id ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-xs text-emerald-400 border border-emerald-500/15">
                          <CheckCircle2 className="w-3 h-3" />
                          Form: {attachedLeadFormName || draft.lead_form_id}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-500/10 text-xs text-amber-400 border border-amber-500/15">
                          No form attached
                        </span>
                      )}
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-500/10 text-xs text-blue-400 border border-blue-500/15">
                        <Target className="w-3 h-3" />
                        Optimize for: Leads
                      </span>
                    </div>
                  ) : draft.pixel_id ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-500/10 text-xs text-emerald-400 border border-emerald-500/15">
                        <CheckCircle2 className="w-3 h-3" />
                        Pixel: {attachedPixelName || draft.pixel_id}
                      </span>
                      {draft.conversion_event && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-violet-500/10 text-xs text-violet-400 border border-violet-500/15">
                          <Target className="w-3 h-3" />
                          Optimize for: {draft.conversion_event.replace(/_/g, " ")}
                        </span>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-gray-500">No pixel attached — ad will optimize for traffic (link clicks) instead of conversions.</p>
                  )}
                </div>
              )}

              {/* Campaign Objective badge */}
              {draft.draft_type === "paid" && (
                <div className="flex items-center gap-2">
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-500/10 text-xs text-indigo-400 border border-indigo-500/15">
                    <Target className="w-3 h-3" />
                    Objective: {draft.campaign_objective
                      ? draft.campaign_objective.replace("OUTCOME_", "")
                      : (() => {
                          const _LE = ["LEAD", "COMPLETE_REGISTRATION", "CONTACT", "SCHEDULE"];
                          const dest = draft.destination_type || "WEBSITE";
                          const evt = (draft.conversion_event || "PURCHASE").toUpperCase();
                          if (dest === "INSTAGRAM_DM") return "Engagement (auto)";
                          if (dest === "INSTANT_FORM") return "Leads (auto)";
                          if (dest === "WHATSAPP") return "Traffic (auto)";
                          if (dest === "MESSAGING") return "Engagement (auto)";
                          if (dest === "PHONE_CALL") return "Leads (auto)";
                          if (draft.pixel_id) return _LE.includes(evt) ? "Leads (auto)" : "Sales (auto)";
                          return "Traffic (auto)";
                        })()
                    }
                  </span>
                </div>
              )}

              {ab && (ab.headline_b || ab.body_text_b) && (
                <div className="bg-blue-500/[0.04] border border-blue-500/10 rounded-xl px-4 py-4 space-y-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-blue-400">A/B Variants</p>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-[10px] text-gray-500 mb-1">Variant A</p>
                      {ab.headline_a && <p className="text-sm text-white font-medium mb-1">{ab.headline_a}</p>}
                      {ab.body_text_a && <p className="text-xs text-gray-400 leading-relaxed">{ab.body_text_a}</p>}
                    </div>
                    <div>
                      <p className="text-[10px] text-gray-500 mb-1">Variant B</p>
                      {ab.headline_b && <p className="text-sm text-white font-medium mb-1">{ab.headline_b}</p>}
                      {ab.body_text_b && <p className="text-xs text-gray-400 leading-relaxed">{ab.body_text_b}</p>}
                    </div>
                  </div>
                </div>
              )}

              {isPending && (
                <div className="flex items-center gap-3 pt-2">
                  <button onClick={() => { onApprove(draft.id); onClose(); }} disabled={loading === draft.id}
                    className="flex-1 flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all glow-blue disabled:opacity-50">
                    {loading === draft.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
                    Approve & Schedule
                  </button>
                  <button onClick={() => { onReject(draft.id); onClose(); }} disabled={loading === draft.id}
                    className="flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-red-400 bg-white/[0.03] hover:bg-red-500/[0.06] border border-white/[0.06] hover:border-red-500/20 transition-all disabled:opacity-50">
                    <RefreshCw className="w-4 h-4" /> Reject
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
      {showPixelModal && (
        <PixelAttachModal
          currentPixelId={draft.pixel_id}
          currentEvent={draft.conversion_event}
          onClose={() => setShowPixelModal(false)}
          onAttach={(pixelId, pixelName, event) => {
            onDraftUpdate(draft.id, { pixel_id: pixelId, conversion_event: event });
            setAttachedPixelName(pixelName);
            setShowPixelModal(false);
          }}
        />
      )}
      {showLeadFormModal && (
        <LeadFormBuilder
          currentFormId={draft.lead_form_id}
          draftId={draft.id}
          onClose={() => setShowLeadFormModal(false)}
          onFormCreated={(formId, formName) => {
            onDraftUpdate(draft.id, { lead_form_id: formId });
            setAttachedLeadFormName(formName);
            setShowLeadFormModal(false);
          }}
        />
      )}
    </div>
  );
}

/* ── Draft card ────────────────────────────────────────────── */

function DraftCard({
  draft,
  onApprove,
  onReject,
  onPause,
  onImageUpdate,
  onDraftUpdate,
  onOpen,
  loading,
  budgetCurrency,
  selected,
  onToggleSelect,
}: {
  draft: Draft;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onPause: (id: string) => void;
  onImageUpdate: (id: string, imageUrl: string) => void;
  onDraftUpdate: (id: string, fields: Record<string, unknown>) => void;
  onOpen: (draft: Draft) => void;
  budgetCurrency: string;
  loading: string | null;
  selected?: boolean;
  onToggleSelect?: (id: string) => void;
}) {
  const isPending = draft.status === "pending";
  const isFailed = draft.status === "failed";
  const canAttachCreative = isPending || isFailed;
  const [showCreativeOptions, setShowCreativeOptions] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [showCardPixelModal, setShowCardPixelModal] = useState(false);
  const [showCardLeadFormModal, setShowCardLeadFormModal] = useState(false);
  const [uploadingThumb, setUploadingThumb] = useState(false);

  const cardMediaItems = getMediaItems(draft);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setUploading(true);
    setUploadError(null);
    try {
      const currentItems: MediaItem[] = [...(draft.media_items || [])];
      for (let i = 0; i < files.length; i++) {
        if (currentItems.length >= 10) break;
        const file = files[i];
        const { data } = await api.uploadProductImage(file);
        const mtype = file.type.startsWith("video/") ? "video" : "image";
        currentItems.push({ type: mtype as "image" | "video", url: data.url });
      }
      const updates: Record<string, unknown> = { media_items: currentItems, image_url: currentItems[0]?.url || null };
      // If a failed draft is having its missing creative supplied, revert to pending so it can be re-approved.
      if (draft.status === "failed") { updates.status = "pending"; updates.error_message = null; }
      onDraftUpdate(draft.id, updates);
      setShowCreativeOptions(false);
    } catch {
      setUploadError("Failed to read file.");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleThumbnailUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingThumb(true);
    try {
      const { data } = await api.uploadProductImage(file);
      onDraftUpdate(draft.id, { thumbnail_url: data.url });
    } catch { /* empty */ }
    setUploadingThumb(false);
  };

  const handleImageUrlSave = () => {
    if (imageUrl.trim()) {
      const url = imageUrl.trim();
      const mtype = isVideoUrl(url) ? "video" : "image";
      const updates: Record<string, unknown> = { media_items: [{ type: mtype, url }], image_url: url };
      if (draft.status === "failed") { updates.status = "pending"; updates.error_message = null; }
      onDraftUpdate(draft.id, updates);
      setImageUrl("");
      setShowCreativeOptions(false);
    }
  };

  return (
    <>
    <div className="glass rounded-2xl overflow-hidden hover:bg-white/[0.04] transition-all duration-300 group">
      {/* Image area */}
      <div
        className="relative h-40 bg-gradient-to-br from-white/[0.03] to-white/[0.01] flex items-center justify-center border-b border-white/[0.06] cursor-pointer"
        onClick={() => {
          if (cardMediaItems.length === 0 && canAttachCreative) {
            setShowCreativeOptions(!showCreativeOptions);
          } else {
            onOpen(draft);
          }
        }}
      >
        {cardMediaItems.length > 0 ? (
          <>
            {cardMediaItems[0].type === "video" || isVideoUrl(cardMediaItems[0].url) ? (
              <video src={resolveImageUrl(cardMediaItems[0].url)} muted loop autoPlay playsInline className="w-full h-full object-cover" />
            ) : (
              <img src={resolveImageUrl(cardMediaItems[0].url)} alt={draft.headline ?? "Ad creative"} className="w-full h-full object-cover" />
            )}
            {cardMediaItems.length > 1 && (
              <div className="absolute top-2 right-2 px-2 py-0.5 rounded-md bg-black/60 backdrop-blur-sm text-[10px] font-medium text-white border border-white/10">
                {cardMediaItems.length} creatives
              </div>
            )}
          </>
        ) : canAttachCreative ? (
          <div className="flex flex-col items-center gap-2 text-gray-500 hover:text-gray-300 transition-colors">
            <ImageIcon className="w-8 h-8" />
            <span className="text-xs font-medium">{isFailed ? "Add Creative & Retry" : "Add Creative"}</span>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 text-gray-600">
            <ImageIcon className="w-8 h-8" />
            <span className="text-xs">No creative</span>
          </div>
        )}
        {/* Badges overlay */}
        <div className="absolute top-3 left-3 flex items-center gap-1.5 flex-wrap max-w-[calc(100%-3rem)]">
          <TypeBadge type={draft.draft_type} onToggle={draft.status === "pending" ? () => {
            const newType = draft.draft_type === "paid" ? "organic" : "paid";
            const updates: Record<string, unknown> = { draft_type: newType };
            if (newType === "paid" && !draft.proposed_budget) {
              updates.proposed_budget = 10;
            }
            onDraftUpdate(draft.id, updates);
          } : undefined} />
          <StatusBadge status={draft.status} />
          {draft.special_ad_category && SAC_DISPLAY[draft.special_ad_category] && (
            <span
              className={`group/sac relative px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase tracking-wider border ${SAC_DISPLAY[draft.special_ad_category].color}`}
              title={draft.special_ad_category_reasoning || `Meta Special Ad Category: ${SAC_DISPLAY[draft.special_ad_category].label}`}
            >
              SAC · {SAC_DISPLAY[draft.special_ad_category].label}
              {draft.special_ad_category_reasoning && (
                <span className="invisible group-hover/sac:visible absolute left-0 top-full mt-1 z-50 w-64 p-2 rounded-lg bg-black/95 border border-white/10 text-[10px] text-gray-300 normal-case font-normal tracking-normal leading-snug shadow-2xl">
                  <strong className="text-white">Why this category:</strong> {draft.special_ad_category_reasoning}
                  {draft.special_ad_category_confidence != null && (
                    <span className="block mt-1 text-gray-500">
                      Confidence: {Math.round((draft.special_ad_category_confidence ?? 0) * 100)}%
                    </span>
                  )}
                </span>
              )}
            </span>
          )}
        </div>
        {/* Expand icon */}
        <button
          onClick={(e) => { e.stopPropagation(); onOpen(draft); }}
          className="absolute top-3 right-3 p-1.5 rounded-lg bg-black/40 text-gray-400 hover:text-white opacity-0 group-hover:opacity-100 transition-all"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
        {/* A/B test selection checkbox — only for pending paid drafts */}
        {isPending && draft.draft_type === "paid" && onToggleSelect && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggleSelect(draft.id); }}
            className={`absolute bottom-3 right-3 w-6 h-6 rounded-lg border-2 flex items-center justify-center transition-all ${
              selected
                ? "bg-blue-500 border-blue-500 text-white"
                : "bg-black/40 border-white/30 text-transparent hover:border-blue-400"
            }`}
          >
            {selected && <CheckCircle2 className="w-3.5 h-3.5" />}
          </button>
        )}
      </div>

      {/* Creative options panel */}
      {canAttachCreative && showCreativeOptions && cardMediaItems.length === 0 && (
        <div className="px-4 py-3 border-b border-white/[0.06] bg-violet-500/[0.03] space-y-2.5 animate-fade-in">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-violet-400">Attach Creative</p>
          <div className="flex gap-2">
            <button
              onClick={() => alert("AI image generation coming soon! Upload an image or paste a URL for now.")}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-gradient-to-r from-violet-600/80 to-blue-600/80 text-white transition-all"
            >
              <Wand2 className="w-3 h-3" />
              Generate with AI
            </button>
            <label className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-white/[0.05] border border-white/[0.08] text-gray-300 hover:bg-white/[0.08] transition-all cursor-pointer">
              {uploading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
              Upload Media (1-10)
              <input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" multiple onChange={handleFileUpload} className="hidden" />
            </label>
          </div>
          {uploadError && (
            <p className="text-[11px] text-red-400 bg-red-500/[0.08] border border-red-500/20 rounded-lg px-2.5 py-1.5">{uploadError}</p>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              value={imageUrl}
              onChange={(e) => setImageUrl(e.target.value)}
              placeholder="Or paste image URL..."
              className="flex-1 px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-white text-xs placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all"
            />
            <button
              onClick={handleImageUrlSave}
              disabled={!imageUrl.trim()}
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.06] border border-white/[0.08] text-gray-300 hover:bg-white/[0.1] transition-all disabled:opacity-40"
            >
              Save
            </button>
          </div>
        </div>
      )}

      {/* Content — click to open full view */}
      <div className="p-5 cursor-pointer" onClick={() => onOpen(draft)}>
        {draft.headline && (
          <h3 className="text-white font-semibold mb-1.5 line-clamp-1">{draft.headline}</h3>
        )}
        <p className="text-sm text-gray-400 leading-relaxed line-clamp-3 mb-4">
          {draft.body_text}
        </p>

        {/* Meta row */}
        <div className="flex items-center gap-3 text-xs text-gray-600 mb-4">
          {draft.draft_type === "paid" && draft.proposed_budget && (
            <span className="flex items-center gap-1">
              <DollarSign className="w-3 h-3" />
              {BUDGET_CURRENCIES.find(c => c.value === ((draft.targeting as Record<string,string>)?.budget_currency ?? budgetCurrency))?.symbol || "$"}{draft.proposed_budget}/day
            </span>
          )}
          {draft.cta_type && (
            <span className="flex items-center gap-1">
              <Target className="w-3 h-3" />
              {draft.cta_type.replace(/_/g, " ")}
            </span>
          )}
          <span className="flex items-center gap-1 ml-auto">
            <Clock className="w-3 h-3" />
            {new Date(draft.created_at).toLocaleDateString()}
          </span>
        </div>

        {/* AI reasoning */}
        {draft.ai_reasoning && (
          <div className="flex items-start gap-2 bg-violet-500/[0.05] border border-violet-500/10 rounded-lg px-3 py-2 mb-4">
            <Sparkles className="w-3.5 h-3.5 text-violet-400 mt-0.5 shrink-0" />
            <p className="text-xs text-gray-400 leading-relaxed line-clamp-2">{draft.ai_reasoning}</p>
          </div>
        )}

        {/* Error + Convert-to-Draft action */}
        {draft.status === "failed" && (
          <div className="flex items-center justify-between gap-3 mb-4">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDraftUpdate(draft.id, { status: "pending", error_message: null });
              }}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium bg-violet-500/10 hover:bg-violet-500/15 text-violet-300 border border-violet-500/20 transition-all"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Convert to Draft (edit & retry)
            </button>
          </div>
        )}
        {draft.status === "failed" && draft.error_message && (
          <div className="flex items-start gap-2 bg-red-500/[0.05] border border-red-500/10 rounded-lg px-3 py-2 mb-4">
            <XCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
            <p className="text-xs text-red-300 line-clamp-1">{draft.error_message}</p>
          </div>
        )}

        {/* Active Meta ID */}
        {draft.status === "active" && draft.meta_ad_id && (
          <div className="flex items-center justify-between gap-2 bg-emerald-500/[0.05] border border-emerald-500/10 rounded-lg px-3 py-2 mb-4">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <p className="text-xs text-emerald-300">Live — {draft.meta_ad_id}</p>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); onPause(draft.id); }}
              disabled={loading === draft.id}
              className="text-[10px] font-medium text-amber-400 hover:text-amber-300 px-2 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/15 transition-all disabled:opacity-50"
            >
              {loading === draft.id ? <Loader2 className="w-3 h-3 animate-spin" /> : "Pause & Edit"}
            </button>
          </div>
        )}

        {/* Geo-Cultural Targeting */}
        {draft.draft_type === "paid" && (() => {
          const spec = parseTargetingSpec(draft.targeting_spec);
          const cardTgt2 = (draft.targeting || {}) as Record<string, unknown>;
          const country = (cardTgt2.target_country as string) || spec?.target_country || draft.target_country;
          const cardCities2 = (cardTgt2.target_cities as string[]) || [];
          const interests = spec?.validated_interests;
          if (!country && !interests?.length) return null;
          return (
            <div className="flex items-start gap-2 bg-blue-500/[0.04] border border-blue-500/10 rounded-lg px-3 py-2 mb-4">
              <Target className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-blue-400 mb-1">
                  Targeting: {country ? COUNTRY_NAMES[country] || country : ""}{cardCities2.length > 0 && ` — ${cardCities2.join(", ")}`}
                </p>
                {interests && interests.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {interests.slice(0, 4).map((interest: { id: string; name: string }) => (
                      <span key={interest.id} className="px-1.5 py-0.5 rounded bg-blue-500/10 text-[10px] text-blue-300 border border-blue-500/15">
                        {interest.name}
                      </span>
                    ))}
                    {interests.length > 4 && (
                      <span className="text-[10px] text-gray-500">+{interests.length - 4} more</span>
                    )}
                  </div>
                )}
                {spec?.advantage_plus_expanded && (
                  <span className="inline-flex items-center gap-1 mt-1 px-2 py-0.5 rounded-md text-[10px] font-medium bg-gradient-to-r from-purple-500/15 to-blue-500/15 text-purple-300 border border-purple-500/20">
                    <span className="text-xs">✨</span> Advantage+ Expansion
                  </span>
                )}
              </div>
            </div>
          );
        })()}

        {/* SAC reconciliation — what Meta actually accepted vs what we sent.
            Populated ~30s after publish by sac_reconciler. Only meaningful for
            SAC drafts; non-SAC drafts have targeting_diff=null and skip this. */}
        {draft.draft_type === "paid" && draft.targeting_diff && draft.targeting_diff.sent_count > 0 && (() => {
          const diff = draft.targeting_diff!;
          const RECON_STYLES: Record<string, { wrap: string; icon: string; label: string; chip: string; title: string }> = {
            clean: {
              wrap: "bg-emerald-500/[0.04] border border-emerald-500/15", icon: "text-emerald-400",
              label: "text-emerald-400", chip: "bg-emerald-500/10 text-emerald-200 border border-emerald-500/20",
              title: "All targeting accepted by Meta",
            },
            partial: {
              wrap: "bg-amber-500/[0.04] border border-amber-500/15", icon: "text-amber-400",
              label: "text-amber-400", chip: "bg-amber-500/10 text-amber-200 border border-amber-500/20",
              title: "Meta stripped some interests",
            },
            heavy: {
              wrap: "bg-orange-500/[0.04] border border-orange-500/15", icon: "text-orange-400",
              label: "text-orange-400", chip: "bg-orange-500/10 text-orange-200 border border-orange-500/20",
              title: "Meta stripped most interests",
            },
            total_strip: {
              wrap: "bg-red-500/[0.04] border border-red-500/15", icon: "text-red-400",
              label: "text-red-400", chip: "bg-red-500/10 text-red-200 border border-red-500/20",
              title: "Meta stripped ALL interests — running broad",
            },
            no_interests_sent: {
              wrap: "bg-gray-500/[0.04] border border-gray-500/15", icon: "text-gray-400",
              label: "text-gray-400", chip: "bg-gray-500/10 text-gray-200 border border-gray-500/20",
              title: "No interests sent",
            },
          };
          const tone = RECON_STYLES[diff.severity] || RECON_STYLES.partial;
          return (
            <div className={`flex items-start gap-2 ${tone.wrap} rounded-lg px-3 py-2 mb-4`}>
              <Target className={`w-3.5 h-3.5 ${tone.icon} mt-0.5 shrink-0`} />
              <div className="min-w-0 flex-1">
                <p className={`text-[10px] font-semibold uppercase tracking-wider ${tone.label} mb-1`}>
                  Meta reconciliation: {tone.title} ({diff.kept_count}/{diff.sent_count} kept)
                </p>
                {diff.stripped_interests.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1">
                    {diff.stripped_interests.slice(0, 6).map((it) => (
                      <span key={it.id} className={`px-1.5 py-0.5 rounded text-[10px] ${tone.chip} line-through opacity-80`}>
                        {it.name}
                      </span>
                    ))}
                    {diff.stripped_interests.length > 6 && (
                      <span className="text-[10px] text-gray-500">+{diff.stripped_interests.length - 6} more stripped</span>
                    )}
                  </div>
                )}
                {diff.stripped_count > 0 && (
                  <p className="text-[10px] text-gray-400 leading-tight">
                    The system has learned these — future {draft.special_ad_category ? SAC_DISPLAY[draft.special_ad_category]?.label || draft.special_ad_category : "SAC"} drafts will skip them automatically.
                  </p>
                )}
                {diff.advantage_audience_active && (
                  <span className="inline-flex items-center gap-1 mt-1 px-2 py-0.5 rounded-md text-[10px] font-medium bg-gradient-to-r from-purple-500/15 to-blue-500/15 text-purple-300 border border-purple-500/20">
                    <span className="text-xs">✨</span> Advantage+ Audience active
                  </span>
                )}
              </div>
            </div>
          );
        })()}

        {/* Phase B — auto-recovery status. Renders only when sac_recovery
            has touched the draft (status set). Shows pending state, the
            replacement interests on success, or a manual-intervention hint
            on failure. */}
        {draft.draft_type === "paid" && draft.auto_recovery_status && (() => {
          const status = draft.auto_recovery_status!;
          const attempts = draft.auto_recovery_attempts ?? 0;
          const RECOVERY_STYLES: Record<string, { wrap: string; icon: string; label: string; title: string; hint: string }> = {
            pending: {
              wrap: "bg-blue-500/[0.04] border border-blue-500/15", icon: "text-blue-400",
              label: "text-blue-400", title: `Auto-recovering targeting (attempt ${attempts})…`,
              hint: "Generating SAC-safe replacement interests and swapping them on Meta.",
            },
            recovered: {
              wrap: "bg-emerald-500/[0.04] border border-emerald-500/15", icon: "text-emerald-400",
              label: "text-emerald-400", title: `Auto-recovered (attempt ${attempts})`,
              hint: "Stripped interests have been replaced with SAC-safe alternatives on the live ad set.",
            },
            no_alternatives: {
              wrap: "bg-amber-500/[0.04] border border-amber-500/15", icon: "text-amber-400",
              label: "text-amber-400", title: "Auto-recovery: no valid replacements",
              hint: "The system couldn't find SAC-safe replacement interests. Ad set is running with whatever Meta accepted plus Advantage+ broad targeting.",
            },
            llm_failed: {
              wrap: "bg-red-500/[0.04] border border-red-500/15", icon: "text-red-400",
              label: "text-red-400", title: "Auto-recovery error (LLM)",
              hint: "Couldn't generate replacement interests — manual intervention may be needed.",
            },
            patch_failed: {
              wrap: "bg-red-500/[0.04] border border-red-500/15", icon: "text-red-400",
              label: "text-red-400", title: "Auto-recovery error (Meta API)",
              hint: "Replacement interests generated but Meta rejected the swap.",
            },
          };
          const tone = RECOVERY_STYLES[status] || RECOVERY_STYLES.pending;
          return (
            <div className={`flex items-start gap-2 ${tone.wrap} rounded-lg px-3 py-2 mb-4`}>
              <Target className={`w-3.5 h-3.5 ${tone.icon} mt-0.5 shrink-0`} />
              <div className="min-w-0 flex-1">
                <p className={`text-[10px] font-semibold uppercase tracking-wider ${tone.label} mb-1`}>
                  {tone.title}
                </p>
                {draft.recovered_interests && draft.recovered_interests.length > 0 && status === "recovered" && (
                  <div className="flex flex-wrap gap-1 mb-1">
                    {draft.recovered_interests.slice(0, 6).map((it) => (
                      <span key={it.id} className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-[10px] text-emerald-200 border border-emerald-500/20">
                        {it.name}
                      </span>
                    ))}
                  </div>
                )}
                <p className="text-[10px] text-gray-400 leading-tight">{tone.hint}</p>
              </div>
            </div>
          );
        })()}

        {/* Pixel / Tracking / Lead Form info on card */}
        {draft.draft_type === "paid" && (
          <div className="mb-4">
            {draft.destination_type === "INSTANT_FORM" ? (
              draft.lead_form_id ? (
                <div className="flex items-center gap-1.5 bg-cyan-500/[0.05] border border-cyan-500/10 rounded-lg px-3 py-2">
                  <ClipboardList className="w-3 h-3 text-cyan-400 shrink-0" />
                  <span className="text-[10px] text-cyan-400 font-medium truncate">Lead Form attached</span>
                </div>
              ) : isPending ? (
                <button
                  onClick={(e) => { e.stopPropagation(); setShowCardLeadFormModal(true); }}
                  className="w-full flex items-center justify-center gap-1.5 bg-cyan-500/[0.05] border border-dashed border-cyan-500/20 rounded-lg px-3 py-2 text-[11px] text-cyan-400 font-medium hover:bg-cyan-500/[0.1] transition-all"
                >
                  <ClipboardList className="w-3 h-3" />
                  Create or Connect Lead Form
                </button>
              ) : (
                <div className="flex items-center gap-1.5 bg-gray-500/[0.05] border border-gray-500/10 rounded-lg px-3 py-2">
                  <ClipboardList className="w-3 h-3 text-gray-500 shrink-0" />
                  <span className="text-[10px] text-gray-500">No lead form</span>
                </div>
              )
            ) : draft.destination_type === "MESSAGING" ? (
              <div className="flex items-center gap-1.5 bg-blue-500/[0.05] border border-blue-500/10 rounded-lg px-3 py-2">
                <MessagesSquare className="w-3 h-3 text-blue-400 shrink-0" />
                <span className="text-[10px] text-blue-400 font-medium truncate">
                  Messaging — {(draft.selected_messaging_apps || []).join(", ").replace(/INSTAGRAM_DM/g, "IG").replace(/WHATSAPP/g, "WA") || "Multi-app"}
                </span>
              </div>
            ) : draft.destination_type === "PHONE_CALL" ? (
              <div className="flex items-center gap-1.5 bg-orange-500/[0.05] border border-orange-500/10 rounded-lg px-3 py-2">
                <Phone className="w-3 h-3 text-orange-400 shrink-0" />
                <span className="text-[10px] text-orange-400 font-medium">Phone Calls{draft.call_phone_number ? ` — ${draft.call_phone_number}` : ""}</span>
              </div>
            ) : draft.destination_type === "INSTAGRAM_DM" ? (
              <div className="flex items-center gap-1.5 bg-pink-500/[0.05] border border-pink-500/10 rounded-lg px-3 py-2">
                <MessageCircle className="w-3 h-3 text-pink-400 shrink-0" />
                <span className="text-[10px] text-pink-400 font-medium">IG Direct — Conversations</span>
              </div>
            ) : draft.pixel_id ? (
              <div className="flex items-center gap-1.5 bg-amber-500/[0.05] border border-amber-500/10 rounded-lg px-3 py-2">
                <Zap className="w-3 h-3 text-amber-400 shrink-0" />
                <span className="text-[10px] text-amber-400 font-medium truncate">Pixel: {draft.pixel_id}</span>
                {draft.conversion_event && (
                  <span className="text-[10px] text-gray-500 ml-auto shrink-0">{draft.conversion_event.replace(/_/g, " ")}</span>
                )}
              </div>
            ) : isPending ? (
              <button
                onClick={(e) => { e.stopPropagation(); setShowCardPixelModal(true); }}
                className="w-full flex items-center justify-center gap-1.5 bg-amber-500/[0.05] border border-dashed border-amber-500/20 rounded-lg px-3 py-2 text-[11px] text-amber-400 font-medium hover:bg-amber-500/[0.1] transition-all"
              >
                <Zap className="w-3 h-3" />
                Attach Meta Pixel
              </button>
            ) : (
              <div className="flex items-center gap-1.5 bg-gray-500/[0.05] border border-gray-500/10 rounded-lg px-3 py-2">
                <Zap className="w-3 h-3 text-gray-500 shrink-0" />
                <span className="text-[10px] text-gray-500">No pixel — traffic mode</span>
              </div>
            )}
          </div>
        )}

        {/* Thumbnail prompt for video drafts */}
        {isPending && draft.image_url && isVideoUrl(draft.image_url) && (
          <div className="mb-4">
            {draft.thumbnail_url ? (
              <div className="flex items-center gap-2 bg-emerald-500/[0.04] border border-emerald-500/10 rounded-lg px-3 py-2">
                <img src={resolveImageUrl(draft.thumbnail_url)} alt="Thumbnail" className="w-8 h-8 rounded object-cover" />
                <span className="text-[10px] text-emerald-400 font-medium">Thumbnail attached</span>
                <label className="ml-auto text-[10px] text-gray-500 hover:text-gray-300 cursor-pointer transition-colors">
                  Change
                  <input type="file" accept="image/jpeg,image/png,image/webp" onChange={handleThumbnailUpload} className="hidden" />
                </label>
              </div>
            ) : (
              <label className="flex items-center justify-center gap-1.5 bg-orange-500/[0.05] border border-dashed border-orange-500/20 rounded-lg px-3 py-2.5 text-[11px] text-orange-400 font-medium hover:bg-orange-500/[0.1] transition-all cursor-pointer">
                {uploadingThumb ? <Loader2 className="w-3 h-3 animate-spin" /> : <ImageIcon className="w-3 h-3" />}
                Upload Video Thumbnail (required)
                <input type="file" accept="image/jpeg,image/png,image/webp" onChange={handleThumbnailUpload} className="hidden" />
              </label>
            )}
          </div>
        )}
      </div>

      {/* Actions — outside the clickable area */}
      {isPending && (
        <div className="flex items-center gap-2 px-5 pb-5">
          <button
            onClick={() => onApprove(draft.id)}
            disabled={loading === draft.id}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all glow-blue hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
          >
            {loading === draft.id ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4" />
                Approve & Schedule
              </>
            )}
          </button>
          <button
            onClick={() => onReject(draft.id)}
            disabled={loading === draft.id}
            className="flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium text-gray-400 hover:text-red-400 bg-white/[0.03] hover:bg-red-500/[0.06] border border-white/[0.06] hover:border-red-500/20 transition-all disabled:opacity-50"
          >
            <RefreshCw className="w-4 h-4" />
            Reject
          </button>
        </div>
      )}
    </div>

      {/* Modals — rendered outside the card to avoid overflow clipping */}
      {showCardPixelModal && (
        <PixelAttachModal
          currentPixelId={draft.pixel_id}
          currentEvent={draft.conversion_event}
          onClose={() => setShowCardPixelModal(false)}
          onAttach={(pixelId, _pixelName, event) => {
            onDraftUpdate(draft.id, { pixel_id: pixelId, conversion_event: event });
            setShowCardPixelModal(false);
          }}
        />
      )}

      {showCardLeadFormModal && (
        <LeadFormBuilder
          currentFormId={draft.lead_form_id}
          draftId={draft.id}
          onClose={() => setShowCardLeadFormModal(false)}
          onFormCreated={(formId, formName) => {
            onDraftUpdate(draft.id, { lead_form_id: formId });
            setShowCardLeadFormModal(false);
          }}
        />
      )}
    </>
  );
}

/* ── Page ──────────────────────────────────────────────────── */

export default function DraftsPage() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [filter, setFilter] = useState<FilterTab>("all");
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genStep, setGenStep] = useState("");
  const [abTest, setAbTest] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<Draft | null>(null);
  const [budgetCurrency, setBudgetCurrency] = useState("USD");
  const [showGenModal, setShowGenModal] = useState(false);
  const [userGuidance, setUserGuidance] = useState("");
  const [genDest, setGenDest] = useState<string>("WEBSITE");
  const [genWaNumber, setGenWaNumber] = useState("");
  const [genMsgApps, setGenMsgApps] = useState<string[]>(["MESSENGER"]);
  const [genCallPhone, setGenCallPhone] = useState("");
  const [selectedAbIds, setSelectedAbIds] = useState<Set<string>>(new Set());
  const [abLaunching, setAbLaunching] = useState(false);
  const [abError, setAbError] = useState<string | null>(null);

  useEffect(() => {
    api.getPreferences().then((res: { data?: { budget_currency?: string; whatsapp_number?: string } }) => {
      if (res?.data?.budget_currency) setBudgetCurrency(res.data.budget_currency);
      if (res?.data?.whatsapp_number) setGenWaNumber(res.data.whatsapp_number);
    }).catch(() => {});
  }, []);

  const fetchDrafts = useCallback(async () => {
    setLoading(true);
    try {
      const statusParam = filter === "all" ? undefined : filter;
      const { data } = await api.listDrafts(statusParam);
      setDrafts(data);
    } catch (err) {
      console.error("Failed to fetch drafts:", err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchDrafts();
  }, [fetchDrafts]);

  // Poll every 5s when any draft is in a transitional status (approved/publishing)
  const hasTransitional = drafts.some(
    (d) => d.status === "approved" || d.status === "publishing"
  );
  const hasTransitionalRef = useRef(hasTransitional);
  hasTransitionalRef.current = hasTransitional;

  useEffect(() => {
    if (!hasTransitional) return;

    const interval = setInterval(async () => {
      if (!hasTransitionalRef.current) return;
      try {
        const statusParam = filter === "all" ? undefined : filter;
        const { data } = await api.listDrafts(statusParam);
        setDrafts(data);
        // Also update the selected draft if it's open
        setSelectedDraft((prev: Draft | null) => {
          if (!prev) return prev;
          const updated = data.find((d: Draft) => d.id === prev.id);
          return updated || prev;
        });
      } catch {
        // silent — next poll will retry
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [hasTransitional, filter]);

  const handleApprove = async (id: string) => {
    setActionLoading(id);
    try {
      await api.approveDraft(id);
      setDrafts((prev) =>
        prev.map((d) => (d.id === id ? { ...d, status: "approved" as const } : d))
      );
    } catch (err) {
      console.error("Approve failed:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (id: string) => {
    setActionLoading(id);
    try {
      await api.rejectDraft(id);
      setDrafts((prev) =>
        prev.map((d) => (d.id === id ? { ...d, status: "rejected" as const } : d))
      );
    } catch (err) {
      console.error("Reject failed:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const handlePause = async (id: string) => {
    setActionLoading(id);
    try {
      await api.pauseDraft(id);
      setDrafts((prev) =>
        prev.map((d) => (d.id === id ? { ...d, status: "pending" as const } : d))
      );
      setSelectedDraft((prev) => prev && prev.id === id ? { ...prev, status: "pending" as const } : prev);
    } catch (err) {
      console.error("Pause failed:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const handleGenerate = async () => {
    setShowGenModal(false);
    setGenerating(true);
    setGenError(null);

    // Animated step indicators — competitor research adds ~5-10s
    setGenStep("Analyzing competitor ads...");
    const stepTimer1 = setTimeout(() => setGenStep("Identifying market gaps..."), 4000);
    const stepTimer2 = setTimeout(() => setGenStep("Crafting unique angles..."), 8000);
    const stepTimer3 = setTimeout(() => setGenStep("Writing ad copy..."), 12000);

    const guidance = userGuidance.trim() || undefined;

    try {
      const genWa = genDest === "WHATSAPP" ? genWaNumber : genDest === "MESSAGING" && genMsgApps.includes("WHATSAPP") ? genWaNumber : undefined;
      const genApps = genDest === "MESSAGING" ? genMsgApps : undefined;
      const genCall = genDest === "PHONE_CALL" ? genCallPhone : undefined;
      await api.generateDrafts(3, undefined, abTest, guidance, undefined, genDest, genWa, genApps, genCall);
      await fetchDrafts();
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.response?.data?.message || "Generation failed. Complete your Strategy Setup first.";
      setGenError(msg);
      setTimeout(() => setGenError(null), 8000);
    } finally {
      clearTimeout(stepTimer1);
      clearTimeout(stepTimer2);
      clearTimeout(stepTimer3);
      setGenerating(false);
      setGenStep("");
      setUserGuidance("");
    }
  };

  const handleDraftUpdate = async (draftId: string, fields: Record<string, unknown>) => {
    try {
      await api.updateDraft(draftId, fields as any);
      setDrafts((prev) =>
        prev.map((d) => (d.id === draftId ? { ...d, ...fields } : d))
      );
      setSelectedDraft((prev) => prev?.id === draftId ? { ...prev, ...fields } as Draft : prev);
    } catch (err) {
      console.error("Draft update failed:", err);
    }
  };

  const toggleAbSelect = (id: string) => {
    setSelectedAbIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setAbError(null);
  };

  const handleLaunchAbTest = async () => {
    const ids = Array.from(selectedAbIds);
    if (ids.length < 2) {
      setAbError("Select at least 2 drafts for an A/B test");
      return;
    }
    setAbLaunching(true);
    setAbError(null);
    try {
      await api.launchAbTest(ids);
      // Mark selected drafts as approved locally
      setDrafts((prev: Draft[]) =>
        prev.map((d: Draft) => selectedAbIds.has(d.id) ? { ...d, status: "approved" as const } : d)
      );
      setSelectedAbIds(new Set());
    } catch (err: any) {
      const msg = err?.response?.data?.detail || "A/B test launch failed";
      setAbError(msg);
    } finally {
      setAbLaunching(false);
    }
  };

  return (
    <div className="p-8 w-full animate-fade-in relative">
      {/* Detail modal */}
      {selectedDraft && (
        <DraftDetailModal
          draft={selectedDraft}
          onClose={() => setSelectedDraft(null)}
          onApprove={handleApprove}
          onReject={handleReject}
          onPause={handlePause}
          onDraftUpdate={handleDraftUpdate}
          loading={actionLoading}
          budgetCurrency={budgetCurrency}
        />
      )}

      {/* Generate modal */}
      {showGenModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setShowGenModal(false)} />
          <div className="relative w-full max-w-md bg-[#141418] border border-white/[0.08] rounded-2xl shadow-2xl p-6 animate-slide-up">
            <button onClick={() => setShowGenModal(false)} className="absolute top-4 right-4 text-gray-500 hover:text-white transition-colors">
              <X className="w-4 h-4" />
            </button>
            <h2 className="text-lg font-bold text-white mb-1 flex items-center gap-2">
              <Wand2 className="w-5 h-5 text-violet-400" />
              Generate New Ad Drafts
            </h2>
            <p className="text-sm text-gray-500 mb-5">The AI will create 3 draft ads based on your strategy and products.</p>

            <label className="block text-xs font-medium text-gray-400 mb-1.5">
              Have a specific angle in mind? <span className="text-gray-600">(Optional)</span>
            </label>
            <textarea
              value={userGuidance}
              onChange={(e: any) => setUserGuidance(e.target.value)}
              rows={3}
              placeholder="e.g., Make it a funny ad targeting college students studying for finals..."
              className="w-full rounded-xl bg-white/[0.04] border border-white/[0.08] text-sm text-white placeholder-gray-600 px-3 py-2.5 focus:outline-none focus:ring-1 focus:ring-violet-500/40 focus:border-violet-500/30 resize-none mb-4"
            />

            <label className="block text-xs font-medium text-gray-400 mb-1.5">Campaign Destination</label>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <button type="button" onClick={() => setGenDest("WEBSITE")}
                className={`px-3 py-2 rounded-xl text-xs font-medium border transition-all ${genDest === "WEBSITE" ? "bg-violet-500/10 border-violet-500/30 text-violet-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500"}`}>
                Website (Pixel)
              </button>
              <button type="button" onClick={() => setGenDest("INSTANT_FORM")}
                className={`px-3 py-2 rounded-xl text-xs font-medium border transition-all flex items-center justify-center gap-1 ${genDest === "INSTANT_FORM" ? "bg-cyan-500/10 border-cyan-500/30 text-cyan-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500"}`}>
                <ClipboardList className="w-3 h-3" /> Instant Form
              </button>
              <button type="button" onClick={() => { setGenDest("PHONE_CALL"); }}
                className={`px-3 py-2 rounded-xl text-xs font-medium border transition-all flex items-center justify-center gap-1 ${genDest === "PHONE_CALL" ? "bg-orange-500/10 border-orange-500/30 text-orange-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500"}`}>
                <Phone className="w-3 h-3" /> Phone Calls
              </button>
              <button type="button" onClick={() => { setGenDest("MESSAGING"); if (genMsgApps.length === 0) setGenMsgApps(["MESSENGER"]); }}
                className={`px-3 py-2 rounded-xl text-xs font-medium border transition-all flex items-center justify-center gap-1 ${genDest === "MESSAGING" ? "bg-blue-500/10 border-blue-500/30 text-blue-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500"}`}>
                <MessagesSquare className="w-3 h-3" /> Messaging
              </button>
            </div>

            {/* MESSAGING — multi-select */}
            {genDest === "MESSAGING" && (
              <div className="mb-4 space-y-2">
                <div className="px-3 py-2.5 rounded-xl bg-blue-500/[0.05] border border-blue-500/15">
                  <p className="text-[11px] text-blue-400 font-medium mb-2">Select Messaging Apps</p>
                  <div className="space-y-1.5">
                    {[
                      { key: "MESSENGER", label: "Facebook Messenger" },
                      { key: "INSTAGRAM_DM", label: "Instagram Direct" },
                      { key: "WHATSAPP", label: "WhatsApp" },
                    ].map((app) => (
                      <label key={app.key} className="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked={genMsgApps.includes(app.key)}
                          onChange={(e: any) => {
                            if (e.target.checked) setGenMsgApps([...genMsgApps, app.key]);
                            else setGenMsgApps(genMsgApps.filter((a: string) => a !== app.key));
                          }}
                          className="w-3.5 h-3.5 rounded border-white/20 bg-white/[0.04] text-blue-500 focus:ring-blue-500/20" />
                        <span className="text-xs text-gray-300">{app.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
                {genMsgApps.includes("WHATSAPP") && (
                  <input type="text" value={genWaNumber} onChange={(e: any) => setGenWaNumber(e.target.value)}
                    placeholder="WhatsApp number, e.g. 923001234567"
                    className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-emerald-500/40 transition-all" />
                )}
                <p className="text-[10px] text-gray-500">Meta routes conversations to all selected apps.</p>
              </div>
            )}

            {/* PHONE CALL */}
            {genDest === "PHONE_CALL" && (
              <div className="mb-4">
                <input type="text" value={genCallPhone} onChange={(e: any) => setGenCallPhone(e.target.value)}
                  placeholder="Phone number, e.g. +923001234567"
                  className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-orange-500/40 transition-all" />
                <p className="mt-1 text-[10px] text-gray-500">Users will see a &quot;Call Now&quot; button on the ad.</p>
              </div>
            )}

            {/* INSTANT FORM */}
            {genDest === "INSTANT_FORM" && (
              <div className="mb-4 px-3 py-2.5 rounded-xl bg-cyan-500/[0.05] border border-cyan-500/15">
                <p className="text-[10px] text-gray-500">Leads collected in-app via Meta forms. Create or attach a lead form to drafts after generation.</p>
              </div>
            )}

            <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer mb-5">
              <input
                type="checkbox"
                checked={abTest}
                onChange={(e: any) => setAbTest(e.target.checked)}
                className="rounded border-white/20 bg-white/[0.04] text-blue-500 focus:ring-blue-500/20 w-3.5 h-3.5"
              />
              Generate A/B test variants
            </label>

            <div className="flex items-center gap-3">
              <button
                onClick={handleGenerate}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all hover:scale-[1.02] active:scale-[0.98]"
              >
                <Sparkles className="w-4 h-4" />
                Generate with AI
              </button>
              <button
                onClick={() => setShowGenModal(false)}
                className="px-4 py-2.5 rounded-xl text-sm font-medium text-gray-400 hover:text-white bg-white/[0.04] border border-white/[0.08] hover:bg-white/[0.08] transition-all"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">
            Drafts & <span className="gradient-text">Approvals</span>
          </h1>
          <p className="text-sm text-gray-500">
            Review AI-generated content before it goes live.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => generating ? undefined : setShowGenModal(true)}
            disabled={generating}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all glow-blue hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
          >
            {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            {generating ? (genStep || "Generating...") : "Generate Drafts"}
          </button>
          <div className="flex items-center gap-1.5">
          <Filter className="w-4 h-4 text-gray-600 mr-1" />
          {FILTER_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setFilter(tab.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                filter === tab.value
                  ? "bg-white/[0.08] text-white border border-white/[0.1]"
                  : "text-gray-500 hover:text-gray-300 hover:bg-white/[0.03]"
              }`}
            >
              {tab.label}
            </button>
          ))}
          </div>
        </div>
      </div>

      {/* Generation error */}
      {genError && (
        <div className="mb-6 flex items-center gap-3 px-4 py-3 rounded-xl text-sm bg-red-500/[0.08] border border-red-500/20 text-red-400 animate-slide-up">
          <XCircle className="w-4 h-4 shrink-0" />
          <span className="flex-1">{genError}</span>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 text-gray-600 animate-spin" />
        </div>
      ) : drafts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-14 h-14 rounded-2xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-4">
            <Inbox className="w-7 h-7 text-gray-600" />
          </div>
          <h2 className="text-lg font-semibold text-gray-300 mb-1">No drafts yet</h2>
          <p className="text-sm text-gray-600 max-w-sm">
            The AI agent will generate content drafts based on your strategy preferences.
            Check back soon!
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {drafts.map((draft) => (
            <DraftCard
              key={draft.id}
              draft={draft}
              onApprove={handleApprove}
              onReject={handleReject}
              onPause={handlePause}
              onImageUpdate={(id, url) => handleDraftUpdate(id, { image_url: url })}
              onDraftUpdate={handleDraftUpdate}
              onOpen={setSelectedDraft}
              loading={actionLoading}
              budgetCurrency={budgetCurrency}
              selected={selectedAbIds.has(draft.id)}
              onToggleSelect={toggleAbSelect}
            />
          ))}
        </div>
      )}

      {/* ── Floating A/B Test Action Bar ───────────────────────────── */}
      {selectedAbIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-5 py-3 rounded-2xl bg-gray-900/95 backdrop-blur-xl border border-white/[0.1] shadow-2xl animate-slide-up">
          <div className="flex items-center gap-2 text-sm text-gray-300">
            <Target className="w-4 h-4 text-blue-400" />
            <span className="font-semibold text-white">{selectedAbIds.size}</span> drafts selected
          </div>
          <div className="w-px h-6 bg-white/10" />
          {abError && (
            <span className="text-xs text-red-400 max-w-[200px] truncate">{abError}</span>
          )}
          <button
            onClick={() => setSelectedAbIds(new Set())}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-white bg-white/[0.05] hover:bg-white/[0.1] transition-all"
          >
            Clear
          </button>
          <button
            onClick={handleLaunchAbTest}
            disabled={abLaunching || selectedAbIds.size < 2}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {abLaunching ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Zap className="w-4 h-4" />
            )}
            Launch A/B Test
          </button>
        </div>
      )}
    </div>
  );
}
