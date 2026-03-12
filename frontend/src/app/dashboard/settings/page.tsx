"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { ConnectMetaButton } from "@/components/ui/ConnectMetaButton";
import { AdAccountCard } from "@/components/ui/AdAccountCard";
import { SmartTrackingCard } from "@/components/ui/SmartTrackingCard";
import {
  CheckCircle2, AlertTriangle, X, Link2, Shield, Briefcase, Loader2,
  Store, FileText, Users, Globe, Calendar, CalendarDays, Sun, Hand, Phone,
  Smile, GraduationCap, Megaphone, PiggyBank, TrendingUp, Rocket,
  SlidersHorizontal, Settings2, ChevronDown, ChevronUp,
  Instagram, Facebook, RefreshCw, Monitor, Key,
} from "lucide-react";

export type AdAccount = {
  id: string;
  meta_account_id: string;
  account_name: string | null;
  currency: string;
  timezone: string;
  is_active: boolean;
  token_expires_at: string | null;
  created_at: string;
};

const FREQ_OPTIONS = [
  { value: "daily", label: "Daily", icon: Calendar },
  { value: "3x_weekly", label: "3x / Week", icon: CalendarDays },
  { value: "weekends_only", label: "Weekends", icon: Sun },
  { value: "manual_only", label: "Manual", icon: Hand },
];
const TONE_OPTIONS = [
  { value: "professional", label: "Professional", icon: Briefcase },
  { value: "humorous", label: "Humorous", icon: Smile },
  { value: "educational", label: "Educational", icon: GraduationCap },
  { value: "promotional", label: "Promotional", icon: Megaphone },
];
const BUDGET_OPTIONS = [
  { value: "conservative", label: "Conservative", amount: 10, icon: PiggyBank },
  { value: "moderate", label: "Moderate", amount: 30, icon: TrendingUp },
  { value: "aggressive", label: "Aggressive", amount: 50, icon: Rocket },
  { value: "custom", label: "Custom", amount: 0, icon: SlidersHorizontal },
];
const BUDGET_CURRENCIES = [
  { value: "USD", label: "USD ($)", symbol: "$" },
  { value: "PKR", label: "PKR (₨)", symbol: "₨" },
  { value: "EUR", label: "EUR (€)", symbol: "€" },
  { value: "GBP", label: "GBP (£)", symbol: "£" },
  { value: "AED", label: "AED", symbol: "AED" },
  { value: "INR", label: "INR (₹)", symbol: "₹" },
];

const PLACEMENT_OPTIONS = [
  { value: "BOTH", label: "Auto / Both", icon: Monitor, desc: "Recommended" },
  { value: "INSTAGRAM_ONLY", label: "Instagram Only", icon: Instagram, desc: "" },
  { value: "FACEBOOK_ONLY", label: "Facebook Only", icon: Facebook, desc: "" },
];

type SocialPage = {
  page_id: string;
  page_name: string;
  instagram_actor_id: string | null;
  instagram_username: string | null;
  instagram_profile_pic: string | null;
};

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const [accounts, setAccounts] = useState<AdAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Strategy preferences
  const [strategyOpen, setStrategyOpen] = useState(false);
  const [prefsLoading, setPrefsLoading] = useState(true);
  const [prefsSaving, setPrefsSaving] = useState(false);
  const [prefs, setPrefs] = useState({
    business_name: "",
    business_description: "",
    target_audience: "",
    website_url: "",
    industry_niche: "",
    posting_frequency: "manual_only",
    content_tone: "professional",
    ad_budget_level: "conservative",
    budget_currency: "USD",
    custom_budget: undefined as number | undefined,
    approval_required: true,
    whatsapp_number: "",
    ad_placements: "BOTH",
    target_country: "PK",
  });
  const [socialPages, setSocialPages] = useState<SocialPage[]>([]);
  const [socialLoading, setSocialLoading] = useState(false);
  const [websiteScrapedAt, setWebsiteScrapedAt] = useState<string | null>(null);
  const [websiteIntel, setWebsiteIntel] = useState<Record<string, unknown> | null>(null);
  const [scraping, setScraping] = useState(false);
  const [extraUrls, setExtraUrls] = useState("");

  // Manual connect state
  const [manualOpen, setManualOpen] = useState(false);
  const [manualToken, setManualToken] = useState("");
  const [manualAccountId, setManualAccountId] = useState("");
  const [manualLoading, setManualLoading] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);

  const handleManualConnect = async () => {
    if (!manualToken.trim() || !manualAccountId.trim()) return;
    setManualLoading(true);
    setManualError(null);
    try {
      const { data } = await api.manualConnect(manualToken.trim(), manualAccountId.trim());
      setBanner({ type: "success", text: data.message });
      setManualToken("");
      setManualAccountId("");
      setManualOpen(false);
      loadAccounts();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setManualError(detail ?? "Failed to connect. Check your token and account ID.");
    } finally {
      setManualLoading(false);
    }
  };

  useEffect(() => {
    const connected = searchParams.get("connected");
    const metaError = searchParams.get("meta_error");
    if (connected === "true") {
      setBanner({ type: "success", text: "Meta Ad Account connected successfully!" });
    } else if (metaError) {
      const messages: Record<string, string> = {
        missing_params: "OAuth redirect was missing required parameters.",
        token_exchange_failed: "Failed to exchange token with Meta. Please try again.",
        access_denied: "You denied access. Connect again when you're ready.",
      };
      setBanner({ type: "error", text: messages[metaError] ?? `Meta error: ${metaError}` });
    }
  }, [searchParams]);

  const loadAccounts = async () => {
    setLoading(true);
    try {
      const { data } = await api.listAdAccounts();
      setAccounts(data);
    } catch {
      /* no accounts yet */
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadAccounts(); }, []);

  // Auto-load social profiles when accounts are available
  useEffect(() => {
    if (accounts.length > 0) {
      setSocialLoading(true);
      api.fetchSocialIdentities()
        .then(({ data }) => setSocialPages(data.pages || []))
        .catch(() => setSocialPages([]))
        .finally(() => setSocialLoading(false));
    }
  }, [accounts]);

  // Load existing preferences
  useEffect(() => {
    api.getPreferences().then(({ data }) => {
      if (data) {
        setPrefs({
          business_name: data.business_name || "",
          business_description: data.business_description || "",
          target_audience: data.target_audience || "",
          website_url: data.website_url || "",
          industry_niche: data.industry_niche || "",
          posting_frequency: data.posting_frequency || "manual_only",
          content_tone: data.content_tone || "professional",
          ad_budget_level: data.ad_budget_level || "conservative",
          budget_currency: data.budget_currency || "USD",
          custom_budget: data.custom_budget ?? undefined,
          approval_required: data.approval_required ?? true,
          whatsapp_number: data.whatsapp_number || "",
          ad_placements: data.ad_placements || "BOTH",
          target_country: data.target_country || "PK",
        });
        if (data.website_scraped_at) setWebsiteScrapedAt(data.website_scraped_at);
        if (data.website_intel) setWebsiteIntel(data.website_intel);
      }
    }).catch(() => {}).finally(() => setPrefsLoading(false));
  }, []);

  const savePrefs = async () => {
    console.log("[SAVE] savePrefs called, prefs:", JSON.stringify(prefs));
    setPrefsSaving(true);
    try {
      const res = await api.upsertPreferences(prefs);
      console.log("[SAVE] success:", res);
      setBanner({ type: "success", text: "Strategy preferences saved!" });
    } catch (err) {
      console.error("[SAVE] error:", err);
      setBanner({ type: "error", text: "Failed to save preferences." });
    } finally {
      setPrefsSaving(false);
    }
  };

  const handleDisconnect = async (accountId: string) => {
    await api.disconnectAdAccount(accountId);
    setAccounts((prev) => prev.filter((a) => a.id !== accountId));
  };

  const activeAccounts = accounts.filter((a) => a.is_active);

  const SCOPES = [
    { name: "ads_management", desc: "Create and edit campaigns" },
    { name: "ads_read", desc: "Read ad performance data" },
    { name: "business_management", desc: "Access business accounts" },
    { name: "pages_read_engagement", desc: "Read page engagement" },
  ];

  return (
    <div className="p-8 w-full animate-fade-in">
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-1">Settings</h1>
        <p className="text-sm text-gray-500">Manage your integrations and ad account connections.</p>
      </div>

      {/* Banner */}
      {banner && (
        <div className={`mb-6 flex items-center gap-3 px-4 py-3.5 rounded-xl text-sm animate-slide-up ${
          banner.type === "success"
            ? "bg-emerald-500/[0.08] border border-emerald-500/20 text-emerald-400"
            : "bg-red-500/[0.08] border border-red-500/20 text-red-400"
        }`}>
          {banner.type === "success" ? (
            <CheckCircle2 className="w-4 h-4 shrink-0" />
          ) : (
            <AlertTriangle className="w-4 h-4 shrink-0" />
          )}
          <span className="flex-1 font-medium">{banner.text}</span>
          <button onClick={() => setBanner(null)} className="opacity-50 hover:opacity-100 transition-opacity shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* ── Meta Integration card ─────────────────────────────────── */}
      <div className="glass rounded-2xl overflow-hidden mb-8">
        {/* Card header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-white/[0.06]">
          <div className="flex items-center gap-3.5">
            {/* Facebook logo mark */}
            <div className="w-10 h-10 rounded-xl bg-[#1877F2]/10 border border-[#1877F2]/20 flex items-center justify-center shrink-0">
              <svg className="w-5 h-5 fill-[#1877F2]" viewBox="0 0 24 24">
                <path d="M24 12.073C24 5.404 18.627 0 12 0S0 5.404 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.41c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.97h-1.514c-1.491 0-1.956.93-1.956 1.884v2.25h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z" />
              </svg>
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Meta Business</p>
              <p className="text-xs text-gray-500">Facebook Ads · Instagram Ads</p>
            </div>
          </div>
          <ConnectMetaButton />
        </div>

        {/* Permissions info */}
        <div className="px-6 py-5">
          <div className="flex items-center gap-2 mb-4">
            <Shield className="w-3.5 h-3.5 text-gray-600" />
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider">Permissions requested</p>
          </div>
          <div className="grid grid-cols-2 gap-2.5">
            {SCOPES.map((scope) => (
              <div key={scope.name} className="flex items-start gap-2.5 px-3 py-2.5 rounded-xl bg-white/[0.02] border border-white/[0.04]">
                <div className="w-1.5 h-1.5 rounded-full bg-blue-500/60 mt-1.5 shrink-0" />
                <div className="min-w-0">
                  <p className="text-xs font-mono text-gray-300">{scope.name}</p>
                  <p className="text-[11px] text-gray-600">{scope.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Manual API Connect */}
        <div className="border-t border-white/[0.06]">
          <button
            onClick={() => setManualOpen(!manualOpen)}
            className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-white/[0.02] transition-colors"
          >
            <div className="flex items-center gap-2.5">
              <Key className="w-4 h-4 text-gray-500" />
              <span className="text-xs font-medium text-gray-400">Connect via API Token (Advanced)</span>
            </div>
            {manualOpen ? <ChevronUp className="w-4 h-4 text-gray-600" /> : <ChevronDown className="w-4 h-4 text-gray-600" />}
          </button>
          {manualOpen && (
            <div className="px-6 pb-5 space-y-3 animate-fade-in">
              <p className="text-[11px] text-gray-600 leading-relaxed">
                Paste a Meta User Access Token and Ad Account ID. The token must have <code className="text-gray-400">ads_management</code> and <code className="text-gray-400">ads_read</code> permissions.
              </p>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Meta Access Token</label>
                <input
                  type="password"
                  value={manualToken}
                  onChange={(e) => setManualToken(e.target.value)}
                  placeholder="EAA..."
                  className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all font-mono"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Ad Account ID</label>
                <input
                  type="text"
                  value={manualAccountId}
                  onChange={(e) => setManualAccountId(e.target.value)}
                  placeholder="act_1234567890"
                  className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all font-mono"
                />
              </div>
              {manualError && (
                <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/[0.08] border border-red-500/20 rounded-xl px-3 py-2">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{manualError}</span>
                </div>
              )}
              <button
                onClick={handleManualConnect}
                disabled={manualLoading || !manualToken.trim() || !manualAccountId.trim()}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500 text-white transition-all disabled:opacity-50"
              >
                {manualLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Key className="w-4 h-4" />}
                {manualLoading ? "Validating..." : "Connect API"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Smart AI Tracking (Pixel / WhatsApp) ──────────────────── */}
      <SmartTrackingCard />

      {/* ── Social Profiles (Facebook Page + Instagram) ────────────── */}
      {accounts.length > 0 && (
        <div className="glass rounded-2xl p-6 mb-8 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-pink-500/10 border border-pink-500/20 flex items-center justify-center shrink-0">
                <Instagram className="w-5 h-5 text-pink-400" />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">Social Profiles</p>
                <p className="text-xs text-gray-500">Facebook Page &amp; linked Instagram account.</p>
              </div>
            </div>
            <button
              onClick={async () => {
                setSocialLoading(true);
                try {
                  const { data } = await api.fetchSocialIdentities();
                  setSocialPages(data.pages || []);
                } catch { setSocialPages([]); }
                finally { setSocialLoading(false); }
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.04] border border-white/[0.08] text-gray-400 hover:text-white transition-all"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${socialLoading ? "animate-spin" : ""}`} />
              {socialLoading ? "Fetching…" : "Refresh"}
            </button>
          </div>

          {socialPages.length > 0 ? (
            <div className="space-y-3">
              {socialPages.map((p) => (
                <div key={p.page_id} className="flex items-center gap-4 p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <Facebook className="w-5 h-5 text-blue-400 shrink-0" />
                    <div className="truncate">
                      <p className="text-sm text-white font-medium truncate">{p.page_name}</p>
                      <p className="text-xs text-gray-500">ID: {p.page_id}</p>
                    </div>
                  </div>
                  {p.instagram_actor_id ? (
                    <div className="flex items-center gap-2">
                      {p.instagram_profile_pic && (
                        <img src={p.instagram_profile_pic} alt="" className="w-6 h-6 rounded-full" />
                      )}
                      <div className="text-right">
                        <p className="text-sm text-white">{p.instagram_username ? `@${p.instagram_username}` : `ID: ${p.instagram_actor_id}`}</p>
                        <p className="text-xs text-emerald-400">IG linked</p>
                      </div>
                    </div>
                  ) : (
                    <span className="text-xs text-gray-600">No IG linked</span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-600">Click &quot;Refresh&quot; to load your social profiles.</p>
          )}
        </div>
      )}

      {/* ── Ad Placements Preference ──────────────────────────────── */}
      <div className="glass rounded-2xl p-6 mb-8 space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center shrink-0">
            <Monitor className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white">Ad Placements</p>
            <p className="text-xs text-gray-500">Where your ads appear by default. Can be overridden per campaign.</p>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {PLACEMENT_OPTIONS.map((o) => (
            <button
              key={o.value}
              onClick={() => {
                setPrefs((p) => ({ ...p, ad_placements: o.value }));
                api.upsertPreferences({ ...prefs, ad_placements: o.value }).catch(() => {});
              }}
              className={`flex flex-col items-center gap-1.5 px-3 py-3 rounded-xl border text-sm transition-all ${
                prefs.ad_placements === o.value
                  ? "bg-blue-500/10 border-blue-500/30 text-blue-400"
                  : "bg-white/[0.02] border-white/[0.06] text-gray-400 hover:border-white/[0.12]"
              }`}
            >
              <o.icon className="w-5 h-5" />
              <span className="font-medium text-xs">{o.label}</span>
              {o.desc && <span className="text-[10px] text-gray-500">{o.desc}</span>}
            </button>
          ))}
        </div>
      </div>

      {/* ── AI Strategy Preferences ───────────────────────────────── */}
      <div className="glass rounded-2xl overflow-hidden mb-8">
        <button
          onClick={() => setStrategyOpen(!strategyOpen)}
          className="w-full flex items-center justify-between px-6 py-5 text-left"
        >
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center shrink-0">
              <Settings2 className="w-5 h-5 text-violet-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">AI Strategy Preferences</p>
              <p className="text-xs text-gray-500">Edit business info, posting frequency, tone, and budget anytime.</p>
            </div>
          </div>
          {strategyOpen ? <ChevronUp className="w-5 h-5 text-gray-500" /> : <ChevronDown className="w-5 h-5 text-gray-500" />}
        </button>

        {strategyOpen && !prefsLoading && (
          <div className="px-6 pb-6 space-y-5 border-t border-white/[0.06] pt-5 animate-fade-in">
            {/* Business Info */}
            <div className="space-y-3">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">Business Info</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Business Name</label>
                  <input type="text" value={prefs.business_name} onChange={(e) => setPrefs(p => ({ ...p, business_name: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" placeholder="Your Business" />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Website URL</label>
                  <input type="url" value={prefs.website_url} onChange={(e) => setPrefs(p => ({ ...p, website_url: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" placeholder="https://..." />
                  {prefs.website_url && (
                    <div className="mt-1.5 space-y-2">
                      {/* Additional pages input */}
                      <div>
                        <label className="text-[10px] text-gray-600 mb-0.5 block">Additional pages (products, about, etc.)</label>
                        <input type="text" value={extraUrls} onChange={(e) => setExtraUrls(e.target.value)}
                          placeholder="https://site.com/products, https://site.com/about"
                          className="w-full px-2.5 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-white text-xs placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" />
                      </div>
                      <div className="flex items-center gap-2">
                        {websiteScrapedAt ? (
                          <span className="text-[10px] text-emerald-400">Analyzed {new Date(websiteScrapedAt).toLocaleDateString()}</span>
                        ) : (
                          <span className="text-[10px] text-gray-600">Not analyzed yet</span>
                        )}
                        <button onClick={async () => {
                          setScraping(true);
                          const extras = extraUrls.split(",").map(u => u.trim()).filter(u => u.startsWith("http"));
                          try {
                            await api.scrapeWebsite(extras.length ? extras : undefined);
                            setBanner({ type: "success", text: `Analyzing ${1 + extras.length} page(s)… this takes ~20-30 seconds.` });
                            // Poll every 5s up to 60s until website_intel appears
                            let attempts = 0;
                            const poll = setInterval(async () => {
                              attempts++;
                              try {
                                const { data } = await api.getPreferences();
                                if (data?.website_intel && data?.website_scraped_at !== websiteScrapedAt) {
                                  setWebsiteIntel(data.website_intel);
                                  setWebsiteScrapedAt(data.website_scraped_at);
                                  setScraping(false);
                                  clearInterval(poll);
                                  setBanner({ type: "success", text: data.website_intel.error ? "Analysis completed with errors." : "Website analyzed successfully! Check results below." });
                                } else if (attempts >= 12) {
                                  setScraping(false);
                                  clearInterval(poll);
                                  setBanner({ type: "error", text: "Analysis is taking longer than expected. Refresh the page in a minute." });
                                }
                              } catch { /* keep polling */ }
                            }, 5000);
                          } catch { setBanner({ type: "error", text: "Failed to start analysis." }); setScraping(false); }
                        }} disabled={scraping} className={`text-[10px] underline ${scraping ? "text-amber-400" : "text-violet-400 hover:text-violet-300"}`}>
                          {scraping ? "Analyzing… (please wait)" : "Analyze now"}
                        </button>
                      </div>
                      {/* Show scraped intel */}
                      {websiteIntel && !websiteIntel.error && (
                        <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] space-y-2">
                          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Website Intelligence</p>
                          {websiteIntel.business_type && (
                            <p className="text-xs text-gray-300"><span className="text-gray-500">Type:</span> {String(websiteIntel.business_type)}</p>
                          )}
                          {websiteIntel.key_offerings_summary && (
                            <p className="text-xs text-gray-300"><span className="text-gray-500">Summary:</span> {String(websiteIntel.key_offerings_summary)}</p>
                          )}
                          {Array.isArray(websiteIntel.products_or_services) && (websiteIntel.products_or_services as Array<{name?: string; description?: string; price?: string}>).length > 0 && (
                            <div>
                              <p className="text-[10px] text-gray-500 mb-1">Products / Services found:</p>
                              <div className="flex flex-wrap gap-1">
                                {(websiteIntel.products_or_services as Array<{name?: string}>).slice(0, 8).map((p, i) => (
                                  <span key={i} className="px-2 py-0.5 rounded-md bg-violet-500/10 text-violet-300 text-[10px] border border-violet-500/15">
                                    {p.name || "Unnamed"}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                          {Array.isArray(websiteIntel.value_propositions) && (websiteIntel.value_propositions as string[]).length > 0 && (
                            <div>
                              <p className="text-[10px] text-gray-500 mb-1">Value Props:</p>
                              <ul className="list-disc list-inside text-xs text-gray-400 space-y-0.5">
                                {(websiteIntel.value_propositions as string[]).slice(0, 4).map((v, i) => <li key={i}>{v}</li>)}
                              </ul>
                            </div>
                          )}
                          {websiteIntel.brand_tone && (
                            <p className="text-xs text-gray-300"><span className="text-gray-500">Tone:</span> {String(websiteIntel.brand_tone)}</p>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-1.5"><Globe className="w-3 h-3" />Country You Serve</label>
                <select value={prefs.target_country} onChange={(e) => setPrefs(p => ({ ...p, target_country: e.target.value }))}
                  className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-violet-500/40 transition-all">
                  <option value="PK">Pakistan</option>
                  <option value="US">United States</option>
                  <option value="GB">United Kingdom</option>
                  <option value="AE">UAE</option>
                  <option value="SA">Saudi Arabia</option>
                  <option value="IN">India</option>
                  <option value="CA">Canada</option>
                  <option value="AU">Australia</option>
                  <option value="DE">Germany</option>
                  <option value="FR">France</option>
                  <option value="TR">Turkey</option>
                  <option value="MY">Malaysia</option>
                  <option value="NG">Nigeria</option>
                  <option value="KE">Kenya</option>
                  <option value="BD">Bangladesh</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block flex items-center gap-1.5"><Phone className="w-3 h-3" />WhatsApp Number</label>
                <input type="tel" value={prefs.whatsapp_number} onChange={(e) => setPrefs(p => ({ ...p, whatsapp_number: e.target.value }))}
                  className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" placeholder="+92 300 1234567" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Business Description</label>
                <textarea value={prefs.business_description} onChange={(e) => setPrefs(p => ({ ...p, business_description: e.target.value }))} rows={2}
                  className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all resize-none" placeholder="What does your business do?" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Target Audience</label>
                  <input type="text" value={prefs.target_audience} onChange={(e) => setPrefs(p => ({ ...p, target_audience: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" placeholder="e.g. Women 25-45" />
                </div>
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Industry / Niche</label>
                  <input type="text" value={prefs.industry_niche} onChange={(e) => setPrefs(p => ({ ...p, industry_niche: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all" placeholder="e.g. DTC Skincare" />
                </div>
              </div>
            </div>

            {/* Posting Frequency */}
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-2">Posting Frequency</p>
              <div className="grid grid-cols-4 gap-2">
                {FREQ_OPTIONS.map((o) => (
                  <button key={o.value} onClick={() => setPrefs(p => ({ ...p, posting_frequency: o.value }))}
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                      prefs.posting_frequency === o.value ? "bg-blue-500/10 border-blue-500/30 text-blue-400" : "bg-white/[0.02] border-white/[0.06] text-gray-400 hover:border-white/[0.12]"
                    }`}>
                    <o.icon className="w-3.5 h-3.5" /> {o.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Content Tone */}
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-2">Content Tone</p>
              <div className="grid grid-cols-4 gap-2">
                {TONE_OPTIONS.map((o) => (
                  <button key={o.value} onClick={() => setPrefs(p => ({ ...p, content_tone: o.value }))}
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                      prefs.content_tone === o.value ? "bg-violet-500/10 border-violet-500/30 text-violet-400" : "bg-white/[0.02] border-white/[0.06] text-gray-400 hover:border-white/[0.12]"
                    }`}>
                    <o.icon className="w-3.5 h-3.5" /> {o.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Ad Budget */}
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-2">Daily Ad Budget</p>
              {/* Currency selector */}
              <div className="flex flex-wrap gap-2 mb-2">
                {BUDGET_CURRENCIES.map((c) => (
                  <button key={c.value} onClick={() => setPrefs(p => ({ ...p, budget_currency: c.value }))}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                      prefs.budget_currency === c.value ? "bg-violet-500/10 border-violet-500/30 text-violet-400" : "bg-white/[0.02] border-white/[0.06] text-gray-400 hover:border-white/[0.12]"
                    }`}>
                    {c.label}
                  </button>
                ))}
              </div>
              {/* Budget level */}
              <div className="grid grid-cols-4 gap-2">
                {BUDGET_OPTIONS.map((o) => {
                  const sym = BUDGET_CURRENCIES.find(c => c.value === prefs.budget_currency)?.symbol || "$";
                  return (
                    <button key={o.value} onClick={() => setPrefs(p => ({ ...p, ad_budget_level: o.value }))}
                      className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${
                        prefs.ad_budget_level === o.value ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" : "bg-white/[0.02] border-white/[0.06] text-gray-400 hover:border-white/[0.12]"
                      }`}>
                      <o.icon className="w-3.5 h-3.5" /> {o.value === "custom" ? "Custom" : `${sym}${o.amount}/day`}
                    </button>
                  );
                })}
              </div>
              {prefs.ad_budget_level === "custom" && (
                <input type="number" min={1} value={prefs.custom_budget ?? ""} onChange={(e) => setPrefs(p => ({ ...p, custom_budget: e.target.value ? parseFloat(e.target.value) : undefined }))}
                  placeholder={`Enter daily budget (${BUDGET_CURRENCIES.find(c => c.value === prefs.budget_currency)?.symbol || "$"})`}
                  className="mt-2 w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-emerald-500/40 transition-all" />
              )}
            </div>

            {/* Save button */}
            <button onClick={savePrefs} disabled={prefsSaving}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-violet-600 to-blue-600 hover:from-violet-500 hover:to-blue-500 text-white transition-all disabled:opacity-50">
              {prefsSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
              {prefsSaving ? "Saving..." : "Save All Preferences"}
            </button>
          </div>
        )}
      </div>

      {/* ── Connected accounts ────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <Link2 className="w-4 h-4 text-gray-600" />
            <h2 className="text-sm font-semibold text-gray-300">
              Connected Ad Accounts
            </h2>
          </div>
          <span className="text-[11px] font-medium text-gray-500 bg-white/[0.04] border border-white/[0.06] px-2.5 py-1 rounded-full">
            {activeAccounts.length} active
          </span>
        </div>

        {loading ? (
          <div className="space-y-3">
            {[1, 2].map((i) => (
              <div key={i} className="h-[80px] rounded-2xl glass animate-pulse" />
            ))}
          </div>
        ) : activeAccounts.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/[0.08] p-12 text-center">
            <div className="w-12 h-12 rounded-2xl bg-white/[0.03] border border-white/[0.06] flex items-center justify-center mx-auto mb-4">
              <Link2 className="w-5 h-5 text-gray-600" />
            </div>
            <p className="text-sm text-gray-400 font-medium mb-1">No accounts connected</p>
            <p className="text-xs text-gray-600 max-w-xs mx-auto">
              Click &ldquo;Connect with Facebook&rdquo; above to link your ad accounts and start managing campaigns.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {activeAccounts.map((account) => (
              <AdAccountCard key={account.id} account={account} onDisconnect={handleDisconnect} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
