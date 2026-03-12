"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api, resolveImageUrl } from "@/lib/api";
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
  suggested_keywords?: string[];
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
  created_at: string;
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
  { value: "PURCHASE", label: "Purchase", desc: "Optimize for completed sales" },
  { value: "LEAD", label: "Lead", desc: "Optimize for lead form submissions" },
  { value: "COMPLETE_REGISTRATION", label: "Complete Registration", desc: "Optimize for sign-ups" },
  { value: "ADD_TO_CART", label: "Add to Cart", desc: "Optimize for cart additions" },
  { value: "INITIATE_CHECKOUT", label: "Initiate Checkout", desc: "Optimize for checkout starts" },
  { value: "VIEW_CONTENT", label: "View Content", desc: "Optimize for page views" },
  { value: "CONTACT", label: "Contact", desc: "Optimize for contact actions" },
];

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
      const data = (res as unknown as { data: { pixel_id: string; pixel_name: string } }).data;
      if (data?.pixel_id) {
        setSelectedPixel(data.pixel_id);
        setPixels((prev) => [...prev, { id: data.pixel_id, name: data.pixel_name || newPixelName }]);
        setTab("select");
        setNewPixelName("");
      }
    } catch {
      setCreateError("Failed to create pixel. Check your Meta connection.");
    }
    setCreating(false);
  };

  const selectedPixelName = pixels.find((p) => p.id === selectedPixel)?.name || selectedPixel;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md bg-[#141418] border border-white/[0.08] rounded-2xl overflow-hidden animate-slide-up">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06]">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-semibold text-white">Attach Meta Pixel</h3>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-white/[0.06]">
          <button onClick={() => setTab("select")}
            className={`flex-1 px-4 py-2.5 text-xs font-medium transition-all ${tab === "select" ? "text-amber-400 border-b-2 border-amber-400 bg-amber-500/[0.05]" : "text-gray-500 hover:text-gray-300"}`}>
            Select Existing
          </button>
          <button onClick={() => setTab("create")}
            className={`flex-1 px-4 py-2.5 text-xs font-medium transition-all ${tab === "create" ? "text-amber-400 border-b-2 border-amber-400 bg-amber-500/[0.05]" : "text-gray-500 hover:text-gray-300"}`}>
            Create New
          </button>
        </div>

        <div className="px-5 py-5 space-y-4">
          {tab === "select" ? (
            <>
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
            </>
          ) : (
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

          {/* Event Selection — shown when a pixel is selected */}
          {selectedPixel && tab === "select" && (
            <div>
              <label className="text-xs text-gray-500 mb-1.5 block">Optimization Event</label>
              <p className="text-[10px] text-gray-600 mb-2">Select the action you want Meta to optimize this ad for.</p>
              <div className="space-y-1.5">
                {CONVERSION_EVENTS.map((ev) => (
                  <label key={ev.value}
                    className={`flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer transition-all border ${selectedEvent === ev.value ? "bg-amber-500/[0.08] border-amber-500/20" : "bg-white/[0.02] border-white/[0.06] hover:bg-white/[0.04]"}`}>
                    <input type="radio" name="conv_event" value={ev.value} checked={selectedEvent === ev.value}
                      onChange={(e) => setSelectedEvent(e.target.value)} className="hidden" />
                    <div className={`w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center ${selectedEvent === ev.value ? "border-amber-400" : "border-gray-600"}`}>
                      {selectedEvent === ev.value && <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />}
                    </div>
                    <div className="flex-1">
                      <span className="text-sm text-white">{ev.label}</span>
                      <p className="text-[10px] text-gray-500">{ev.desc}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-5 py-4 border-t border-white/[0.06]">
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
  onDraftUpdate,
  loading,
  budgetCurrency: initialCurrency,
}: {
  draft: Draft;
  onClose: () => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
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

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const isVideo = file.type.startsWith("video/");
    setUploading(true);
    setUploadError(null);
    try {
      const { data } = await api.uploadProductImage(file);
      onDraftUpdate(draft.id, { image_url: data.url });
    } catch { setUploadError("Failed to upload file."); }
    finally { setUploading(false); }
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

        {/* Image section */}
        <div className="relative w-full h-64 bg-black/30 border-b border-white/[0.06]">
          {draft.image_url ? (
            <>
              {isVideoUrl(draft.image_url) ? (
                <video src={resolveImageUrl(draft.image_url)} controls className="w-full h-full object-contain" />
              ) : (
                <img src={resolveImageUrl(draft.image_url)} alt={draft.headline ?? "Ad creative"} className="w-full h-full object-contain" />
              )}
              {isPending && (
                <div className="absolute bottom-3 right-3 flex gap-2">
                  <label className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium bg-black/60 backdrop-blur-sm text-white hover:bg-black/80 transition-all cursor-pointer border border-white/10">
                    <Upload className="w-3 h-3" /> Replace
                    <input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" onChange={handleFileUpload} className="hidden" />
                  </label>
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
                    Upload Media
                    <input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" onChange={handleFileUpload} className="hidden" />
                  </label>
                  <button onClick={() => alert("AI image generation coming soon!")}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium bg-gradient-to-r from-violet-600/80 to-blue-600/80 text-white transition-all">
                    <Wand2 className="w-3.5 h-3.5" /> Generate with AI
                  </button>
                </div>
              )}
              {uploadError && <p className="text-[11px] text-red-400">{uploadError}</p>}
              <div className="flex gap-2 w-64">
                <input type="text" value={imageUrlInput} onChange={(e) => setImageUrlInput(e.target.value)}
                  placeholder="Or paste image URL..." className="flex-1 px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-white text-xs placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" />
                <button onClick={() => { if (imageUrlInput.trim()) { onDraftUpdate(draft.id, { image_url: imageUrlInput.trim() }); setImageUrlInput(""); } }}
                  disabled={!imageUrlInput.trim()} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-600/80 text-white disabled:opacity-40 transition-all">
                  Save
                </button>
              </div>
            </div>
          )}
        </div>

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
              <div className="flex gap-2 pt-1">
                <button onClick={handleSaveEdits} disabled={saving}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500 text-white transition-all disabled:opacity-50">
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
                  Save Changes
                </button>
                <button onClick={() => { setEditing(false); setHeadline(draft.headline ?? ""); setBodyText(draft.body_text); setCtaType(draft.cta_type ?? "SHOP_NOW"); setBudget(String(draft.proposed_budget ?? "")); }}
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
                <div className="flex items-center gap-2 bg-emerald-500/[0.05] border border-emerald-500/10 rounded-xl px-4 py-3">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  <p className="text-sm text-emerald-300">Live on Meta — Ad ID: {draft.meta_ad_id}</p>
                </div>
              )}

              {/* Geo-Cultural Targeting Spec (Detail View) */}
              {draft.draft_type === "paid" && (() => {
                const spec = parseTargetingSpec(draft.targeting_spec);
                const country = spec?.target_country || draft.target_country;
                const interests = spec?.validated_interests;
                if (!country && !interests?.length) return null;
                return (
                  <div className="bg-blue-500/[0.04] border border-blue-500/10 rounded-xl px-4 py-4 space-y-2">
                    <div className="flex items-center gap-2">
                      <Target className="w-4 h-4 text-blue-400" />
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-blue-400">
                        Geo-Cultural Targeting: {country ? COUNTRY_NAMES[country] || country : ""}
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
                    {isPending && (
                      <button onClick={() => setShowPixelModal(true)}
                        className="text-[11px] text-amber-400 hover:text-amber-300 font-medium px-2.5 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 transition-all">
                        {draft.pixel_id ? "Change" : "Attach Pixel"}
                      </button>
                    )}
                  </div>
                  {draft.pixel_id ? (
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
    </div>
  );
}

/* ── Draft card ────────────────────────────────────────────── */

function DraftCard({
  draft,
  onApprove,
  onReject,
  onImageUpdate,
  onDraftUpdate,
  onOpen,
  loading,
  budgetCurrency,
}: {
  draft: Draft;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onImageUpdate: (id: string, imageUrl: string) => void;
  onDraftUpdate: (id: string, fields: Record<string, unknown>) => void;
  onOpen: (draft: Draft) => void;
  budgetCurrency: string;
  loading: string | null;
}) {
  const isPending = draft.status === "pending";
  const [showCreativeOptions, setShowCreativeOptions] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [showCardPixelModal, setShowCardPixelModal] = useState(false);
  const [uploadingThumb, setUploadingThumb] = useState(false);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const { data } = await api.uploadProductImage(file);
      onImageUpdate(draft.id, data.url);
      setShowCreativeOptions(false);
    } catch {
      setUploadError("Failed to read file.");
    } finally {
      setUploading(false);
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
      onImageUpdate(draft.id, imageUrl.trim());
      setImageUrl("");
      setShowCreativeOptions(false);
    }
  };

  return (
    <div className="glass rounded-2xl overflow-hidden hover:bg-white/[0.04] transition-all duration-300 group">
      {/* Image area */}
      <div
        className="relative h-40 bg-gradient-to-br from-white/[0.03] to-white/[0.01] flex items-center justify-center border-b border-white/[0.06] cursor-pointer"
        onClick={() => {
          if (!draft.image_url && isPending) {
            setShowCreativeOptions(!showCreativeOptions);
          } else {
            onOpen(draft);
          }
        }}
      >
        {draft.image_url ? (
          isVideoUrl(draft.image_url) ? (
            <video src={resolveImageUrl(draft.image_url)} muted loop autoPlay playsInline className="w-full h-full object-cover" />
          ) : (
            <img
              src={resolveImageUrl(draft.image_url)}
              alt={draft.headline ?? "Ad creative"}
              className="w-full h-full object-cover"
            />
          )
        ) : isPending ? (
          <div className="flex flex-col items-center gap-2 text-gray-500 hover:text-gray-300 transition-colors">
            <ImageIcon className="w-8 h-8" />
            <span className="text-xs font-medium">Add Creative</span>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 text-gray-600">
            <ImageIcon className="w-8 h-8" />
            <span className="text-xs">No creative</span>
          </div>
        )}
        {/* Badges overlay */}
        <div className="absolute top-3 left-3 flex items-center gap-1.5">
          <TypeBadge type={draft.draft_type} onToggle={draft.status === "pending" ? () => {
            const newType = draft.draft_type === "paid" ? "organic" : "paid";
            const updates: Record<string, unknown> = { draft_type: newType };
            if (newType === "paid" && !draft.proposed_budget) {
              updates.proposed_budget = 10;
            }
            onDraftUpdate(draft.id, updates);
          } : undefined} />
          <StatusBadge status={draft.status} />
        </div>
        {/* Expand icon */}
        <button
          onClick={(e) => { e.stopPropagation(); onOpen(draft); }}
          className="absolute top-3 right-3 p-1.5 rounded-lg bg-black/40 text-gray-400 hover:text-white opacity-0 group-hover:opacity-100 transition-all"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Creative options panel */}
      {isPending && showCreativeOptions && !draft.image_url && (
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
              Upload Media
              <input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm" onChange={handleFileUpload} className="hidden" />
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

        {/* Error */}
        {draft.status === "failed" && draft.error_message && (
          <div className="flex items-start gap-2 bg-red-500/[0.05] border border-red-500/10 rounded-lg px-3 py-2 mb-4">
            <XCircle className="w-3.5 h-3.5 text-red-400 mt-0.5 shrink-0" />
            <p className="text-xs text-red-300 line-clamp-1">{draft.error_message}</p>
          </div>
        )}

        {/* Active Meta ID */}
        {draft.status === "active" && draft.meta_ad_id && (
          <div className="flex items-center gap-2 bg-emerald-500/[0.05] border border-emerald-500/10 rounded-lg px-3 py-2 mb-4">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <p className="text-xs text-emerald-300">Live — {draft.meta_ad_id}</p>
          </div>
        )}

        {/* Geo-Cultural Targeting */}
        {draft.draft_type === "paid" && (() => {
          const spec = parseTargetingSpec(draft.targeting_spec);
          const country = spec?.target_country || draft.target_country;
          const interests = spec?.validated_interests;
          if (!country && !interests?.length) return null;
          return (
            <div className="flex items-start gap-2 bg-blue-500/[0.04] border border-blue-500/10 rounded-lg px-3 py-2 mb-4">
              <Target className="w-3.5 h-3.5 text-blue-400 mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-blue-400 mb-1">
                  Targeting: {country ? COUNTRY_NAMES[country] || country : ""}
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
              </div>
            </div>
          );
        })()}

        {/* Pixel / Tracking info on card */}
        {draft.draft_type === "paid" && (
          <div className="mb-4">
            {draft.pixel_id ? (
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

      {/* Pixel modal for card */}
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

  useEffect(() => {
    api.getPreferences().then((res: { data?: { budget_currency?: string } }) => {
      if (res?.data?.budget_currency) setBudgetCurrency(res.data.budget_currency);
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
      await api.generateDrafts(3, undefined, abTest, guidance);
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

  return (
    <div className="p-8 w-full animate-fade-in">
      {/* Detail modal */}
      {selectedDraft && (
        <DraftDetailModal
          draft={selectedDraft}
          onClose={() => setSelectedDraft(null)}
          onApprove={handleApprove}
          onReject={handleReject}
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
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {drafts.map((draft) => (
            <DraftCard
              key={draft.id}
              draft={draft}
              onApprove={handleApprove}
              onReject={handleReject}
              onImageUpdate={(id, url) => handleDraftUpdate(id, { image_url: url })}
              onDraftUpdate={handleDraftUpdate}
              onOpen={setSelectedDraft}
              loading={actionLoading}
              budgetCurrency={budgetCurrency}
            />
          ))}
        </div>
      )}
    </div>
  );
}
