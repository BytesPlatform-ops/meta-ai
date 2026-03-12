"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { Loader2, Send, CheckCircle2, Zap, Globe, ShoppingBag, Code2, Mail, Plus, Copy, Check } from "lucide-react";

type Pixel = { id: string; name: string };

export function SmartTrackingCard() {
  const [pixels, setPixels] = useState<Pixel[]>([]);
  const [selectedPixel, setSelectedPixel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [platform, setPlatform] = useState("custom");

  // Email developer state
  const [devEmail, setDevEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  // Create pixel state
  const [creating, setCreating] = useState(false);
  const [newPixelName, setNewPixelName] = useState("AI Pixel");
  const [baseCode, setBaseCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.listPixels()
      .then(({ data }) => setPixels(data.pixels || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleCreatePixel = async () => {
    setCreating(true);
    setSaveError(null);
    try {
      const { data } = await api.createPixel(newPixelName);
      const pixelId = data.pixel_id || data.id;
      const pixelName = data.name || newPixelName;
      // Add to list and auto-select
      setPixels((prev) => [...prev, { id: pixelId, name: pixelName }]);
      setSelectedPixel(pixelId);
      setBaseCode(data.base_code || null);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || "Failed to create pixel. Make sure your Meta account is connected.";
      setSaveError(msg);
      setTimeout(() => setSaveError(null), 5000);
    } finally {
      setCreating(false);
    }
  };

  const handleCopyCode = () => {
    if (!baseCode) return;
    navigator.clipboard.writeText(baseCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      await api.savePixel(selectedPixel);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: any) {
      const msg = err?.response?.data?.detail || "Failed to save. Make sure you have an ad account connected.";
      setSaveError(msg);
      setTimeout(() => setSaveError(null), 5000);
    } finally {
      setSaving(false);
    }
  };

  const handleEmailDev = async () => {
    if (!devEmail || !selectedPixel) return;
    setSending(true);
    setSent(false);
    try {
      await api.emailDeveloper({ developer_email: devEmail, pixel_id: selectedPixel, platform });
      setSent(true);
      setTimeout(() => setSent(false), 4000);
    } catch { /* handled by UI */ }
    finally { setSending(false); }
  };

  const platforms = [
    { id: "shopify", label: "Shopify", icon: ShoppingBag },
    { id: "woocommerce", label: "WooCommerce", icon: Globe },
    { id: "custom", label: "Custom Site", icon: Code2 },
  ];

  return (
    <div className="glass rounded-2xl overflow-hidden mb-8">
      <div className="px-6 py-5 border-b border-white/[0.06]">
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center shrink-0">
            <Zap className="w-5 h-5 text-amber-400" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white">Enable Smart AI Tracking</p>
            <p className="text-xs text-gray-500">
              Connect your Meta Pixel so our AI can track purchases and optimize your campaigns automatically.
            </p>
          </div>
        </div>
      </div>

      <div className="px-6 py-5 space-y-5">
        {/* Pixel selector */}
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading available pixels...
          </div>
        ) : (
          <div>
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2 block">
              Select your Pixel
            </label>
            <select
              value={selectedPixel ?? ""}
              onChange={(e) => { setSelectedPixel(e.target.value || null); setBaseCode(null); }}
              className="w-full px-4 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-amber-500/40 transition-all"
            >
              <option value="">No pixel (WhatsApp/COD mode)</option>
              {pixels.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.id})</option>
              ))}
            </select>

            {/* Create new pixel */}
            {pixels.length === 0 && (
              <div className="mt-3 rounded-xl bg-amber-500/[0.06] border border-amber-500/20 p-4">
                <p className="text-xs text-amber-300/80 mb-3">
                  No Pixels found on your account. Create one now, or skip to use WhatsApp/COD mode.
                </p>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={newPixelName}
                    onChange={(e) => setNewPixelName(e.target.value)}
                    placeholder="Pixel name"
                    className="flex-1 px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 text-sm focus:outline-none focus:border-amber-500/40 transition-all"
                  />
                  <button
                    onClick={handleCreatePixel}
                    disabled={creating || !newPixelName.trim()}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-amber-600 hover:bg-amber-500 text-white transition-all disabled:opacity-50"
                  >
                    {creating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                    {creating ? "Creating..." : "Create Pixel"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Base code snippet after pixel creation */}
        {baseCode && (
          <div className="rounded-xl bg-[#0d1117] border border-white/[0.08] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.06]">
              <p className="text-xs font-medium text-emerald-400">Pixel created! Install this code on your website</p>
              <button
                onClick={handleCopyCode}
                className="flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-medium bg-white/[0.06] text-gray-400 hover:text-white hover:bg-white/[0.1] transition-all"
              >
                {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                {copied ? "Copied!" : "Copy"}
              </button>
            </div>
            <pre className="px-4 py-3 text-[11px] text-gray-400 leading-relaxed overflow-x-auto max-h-48 overflow-y-auto">
              {baseCode}
            </pre>
            <div className="px-4 py-2.5 border-t border-white/[0.06] bg-white/[0.02]">
              <p className="text-[11px] text-gray-500">
                Paste this in the <code className="text-amber-400">&lt;head&gt;</code> tag of every page on your website. Also add the Purchase event on your order confirmation page.
              </p>
            </div>
          </div>
        )}

        {/* Platform selector */}
        {selectedPixel && (
          <>
            <div>
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2 block">
                Select your platform
              </label>
              <div className="grid grid-cols-3 gap-2">
                {platforms.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setPlatform(p.id)}
                    className={`flex items-center gap-2 px-3 py-2.5 rounded-xl text-xs font-medium transition-all border ${
                      platform === p.id
                        ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                        : "bg-white/[0.02] border-white/[0.06] text-gray-400 hover:border-white/[0.12]"
                    }`}
                  >
                    <p.icon className="w-3.5 h-3.5" />
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Email developer */}
            <div className="rounded-xl bg-white/[0.02] border border-white/[0.06] p-4">
              <div className="flex items-center gap-2 mb-3">
                <Mail className="w-3.5 h-3.5 text-gray-500" />
                <p className="text-xs font-medium text-gray-400">Send instructions to my developer</p>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="email"
                  value={devEmail}
                  onChange={(e) => setDevEmail(e.target.value)}
                  placeholder="developer@example.com"
                  className="flex-1 px-3 py-2 rounded-lg bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 text-sm focus:outline-none focus:border-amber-500/40 transition-all"
                />
                <button
                  onClick={handleEmailDev}
                  disabled={!devEmail || sending}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold bg-white/[0.06] border border-white/[0.08] text-gray-300 hover:bg-white/[0.1] transition-all disabled:opacity-40"
                >
                  {sending ? <Loader2 className="w-3 h-3 animate-spin" /> : sent ? <CheckCircle2 className="w-3 h-3 text-emerald-400" /> : <Send className="w-3 h-3" />}
                  {sent ? "Sent!" : "Send"}
                </button>
              </div>
            </div>
          </>
        )}

        {/* Save button */}
        <button
          onClick={handleSave}
          disabled={saving || loading}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-500 hover:to-orange-500 text-white transition-all disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : saved ? <CheckCircle2 className="w-3.5 h-3.5" /> : null}
          {saved ? "Saved!" : selectedPixel ? "Enable Pixel Tracking" : "Use WhatsApp/COD Mode"}
        </button>

        {saveError && (
          <p className="text-xs text-red-400 bg-red-500/[0.08] border border-red-500/20 rounded-lg px-3 py-2">{saveError}</p>
        )}

        {/* Helper text */}
        <p className="text-[11px] text-gray-600 leading-relaxed">
          {selectedPixel
            ? "Your AI campaigns will optimize for website purchases tracked by this Pixel."
            : "Without a Pixel, campaigns will optimize for WhatsApp conversations — ideal for Cash on Delivery businesses."}
        </p>
      </div>
    </div>
  );
}
