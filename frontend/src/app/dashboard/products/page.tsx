"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { api, resolveImageUrl } from "@/lib/api";
import {
  Package,
  Plus,
  Pencil,
  Trash2,
  Rocket,
  ImageIcon,
  Upload,
  Link2,
  Loader2,
  X,
  DollarSign,
  Tag,
  Users,
  Globe,
  Layers,
  ToggleLeft,
  ToggleRight,
  Zap,
  Copy,
  Check,
  Sparkles,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────────── */

type VariationOption = {
  label: string;
  price_value: string; // absolute if base_price group, modifier otherwise
};

type VariationGroup = {
  name: string;
  is_base_price: boolean;
  affects_price: boolean;
  options: VariationOption[];
};

type MatrixRow = {
  variant_name: string;
  price: number;
  currency: string;
};

type Product = {
  id: string;
  name: string;
  description: string | null;
  image_url: string | null;
  landing_url: string | null;
  price: number | null;
  currency: string;
  tags: string[];
  target_audience: string | null;
  is_active: boolean;
  created_at: string;
  product_type: string;
  product_options: VariationGroup[] | null;
  profit_margin: number | null;
  target_country: string | null;
  pixel_id: string | null;
  variants: { id?: string; variant_name: string; price: string | number; currency: string; sku: string }[];
};

type FormData = {
  name: string;
  description: string;
  image_url: string;
  landing_url: string;
  price: string;
  currency: string;
  tags: string;
  target_audience: string;
  product_type: string;
  profit_margin: string;
  target_country: string;
  pixel_id: string;
};

const EMPTY_FORM: FormData = {
  name: "",
  description: "",
  image_url: "",
  landing_url: "",
  price: "",
  currency: "USD",
  tags: "",
  target_audience: "",
  product_type: "physical",
  profit_margin: "",
  target_country: "",
  pixel_id: "",
};

const TARGET_COUNTRIES = [
  { value: "", label: "Use account default" },
  { value: "PK", label: "Pakistan" },
  { value: "US", label: "United States" },
  { value: "GB", label: "United Kingdom" },
  { value: "AE", label: "UAE" },
  { value: "SA", label: "Saudi Arabia" },
  { value: "IN", label: "India" },
  { value: "CA", label: "Canada" },
  { value: "AU", label: "Australia" },
  { value: "DE", label: "Germany" },
  { value: "FR", label: "France" },
  { value: "TR", label: "Turkey" },
  { value: "MY", label: "Malaysia" },
  { value: "NG", label: "Nigeria" },
  { value: "KE", label: "Kenya" },
  { value: "BD", label: "Bangladesh" },
];

const PRODUCT_TYPES = [
  { value: "physical", label: "Physical" },
  { value: "digital", label: "Digital" },
  { value: "saas", label: "SaaS" },
  { value: "service", label: "Service" },
];

const TYPE_BADGE_COLORS: Record<string, string> = {
  physical: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  digital: "bg-violet-500/20 text-violet-400 border-violet-500/30",
  saas: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  service: "bg-amber-500/20 text-amber-400 border-amber-500/30",
};

/* ── Matrix Generator ──────────────────────────────────────────────────────── */

function generateVariantMatrix(groups: VariationGroup[], currency: string): MatrixRow[] {
  const activeGroups = groups.filter(
    (g) => g.name.trim() && g.options.some((o) => o.label.trim())
  );
  if (activeGroups.length === 0) return [];

  // Build arrays of options per group (only non-empty labels)
  const perGroup = activeGroups.map((g) => ({
    group: g,
    options: g.options.filter((o) => o.label.trim()),
  }));

  // Cartesian product
  let combos: { group: VariationGroup; option: VariationOption }[][] = [[]];
  for (const { group, options } of perGroup) {
    const next: typeof combos = [];
    for (const combo of combos) {
      for (const option of options) {
        next.push([...combo, { group, option }]);
      }
    }
    combos = next;
  }

  return combos.map((combo) => {
    // Build name: "Size: 250g | Flavor: Chilli"
    const variant_name = combo
      .map((c) => `${c.group.name}: ${c.option.label}`)
      .join(" | ");

    // Calculate price: base + modifiers
    let price = 0;
    for (const c of combo) {
      const val = parseFloat(c.option.price_value) || 0;
      if (c.group.is_base_price) {
        price += val; // absolute
      } else if (c.group.affects_price) {
        price += val; // modifier/delta
      }
      // if !affects_price and !is_base_price, contributes 0
    }

    return { variant_name, price: Math.round(price * 100) / 100, currency };
  });
}

/* ── Toggle Component ──────────────────────────────────────────────────────── */

function Toggle({ on, onToggle, disabled }: { on: boolean; onToggle: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      className={`transition-all ${disabled ? "opacity-30 cursor-not-allowed" : "cursor-pointer"}`}
    >
      {on ? (
        <ToggleRight className="w-5 h-5 text-blue-400" />
      ) : (
        <ToggleLeft className="w-5 h-5 text-gray-600" />
      )}
    </button>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────────── */

export default function ProductsPage() {
  const router = useRouter();
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [imageTab, setImageTab] = useState<"url" | "upload">("url");
  const [generating, setGenerating] = useState<string | null>(null);
  const [genStep, setGenStep] = useState("");
  const [variationGroups, setVariationGroups] = useState<VariationGroup[]>([]);
  const [showMarginTooltip, setShowMarginTooltip] = useState(false);

  // Generate campaign modal state
  const [showGenModal, setShowGenModal] = useState(false);
  const [genProductId, setGenProductId] = useState<string | null>(null);
  const [userGuidance, setUserGuidance] = useState("");
  const [abTest, setAbTest] = useState(false);
  const [conversionEvent, setConversionEvent] = useState("");
  const [pixelEvents, setPixelEvents] = useState<{ event: string; count_7d: number }[]>([]);
  const [pixelEventsLoading, setPixelEventsLoading] = useState(false);

  // Pixel tracking state
  const [availablePixels, setAvailablePixels] = useState<{id: string; name: string}[]>([]);
  const [pixelsLoading, setPixelsLoading] = useState(false);
  const [creatingPixel, setCreatingPixel] = useState(false);
  const [newPixelName, setNewPixelName] = useState("");
  const [pixelBaseCode, setPixelBaseCode] = useState<string | null>(null);
  const [codeCopied, setCodeCopied] = useState(false);

  const matrix = useMemo(
    () => generateVariantMatrix(variationGroups, form.currency),
    [variationGroups, form.currency]
  );

  const hasVariations = variationGroups.length > 0;

  const fetchProducts = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.listProducts();
      setProducts(data);
    } catch {
      /* empty */
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPixels = useCallback(async () => {
    setPixelsLoading(true);
    try {
      const { data } = await api.listPixels();
      setAvailablePixels(data.pixels || []);
    } catch { /* empty */ }
    finally { setPixelsLoading(false); }
  }, []);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  /* ── Form open/close ──────────────────────────────────────────────────── */

  const openNew = () => {
    setForm(EMPTY_FORM);
    setEditingId(null);
    setVariationGroups([]);
    setShowForm(true);
    setImageTab("url");
    setPixelBaseCode(null);
    setNewPixelName("");
  };

  const openEdit = (p: Product) => {
    setForm({
      name: p.name,
      description: p.description || "",
      image_url: p.image_url || "",
      landing_url: p.landing_url || "",
      price: p.price?.toString() || "",
      currency: p.currency,
      tags: (p.tags || []).join(", "),
      target_audience: p.target_audience || "",
      product_type: p.product_type || "physical",
      profit_margin: p.profit_margin?.toString() || "",
      target_country: p.target_country || "",
      pixel_id: p.pixel_id || "",
    });
    // Restore variation groups from product_options if present
    if (p.product_options && Array.isArray(p.product_options) && p.product_options.length > 0) {
      setVariationGroups(
        p.product_options.map((g) => ({
          name: g.name || "",
          is_base_price: !!g.is_base_price,
          affects_price: !!g.affects_price,
          options: (g.options || []).map((o) => ({
            label: o.label || "",
            price_value: o.price_value?.toString() || "",
          })),
        }))
      );
    } else {
      setVariationGroups([]);
    }
    setEditingId(p.id);
    setShowForm(true);
    setImageTab("url");
    setPixelBaseCode(null);
  };

  /* ── Variation Group helpers ──────────────────────────────────────────── */

  const addGroup = () => {
    setVariationGroups((prev) => [
      ...prev,
      {
        name: "",
        is_base_price: prev.length === 0, // first group defaults to base price
        affects_price: prev.length > 0,
        options: [{ label: "", price_value: "" }],
      },
    ]);
  };

  const updateGroup = (gi: number, field: keyof VariationGroup, value: unknown) => {
    setVariationGroups((prev) =>
      prev.map((g, i) => {
        if (i !== gi) {
          // If toggling is_base_price ON for gi, turn it OFF for others
          if (field === "is_base_price" && value === true) {
            return { ...g, is_base_price: false };
          }
          return g;
        }
        return { ...g, [field]: value };
      })
    );
  };

  const removeGroup = (gi: number) => {
    setVariationGroups((prev) => prev.filter((_, i) => i !== gi));
  };

  const addOption = (gi: number) => {
    setVariationGroups((prev) =>
      prev.map((g, i) =>
        i === gi ? { ...g, options: [...g.options, { label: "", price_value: "" }] } : g
      )
    );
  };

  const updateOption = (gi: number, oi: number, field: keyof VariationOption, value: string) => {
    setVariationGroups((prev) =>
      prev.map((g, i) =>
        i === gi
          ? {
              ...g,
              options: g.options.map((o, j) => (j === oi ? { ...o, [field]: value } : o)),
            }
          : g
      )
    );
  };

  const removeOption = (gi: number, oi: number) => {
    setVariationGroups((prev) =>
      prev.map((g, i) =>
        i === gi ? { ...g, options: g.options.filter((_, j) => j !== oi) } : g
      )
    );
  };

  /* ── Save ─────────────────────────────────────────────────────────────── */

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        image_url: form.image_url || null,
        landing_url: form.landing_url || null,
        price: !hasVariations && form.price ? parseFloat(form.price) : null,
        currency: form.currency,
        tags: form.tags
          ? form.tags.split(",").map((t) => t.trim()).filter(Boolean)
          : [],
        target_audience: form.target_audience || null,
        product_type: form.product_type,
        product_options: hasVariations ? variationGroups : null,
        profit_margin: form.profit_margin ? parseFloat(form.profit_margin) : null,
        target_country: form.target_country || null,
        pixel_id: form.pixel_id || null,
      };

      let productId = editingId;
      if (editingId) {
        await api.updateProduct(editingId, { ...payload, is_active: true });
      } else {
        const { data } = await api.createProduct(payload);
        productId = data.id;
      }

      // Sync variants from matrix
      if (productId) {
        // Delete all existing variants first (full replace for matrix)
        try {
          const { data: existingVariants } = await api.listVariants(productId);
          for (const v of existingVariants || []) {
            if (v.id) await api.deleteVariant(productId, v.id);
          }
        } catch {
          /* no existing variants */
        }

        // Create new variants from generated matrix
        for (let i = 0; i < matrix.length; i++) {
          const row = matrix[i];
          await api.createVariant(productId, {
            variant_name: row.variant_name,
            price: row.price,
            currency: row.currency,
            sort_order: i,
          });
        }
      }

      setShowForm(false);
      await fetchProducts();
    } catch (err) {
      console.error("Save failed:", err);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteProduct(id);
      setProducts((prev) => prev.filter((p) => p.id !== id));
    } catch {
      /* empty */
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const { data } = await api.uploadProductImage(file);
      setForm((f) => ({ ...f, image_url: data.url }));
    } catch (err) {
      console.error("Upload failed:", err);
    } finally {
      setUploading(false);
    }
  };

  const STANDARD_EVENTS = [
    { event: "PURCHASE", count_7d: 0 },
    { event: "LEAD", count_7d: 0 },
    { event: "COMPLETE_REGISTRATION", count_7d: 0 },
  ];

  const openGenModal = (productId: string) => {
    setGenProductId(productId);
    setUserGuidance("");
    setAbTest(false);
    setConversionEvent("");
    setPixelEvents([]);
    setShowGenModal(true);

    // Fetch pixel events if product has a pixel
    const product = products.find((p) => p.id === productId);
    if (product?.pixel_id) {
      setPixelEventsLoading(true);
      api.getPixelEvents(product.pixel_id)
        .then((res) => {
          const events = (res as { data: { events: { event: string; count_7d: number }[] } }).data?.events
            ?? (res as { events: { event: string; count_7d: number }[] }).events
            ?? [];
          setPixelEvents(events.length > 0 ? events : STANDARD_EVENTS);
          // Auto-select first event
          if (events.length > 0) setConversionEvent(events[0].event);
        })
        .catch(() => setPixelEvents(STANDARD_EVENTS))
        .finally(() => setPixelEventsLoading(false));
    }
  };

  const handleGenerate = async () => {
    if (!genProductId) return;
    setShowGenModal(false);
    setGenerating(genProductId);
    setGenStep("Analyzing competitor ads...");
    const t1 = setTimeout(() => setGenStep("Identifying market gaps..."), 4000);
    const t2 = setTimeout(() => setGenStep("Crafting unique angles..."), 8000);
    const t3 = setTimeout(() => setGenStep("Writing ad copy..."), 12000);
    try {
      const guidance = userGuidance.trim() || undefined;
      await api.generateDrafts(3, genProductId, abTest, guidance, conversionEvent || undefined);
      router.push("/dashboard/drafts");
    } catch (err) {
      console.error("Generation failed:", err);
    } finally {
      clearTimeout(t1); clearTimeout(t2); clearTimeout(t3);
      setGenerating(null);
      setGenStep("");
    }
  };

  const getPriceDisplay = (p: Product) => {
    if (p.variants && p.variants.length > 0) {
      const prices = p.variants
        .map((v) => parseFloat(v.price?.toString() || "0"))
        .filter((n) => !isNaN(n) && n > 0);
      if (prices.length > 0) {
        const min = Math.min(...prices);
        const max = Math.max(...prices);
        if (min === max) return `$${min} ${p.currency}`;
        return `$${min} – $${max} ${p.currency}`;
      }
    }
    if (p.price) return `$${p.price} ${p.currency}`;
    return null;
  };

  /* ── Input class shorthand ────────────────────────────────────────────── */
  const inputCls =
    "w-full px-4 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/40 transition-all text-sm";
  const inputSmCls =
    "px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/40 transition-all text-xs";

  return (
    <div className="p-8 w-full animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">
            Product <span className="gradient-text">Catalog</span>
          </h1>
          <p className="text-sm text-gray-500">
            Manage products and generate product-specific ad campaigns.
          </p>
        </div>
        <button
          onClick={openNew}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all glow-blue hover:scale-[1.02] active:scale-[0.98]"
        >
          <Plus className="w-4 h-4" />
          Add Product
        </button>
      </div>

      {/* ── Form Modal ─────────────────────────────────────────────────── */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="glass rounded-2xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-5 border-b border-white/[0.06]">
              <h2 className="text-lg font-semibold text-white">
                {editingId ? "Edit Product" : "New Product"}
              </h2>
              <button onClick={() => setShowForm(false)} className="text-gray-500 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              {/* Name */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-1.5">
                  <Package className="w-3.5 h-3.5 text-blue-400" /> Name{" "}
                  <span className="text-red-400">*</span>
                </label>
                <input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. Vitamin C Serum"
                  className={inputCls}
                />
              </div>

              {/* Product Type */}
              <div>
                <label className="text-sm font-medium text-gray-300 mb-2 block">Product Type</label>
                <div className="flex gap-2">
                  {PRODUCT_TYPES.map((t) => (
                    <button
                      key={t.value}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, product_type: t.value }))}
                      className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                        form.product_type === t.value
                          ? "bg-blue-500/20 text-blue-400 border-blue-500/30"
                          : "bg-white/[0.04] text-gray-500 border-white/[0.08] hover:text-gray-300"
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Description / USPs */}
              <div>
                <label className="text-sm font-medium text-gray-300 mb-1.5 block">
                  Description / USPs
                </label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="Key features, benefits, unique selling points..."
                  rows={3}
                  className={`${inputCls} resize-none`}
                />
              </div>

              {/* Target Audience */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-1.5">
                  <Users className="w-3.5 h-3.5 text-emerald-400" /> Target Audience
                </label>
                <input
                  value={form.target_audience}
                  onChange={(e) => setForm((f) => ({ ...f, target_audience: e.target.value }))}
                  placeholder="e.g. Women 25-45 interested in skincare"
                  className={inputCls}
                />
              </div>

              {/* Target Country */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-1.5">
                  <Globe className="w-3.5 h-3.5 text-blue-400" /> Target Country
                </label>
                <select
                  value={form.target_country}
                  onChange={(e) => setForm((f) => ({ ...f, target_country: e.target.value }))}
                  className={inputCls}
                >
                  {TARGET_COUNTRIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-[11px] text-gray-600">
                  AI will generate culturally relevant ad targeting for this market.
                </p>
              </div>

              {/* Price + Currency — hidden when variation groups exist */}
              {!hasVariations && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-1.5">
                      <DollarSign className="w-3.5 h-3.5 text-amber-400" /> Price
                    </label>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={form.price}
                      onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))}
                      placeholder="29.99"
                      className={inputCls}
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium text-gray-300 mb-1.5 block">Currency</label>
                    <select
                      value={form.currency}
                      onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}
                      className={inputCls}
                    >
                      <option value="USD">USD</option>
                      <option value="EUR">EUR</option>
                      <option value="GBP">GBP</option>
                      <option value="CAD">CAD</option>
                      <option value="AUD">AUD</option>
                    <option value="PKR">PKR</option>
                    </select>
                  </div>
                </div>
              )}

              {/* Currency selector when variations exist (still need to pick currency) */}
              {hasVariations && (
                <div className="w-40">
                  <label className="text-sm font-medium text-gray-300 mb-1.5 block">Currency</label>
                  <select
                    value={form.currency}
                    onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}
                    className={inputCls}
                  >
                    <option value="USD">USD</option>
                    <option value="EUR">EUR</option>
                    <option value="GBP">GBP</option>
                    <option value="CAD">CAD</option>
                    <option value="AUD">AUD</option>
                    <option value="PKR">PKR</option>
                  </select>
                </div>
              )}

              {/* Profit Margin (optional) */}
              <div>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <label className="flex items-center gap-2 text-sm font-medium text-gray-300">
                    <DollarSign className="w-3.5 h-3.5 text-emerald-400" /> Expected Profit Margin per Sale ({form.currency})
                  </label>
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setShowMarginTooltip(!showMarginTooltip)}
                      className="w-4 h-4 rounded-full bg-white/[0.06] border border-white/[0.1] text-gray-500 hover:text-gray-300 text-[10px] font-bold flex items-center justify-center transition-colors"
                    >?</button>
                    {showMarginTooltip && (
                      <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-72 p-3 rounded-xl bg-[#1a1a2e] border border-white/[0.1] text-[11px] text-gray-300 leading-relaxed shadow-xl z-20">
                        Why we ask: By knowing your profit per sale, our AI can set a &apos;Cost Cap&apos; on Meta. This prevents the algorithm from spending your budget on expensive clicks that don&apos;t result in profitable sales. It acts as a safety net for your budget.
                      </div>
                    )}
                  </div>
                </div>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={form.profit_margin}
                  onChange={(e) => setForm((f) => ({ ...f, profit_margin: e.target.value }))}
                  placeholder="e.g. 400 — leave blank for Highest Volume (no cap)"
                  className={inputCls}
                />
                {parseFloat(form.profit_margin) > 0 && parseFloat(form.profit_margin) < 100 && (
                  <p className="mt-1.5 text-[11px] text-amber-400 bg-amber-500/[0.08] border border-amber-500/15 rounded-lg px-2.5 py-1.5">
                    Note: A very low profit goal might prevent your ads from showing if the market is competitive. Consider leaving it blank for the first 3 days to gather data.
                  </p>
                )}
                {parseFloat(form.profit_margin) >= 100 && (
                  <p className="mt-1.5 text-[11px] text-gray-500">
                    Cost Cap will be set to ~{Math.round(parseFloat(form.profit_margin) * 0.7)} {form.currency} (70% of margin)
                  </p>
                )}
              </div>

              {/* ── Variation Groups Builder ────────────────────────────────── */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-gray-300">
                    <Layers className="w-3.5 h-3.5 text-cyan-400" /> Variation Groups
                  </label>
                  <button
                    type="button"
                    onClick={addGroup}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium text-blue-400 bg-blue-500/10 border border-blue-500/20 hover:bg-blue-500/20 transition-all"
                  >
                    <Plus className="w-3 h-3" /> Add Group
                  </button>
                </div>

                {variationGroups.length === 0 && (
                  <p className="text-xs text-gray-600 mb-2">
                    Add variation groups (e.g. Size, Flavor) to auto-generate all product combinations.
                  </p>
                )}

                <div className="space-y-4">
                  {variationGroups.map((g, gi) => (
                    <div
                      key={gi}
                      className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-4 space-y-3"
                    >
                      {/* Group header */}
                      <div className="flex items-center gap-2">
                        <input
                          value={g.name}
                          onChange={(e) => updateGroup(gi, "name", e.target.value)}
                          placeholder="Group name (e.g. Size, Flavor)"
                          className={`flex-1 ${inputSmCls}`}
                        />
                        <button
                          type="button"
                          onClick={() => removeGroup(gi)}
                          className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-all"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>

                      {/* Toggles */}
                      <div className="flex items-center gap-5 text-xs">
                        <label className="flex items-center gap-1.5 text-gray-400">
                          <Toggle
                            on={g.is_base_price}
                            onToggle={() => {
                              const turningOn = !g.is_base_price;
                              setVariationGroups((prev) =>
                                prev.map((gr, i) => {
                                  if (i === gi) {
                                    return {
                                      ...gr,
                                      is_base_price: turningOn,
                                      affects_price: turningOn ? false : gr.affects_price,
                                    };
                                  }
                                  // Only one group can be base price
                                  return turningOn ? { ...gr, is_base_price: false } : gr;
                                })
                              );
                            }}
                          />
                          Base Price
                        </label>
                        <label className="flex items-center gap-1.5 text-gray-400">
                          <Toggle
                            on={g.affects_price}
                            disabled={g.is_base_price}
                            onToggle={() => updateGroup(gi, "affects_price", !g.affects_price)}
                          />
                          Price Modifier
                        </label>
                      </div>

                      {/* Options */}
                      <div className="space-y-2">
                        {g.options.map((o, oi) => (
                          <div key={oi} className="flex items-center gap-2">
                            <input
                              value={o.label}
                              onChange={(e) => updateOption(gi, oi, "label", e.target.value)}
                              placeholder="Option label (e.g. 250g)"
                              className={`flex-1 ${inputSmCls}`}
                            />
                            {(g.is_base_price || g.affects_price) && (
                              <div className="relative">
                                <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-gray-500">
                                  {g.is_base_price ? "$" : "+$"}
                                </span>
                                <input
                                  type="number"
                                  min="0"
                                  step="0.01"
                                  value={o.price_value}
                                  onChange={(e) =>
                                    updateOption(gi, oi, "price_value", e.target.value)
                                  }
                                  placeholder="0"
                                  className={`w-24 ${inputSmCls} ${g.is_base_price ? "pl-6" : "pl-7"}`}
                                />
                              </div>
                            )}
                            <button
                              type="button"
                              onClick={() => removeOption(gi, oi)}
                              className="p-1 rounded text-gray-600 hover:text-red-400 transition-all"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        ))}
                        <button
                          type="button"
                          onClick={() => addOption(gi)}
                          className="flex items-center gap-1 text-[11px] text-gray-500 hover:text-blue-400 transition-all"
                        >
                          <Plus className="w-3 h-3" /> Add option
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* ── Matrix Preview ──────────────────────────────────────────── */}
              {matrix.length > 0 && (
                <div>
                  <label className="text-sm font-medium text-gray-300 mb-2 block">
                    Generated Combinations ({matrix.length})
                  </label>
                  <div className="rounded-xl border border-white/[0.08] overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-white/[0.04]">
                          <th className="text-left px-3 py-2 text-gray-400 font-medium">#</th>
                          <th className="text-left px-3 py-2 text-gray-400 font-medium">Variant</th>
                          <th className="text-right px-3 py-2 text-gray-400 font-medium">Price</th>
                        </tr>
                      </thead>
                      <tbody>
                        {matrix.map((row, i) => (
                          <tr
                            key={i}
                            className="border-t border-white/[0.04] hover:bg-white/[0.02]"
                          >
                            <td className="px-3 py-2 text-gray-600">{i + 1}</td>
                            <td className="px-3 py-2 text-white">{row.variant_name}</td>
                            <td className="px-3 py-2 text-emerald-400 text-right font-medium">
                              ${row.price.toFixed(2)} {row.currency}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Landing URL */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-1.5">
                  <Globe className="w-3.5 h-3.5 text-violet-400" /> Landing URL
                </label>
                <input
                  type="url"
                  value={form.landing_url}
                  onChange={(e) => setForm((f) => ({ ...f, landing_url: e.target.value }))}
                  placeholder="https://yoursite.com/product"
                  className={inputCls}
                />
              </div>

              {/* Tracking & Conversions — only show when landing URL exists */}
              {form.landing_url.trim() && (
                <div className="rounded-xl bg-amber-500/[0.04] border border-amber-500/20 p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <Zap className="w-4 h-4 text-amber-400" />
                    <p className="text-sm font-semibold text-white">Tracking & Conversions</p>
                  </div>
                  <p className="text-xs text-gray-400">
                    Track leads and sales for this URL. Select an existing Meta Pixel or create a new one.
                  </p>

                  {/* Pixel dropdown */}
                  <div>
                    <div className="flex items-center gap-2 mb-1.5">
                      <select
                        value={form.pixel_id}
                        onChange={(e) => { setForm((f) => ({ ...f, pixel_id: e.target.value })); setPixelBaseCode(null); }}
                        onFocus={() => { if (availablePixels.length === 0 && !pixelsLoading) fetchPixels(); }}
                        className="flex-1 px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-all"
                      >
                        <option value="">No pixel (WhatsApp/COD mode)</option>
                        {pixelsLoading && <option disabled>Loading pixels...</option>}
                        {availablePixels.map((p) => (
                          <option key={p.id} value={p.id}>{p.name} ({p.id})</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Create new pixel */}
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      value={newPixelName}
                      onChange={(e) => setNewPixelName(e.target.value)}
                      placeholder={`${form.name || "Product"} Pixel`}
                      className="flex-1 px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 text-sm focus:outline-none focus:border-amber-500/40 transition-all"
                    />
                    <button
                      type="button"
                      onClick={async () => {
                        setCreatingPixel(true);
                        try {
                          const { data } = await api.createPixel(newPixelName || `${form.name} Pixel`);
                          const pid = data.pixel_id || data.id;
                          const pname = data.name || newPixelName;
                          setAvailablePixels((prev) => [...prev, { id: pid, name: pname }]);
                          setForm((f) => ({ ...f, pixel_id: pid }));
                          setPixelBaseCode(data.base_code || null);
                          setNewPixelName("");
                        } catch { /* error handled */ }
                        finally { setCreatingPixel(false); }
                      }}
                      disabled={creatingPixel}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-amber-600 hover:bg-amber-500 text-white transition-all disabled:opacity-50"
                    >
                      {creatingPixel ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                      {creatingPixel ? "Creating..." : "Create Pixel"}
                    </button>
                  </div>

                  {/* Base code snippet */}
                  {pixelBaseCode && (
                    <div className="rounded-lg bg-[#0d1117] border border-white/[0.08] overflow-hidden">
                      <div className="flex items-center justify-between px-3 py-2 border-b border-white/[0.06]">
                        <p className="text-[11px] font-medium text-emerald-400">Install this on your landing page</p>
                        <button
                          type="button"
                          onClick={() => {
                            navigator.clipboard.writeText(pixelBaseCode);
                            setCodeCopied(true);
                            setTimeout(() => setCodeCopied(false), 2000);
                          }}
                          className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-white/[0.06] text-gray-400 hover:text-white transition-all"
                        >
                          {codeCopied ? <Check className="w-2.5 h-2.5 text-emerald-400" /> : <Copy className="w-2.5 h-2.5" />}
                          {codeCopied ? "Copied!" : "Copy"}
                        </button>
                      </div>
                      <pre className="px-3 py-2 text-[10px] text-gray-500 leading-relaxed overflow-x-auto max-h-32 overflow-y-auto">
                        {pixelBaseCode}
                      </pre>
                    </div>
                  )}

                  {form.pixel_id && !pixelBaseCode && (
                    <p className="text-[11px] text-emerald-400/70">
                      Pixel {form.pixel_id} will track conversions for this product's URL.
                    </p>
                  )}
                </div>
              )}

              {/* Tags */}
              <div>
                <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-1.5">
                  <Tag className="w-3.5 h-3.5 text-rose-400" /> Tags
                </label>
                <input
                  value={form.tags}
                  onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
                  placeholder="skincare, organic, serum (comma separated)"
                  className={inputCls}
                />
              </div>

              {/* Image */}
              <div>
                <label className="text-sm font-medium text-gray-300 mb-2 block">Product Image</label>
                <div className="flex gap-2 mb-2">
                  <button
                    onClick={() => setImageTab("url")}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      imageTab === "url"
                        ? "bg-white/[0.08] text-white border border-white/[0.1]"
                        : "text-gray-500 hover:text-gray-300"
                    }`}
                  >
                    <Link2 className="w-3 h-3" /> Paste URL
                  </button>
                  <button
                    onClick={() => setImageTab("upload")}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      imageTab === "upload"
                        ? "bg-white/[0.08] text-white border border-white/[0.1]"
                        : "text-gray-500 hover:text-gray-300"
                    }`}
                  >
                    <Upload className="w-3 h-3" /> Upload File
                  </button>
                </div>
                {imageTab === "url" ? (
                  <input
                    type="url"
                    value={form.image_url}
                    onChange={(e) => setForm((f) => ({ ...f, image_url: e.target.value }))}
                    placeholder="https://example.com/image.jpg"
                    className={inputCls}
                  />
                ) : (
                  <label className="flex items-center justify-center gap-2 px-4 py-4 rounded-xl border border-dashed border-white/[0.1] bg-white/[0.02] cursor-pointer hover:bg-white/[0.04] transition-all text-sm text-gray-400">
                    {uploading ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Upload className="w-4 h-4" />
                    )}
                    {uploading ? "Uploading..." : "Choose file"}
                    <input
                      type="file"
                      accept="image/*,video/mp4,video/quicktime,video/webm"
                      onChange={handleUpload}
                      className="hidden"
                    />
                  </label>
                )}
                {form.image_url && (
                  <div className="mt-2 relative w-20 h-20 rounded-lg overflow-hidden border border-white/[0.06]">
                    <img
                      src={resolveImageUrl(form.image_url)}
                      alt="Preview"
                      className="w-full h-full object-cover"
                    />
                  </div>
                )}
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 p-5 border-t border-white/[0.06]">
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 rounded-xl text-sm text-gray-400 hover:text-white hover:bg-white/[0.04] transition-all"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={!form.name.trim() || saving}
                className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all disabled:opacity-50"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                {editingId ? "Update" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Product Grid ───────────────────────────────────────────────── */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 text-gray-600 animate-spin" />
        </div>
      ) : products.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-14 h-14 rounded-2xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-4">
            <Package className="w-7 h-7 text-gray-600" />
          </div>
          <h2 className="text-lg font-semibold text-gray-300 mb-1">No products yet</h2>
          <p className="text-sm text-gray-600 max-w-sm mb-6">
            Add your products to generate targeted ad campaigns with product-specific copy and
            images.
          </p>
          <button
            onClick={openNew}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all glow-blue"
          >
            <Plus className="w-4 h-4" />
            Add New Product
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {products.map((p) => (
            <div
              key={p.id}
              className="glass rounded-2xl overflow-hidden hover:bg-white/[0.04] transition-all duration-300 group"
            >
              {/* Image */}
              <div className="relative h-40 bg-gradient-to-br from-white/[0.03] to-white/[0.01] flex items-center justify-center border-b border-white/[0.06]">
                {p.image_url ? (
                  <img src={resolveImageUrl(p.image_url)} alt={p.name} className="w-full h-full object-cover" />
                ) : (
                  <div className="flex flex-col items-center gap-2 text-gray-600">
                    <ImageIcon className="w-8 h-8" />
                    <span className="text-xs">No image</span>
                  </div>
                )}
                <div className="absolute top-3 right-3 flex items-center gap-2">
                  {p.product_type && (
                    <span
                      className={`px-2 py-0.5 rounded-md text-[10px] font-semibold border backdrop-blur-sm ${
                        TYPE_BADGE_COLORS[p.product_type] || TYPE_BADGE_COLORS.physical
                      }`}
                    >
                      {PRODUCT_TYPES.find((t) => t.value === p.product_type)?.label ||
                        p.product_type}
                    </span>
                  )}
                  {getPriceDisplay(p) && (
                    <span className="bg-black/60 backdrop-blur-sm px-2 py-0.5 rounded-md text-xs font-semibold text-emerald-400">
                      {getPriceDisplay(p)}
                    </span>
                  )}
                </div>
              </div>

              {/* Info */}
              <div className="p-5">
                <h3 className="text-white font-semibold mb-1 line-clamp-1">{p.name}</h3>
                {p.description && (
                  <p className="text-sm text-gray-400 leading-relaxed line-clamp-2 mb-3">
                    {p.description}
                  </p>
                )}
                {p.target_audience && (
                  <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-3">
                    <Users className="w-3 h-3" />
                    <span className="line-clamp-1">{p.target_audience}</span>
                  </div>
                )}
                {p.target_country && (
                  <div className="flex items-center gap-1.5 text-xs text-blue-400/70 mb-3">
                    <Globe className="w-3 h-3" />
                    {TARGET_COUNTRIES.find((c) => c.value === p.target_country)?.label || p.target_country}
                  </div>
                )}
                {p.tags && p.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-4">
                    {p.tags.slice(0, 3).map((tag) => (
                      <span
                        key={tag}
                        className="px-2 py-0.5 rounded-md bg-white/[0.04] border border-white/[0.06] text-[10px] text-gray-500"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                {/* Variant count badge */}
                {p.variants && p.variants.length > 0 && (
                  <div className="flex items-center gap-1.5 text-xs text-cyan-400/70 mb-3">
                    <Layers className="w-3 h-3" />
                    {p.variants.length} variant{p.variants.length !== 1 ? "s" : ""}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => openGenModal(p.id)}
                    disabled={generating === p.id}
                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
                  >
                    {generating === p.id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Rocket className="w-3.5 h-3.5" />
                    )}
                    {generating === p.id ? (genStep || "Generating...") : "Generate Campaigns"}
                  </button>
                  <button
                    onClick={() => openEdit(p)}
                    className="p-2 rounded-xl text-gray-500 hover:text-white hover:bg-white/[0.06] transition-all"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleDelete(p.id)}
                    className="p-2 rounded-xl text-gray-500 hover:text-red-400 hover:bg-red-500/[0.06] transition-all"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Generate Campaign Modal ─────────────────────────────────── */}
      {showGenModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="glass rounded-2xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06]">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
                  <Sparkles className="w-4 h-4 text-violet-400" />
                </div>
                <p className="text-sm font-semibold text-white">Generate Campaigns</p>
              </div>
              <button
                onClick={() => setShowGenModal(false)}
                className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/[0.06] transition-all"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1.5 block">
                  Creative Direction (optional)
                </label>
                <textarea
                  value={userGuidance}
                  onChange={(e) => setUserGuidance(e.target.value)}
                  placeholder="e.g. Focus on health benefits, use urgency, target young professionals..."
                  rows={3}
                  className="w-full px-4 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 text-sm focus:outline-none focus:border-violet-500/40 transition-all resize-none"
                />
                <p className="text-[11px] text-gray-600 mt-1">
                  Guide the AI's creative direction. Leave empty for fully autonomous generation.
                </p>
              </div>

              <label className="flex items-center gap-2.5 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={abTest}
                  onChange={(e) => setAbTest(e.target.checked)}
                  className="w-4 h-4 rounded border-white/[0.15] bg-white/[0.04] text-violet-500 focus:ring-violet-500/30"
                />
                <span className="text-sm text-gray-400 group-hover:text-gray-300 transition-colors">
                  Generate A/B test variants
                </span>
              </label>

              {/* Conversion Event dropdown — only when product has pixel */}
              {(() => {
                const genProduct = products.find((p) => p.id === genProductId);
                if (!genProduct?.pixel_id) return null;
                return (
                  <div>
                    <label className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1.5 block">
                      Conversion Event
                    </label>
                    {pixelEventsLoading ? (
                      <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-gray-500 text-sm">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Loading pixel events...
                      </div>
                    ) : (
                      <select
                        value={conversionEvent}
                        onChange={(e) => setConversionEvent(e.target.value)}
                        className="w-full px-4 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all"
                      >
                        <option value="">Select conversion goal</option>
                        {pixelEvents.map((ev) => (
                          <option key={ev.event} value={ev.event}>
                            {ev.event.replace(/_/g, " ")}{ev.count_7d > 0 ? ` (${ev.count_7d} in 7d)` : ""}
                          </option>
                        ))}
                      </select>
                    )}
                    <p className="text-[11px] text-gray-600 mt-1">
                      Events actively tracked by your pixel. Used to optimize ad delivery.
                    </p>
                  </div>
                );
              })()}
            </div>

            <div className="px-6 py-4 border-t border-white/[0.06] flex items-center justify-end gap-2">
              <button
                onClick={() => setShowGenModal(false)}
                className="px-4 py-2 rounded-xl text-xs font-medium text-gray-400 hover:text-white hover:bg-white/[0.06] transition-all"
              >
                Cancel
              </button>
              <button
                onClick={handleGenerate}
                className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all"
              >
                <Rocket className="w-3.5 h-3.5" />
                Generate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
