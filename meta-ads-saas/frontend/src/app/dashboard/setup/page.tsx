"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import {
  Calendar,
  CalendarDays,
  Sun,
  Hand,
  Briefcase,
  Smile,
  GraduationCap,
  Megaphone,
  PiggyBank,
  TrendingUp,
  Rocket,
  ArrowRight,
  ArrowLeft,
  Check,
  Sparkles,
  Shield,
  Store,
  Globe,
  Users,
  FileText,
  SlidersHorizontal,
} from "lucide-react";

/* ── Option types ─────────────────────────────────────────── */

type Option = {
  value: string;
  label: string;
  description: string;
  icon: React.ElementType;
  color: string;
};

const FREQUENCIES: Option[] = [
  { value: "daily", label: "Daily", description: "Post every day for maximum reach", icon: Calendar, color: "from-blue-500/20 to-blue-600/10 border-blue-500/20 text-blue-400" },
  { value: "3x_weekly", label: "3x / Week", description: "Balanced cadence, Mon-Wed-Fri", icon: CalendarDays, color: "from-violet-500/20 to-violet-600/10 border-violet-500/20 text-violet-400" },
  { value: "weekends_only", label: "Weekends Only", description: "Saturday & Sunday posts", icon: Sun, color: "from-amber-500/20 to-amber-600/10 border-amber-500/20 text-amber-400" },
  { value: "manual_only", label: "Manual Only", description: "You decide when to post", icon: Hand, color: "from-emerald-500/20 to-emerald-600/10 border-emerald-500/20 text-emerald-400" },
];

const TONES: Option[] = [
  { value: "professional", label: "Professional", description: "Clean, authoritative, trust-building", icon: Briefcase, color: "from-blue-500/20 to-blue-600/10 border-blue-500/20 text-blue-400" },
  { value: "humorous", label: "Humorous", description: "Witty, relatable, scroll-stopping", icon: Smile, color: "from-amber-500/20 to-amber-600/10 border-amber-500/20 text-amber-400" },
  { value: "educational", label: "Educational", description: "Informative, value-driven content", icon: GraduationCap, color: "from-emerald-500/20 to-emerald-600/10 border-emerald-500/20 text-emerald-400" },
  { value: "promotional", label: "Promotional", description: "Direct offers, urgency, CTAs", icon: Megaphone, color: "from-rose-500/20 to-rose-600/10 border-rose-500/20 text-rose-400" },
];

const BUDGETS: Option[] = [
  { value: "conservative_$10", label: "Conservative", description: "$10/day — test & learn", icon: PiggyBank, color: "from-emerald-500/20 to-emerald-600/10 border-emerald-500/20 text-emerald-400" },
  { value: "moderate_$30", label: "Moderate", description: "$30/day — steady growth", icon: TrendingUp, color: "from-blue-500/20 to-blue-600/10 border-blue-500/20 text-blue-400" },
  { value: "aggressive_$50", label: "Aggressive", description: "$50/day — scale fast", icon: Rocket, color: "from-violet-500/20 to-violet-600/10 border-violet-500/20 text-violet-400" },
  { value: "custom", label: "Custom", description: "Set your own daily budget", icon: SlidersHorizontal, color: "from-rose-500/20 to-rose-600/10 border-rose-500/20 text-rose-400" },
];

/* ── Step definitions ─────────────────────────────────────── */

type CardStep = {
  type: "cards";
  title: string;
  subtitle: string;
  options: Option[];
  key: string;
};

type BusinessStep = {
  type: "business";
  title: string;
  subtitle: string;
};

type Step = CardStep | BusinessStep;

const STEPS: Step[] = [
  { type: "business", title: "Your Business", subtitle: "Tell us about your business so AI can create relevant ads." },
  { type: "cards", title: "Posting Frequency", subtitle: "How often should the AI create content?", options: FREQUENCIES, key: "posting_frequency" },
  { type: "cards", title: "Content Tone", subtitle: "What voice fits your brand?", options: TONES, key: "content_tone" },
  { type: "cards", title: "Ad Budget", subtitle: "Set your daily paid-ad spend limit.", options: BUDGETS, key: "ad_budget_level" },
];

const TOTAL_STEPS = STEPS.length;

/* ── Component ────────────────────────────────────────────── */

export default function StrategySetupPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Business info (step 0)
  const [business, setBusiness] = useState({
    business_name: "",
    business_description: "",
    target_audience: "",
    website_url: "",
    industry_niche: "",
  });

  // Card selections (steps 1-3)
  const [selections, setSelections] = useState({
    posting_frequency: "",
    content_tone: "",
    ad_budget_level: "",
  });
  const [customBudget, setCustomBudget] = useState("");

  const current = STEPS[step];
  const isLastStep = step === TOTAL_STEPS - 1;

  // Can proceed logic
  const canProceed = (() => {
    if (current.type === "business") {
      return business.business_name.trim() !== "" && business.business_description.trim() !== "";
    }
    const val = selections[(current as CardStep).key as keyof typeof selections];
    if ((current as CardStep).key === "ad_budget_level" && val === "custom") {
      return customBudget !== "" && parseFloat(customBudget) > 0;
    }
    return val !== "";
  })();

  const select = (value: string) => {
    const key = (current as CardStep).key as keyof typeof selections;
    setSelections((prev) => ({ ...prev, [key]: value }));
  };

  const next = async () => {
    if (!canProceed) return;
    if (!isLastStep) {
      setStep((s) => s + 1);
      return;
    }
    // Final step — save everything
    setSaving(true);
    setError(null);
    try {
      await api.upsertPreferences({
        business_name: business.business_name,
        business_description: business.business_description,
        target_audience: business.target_audience,
        website_url: business.website_url,
        industry_niche: business.industry_niche || undefined,
        posting_frequency: selections.posting_frequency,
        content_tone: selections.content_tone,
        ad_budget_level: selections.ad_budget_level,
        custom_budget: selections.ad_budget_level === "custom" ? parseFloat(customBudget) : undefined,
        approval_required: true,
      });
      router.push("/dashboard");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save preferences. Please try again.";
      console.error("Failed to save preferences:", err);
      setError(msg);
      setSaving(false);
    }
  };

  const back = () => step > 0 && setStep((s) => s - 1);

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="w-full max-w-2xl animate-fade-in">
        {/* Header */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full glass text-xs text-gray-400 mb-5">
            <Sparkles className="w-3.5 h-3.5 text-violet-400" />
            Step {step + 1} of {TOTAL_STEPS}
          </div>
          <h1 className="text-3xl font-bold text-white mb-2">{current.title}</h1>
          <p className="text-gray-500">{current.subtitle}</p>
        </div>

        {/* Progress bar */}
        <div className="flex gap-2 mb-8">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`h-1 flex-1 rounded-full transition-all duration-500 ${
                i <= step ? "bg-gradient-to-r from-blue-500 to-violet-500" : "bg-white/[0.06]"
              }`}
            />
          ))}
        </div>

        {/* Step content */}
        {current.type === "business" ? (
          <div className="space-y-4 mb-8">
            {/* Business Name */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-2">
                <Store className="w-4 h-4 text-blue-400" />
                Business Name <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={business.business_name}
                onChange={(e) => setBusiness((b) => ({ ...b, business_name: e.target.value }))}
                placeholder="e.g. Acme Digital Agency"
                className="w-full px-4 py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/40 focus:bg-white/[0.06] transition-all"
              />
            </div>

            {/* Business Description */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-2">
                <FileText className="w-4 h-4 text-violet-400" />
                What does your business do? <span className="text-red-400">*</span>
              </label>
              <textarea
                value={business.business_description}
                onChange={(e) => setBusiness((b) => ({ ...b, business_description: e.target.value }))}
                placeholder="e.g. We sell organic skincare products for women aged 25-45. Our best sellers are vitamin C serum and hyaluronic acid moisturizer."
                rows={3}
                className="w-full px-4 py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/40 focus:bg-white/[0.06] transition-all resize-none"
              />
              <p className="text-xs text-gray-600 mt-1">Include products/services, pricing, and what makes you unique.</p>
            </div>

            {/* Target Audience */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-2">
                <Users className="w-4 h-4 text-emerald-400" />
                Target Audience
              </label>
              <input
                type="text"
                value={business.target_audience}
                onChange={(e) => setBusiness((b) => ({ ...b, target_audience: e.target.value }))}
                placeholder="e.g. Women 25-45, interested in clean beauty and wellness"
                className="w-full px-4 py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/40 focus:bg-white/[0.06] transition-all"
              />
            </div>

            {/* Website */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-2">
                <Globe className="w-4 h-4 text-amber-400" />
                Website URL
              </label>
              <input
                type="url"
                value={business.website_url}
                onChange={(e) => setBusiness((b) => ({ ...b, website_url: e.target.value }))}
                placeholder="https://yoursite.com"
                className="w-full px-4 py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/40 focus:bg-white/[0.06] transition-all"
              />
            </div>

            {/* Industry / Niche */}
            <div>
              <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-2">
                <Briefcase className="w-4 h-4 text-violet-400" />
                Industry / Niche <span className="text-xs text-gray-600 ml-1">(optional)</span>
              </label>
              <input
                type="text"
                value={business.industry_niche}
                onChange={(e) => setBusiness((b) => ({ ...b, industry_niche: e.target.value }))}
                placeholder="e.g. DTC Skincare, B2B SaaS, Local Restaurant"
                className="w-full px-4 py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 focus:outline-none focus:border-blue-500/40 focus:bg-white/[0.06] transition-all"
              />
              <p className="text-xs text-gray-600 mt-1">Helps AI reference trends and best practices in your niche.</p>
            </div>
          </div>
        ) : (
          <>
            {/* Option cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-8">
              {(current as CardStep).options.map((opt) => {
                const Icon = opt.icon;
                const active = selections[(current as CardStep).key as keyof typeof selections] === opt.value;
                return (
                  <button
                    key={opt.value}
                    onClick={() => select(opt.value)}
                    className={`relative text-left p-5 rounded-2xl border transition-all duration-300 group ${
                      active
                        ? `bg-gradient-to-br ${opt.color} border-opacity-100 scale-[1.02]`
                        : "bg-white/[0.02] border-white/[0.06] hover:bg-white/[0.04] hover:border-white/[0.1]"
                    }`}
                  >
                    {active && (
                      <div className="absolute top-3 right-3 w-6 h-6 rounded-full bg-white/10 flex items-center justify-center">
                        <Check className="w-3.5 h-3.5 text-white" />
                      </div>
                    )}
                    <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${opt.color} flex items-center justify-center mb-3`}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <p className={`font-semibold mb-1 ${active ? "text-white" : "text-gray-300"}`}>
                      {opt.label}
                    </p>
                    <p className={`text-sm ${active ? "text-gray-300" : "text-gray-600"}`}>
                      {opt.description}
                    </p>
                  </button>
                );
              })}
            </div>

            {/* Custom budget input */}
            {(current as CardStep).key === "ad_budget_level" && selections.ad_budget_level === "custom" && (
              <div className="mt-4">
                <label className="flex items-center gap-2 text-sm font-medium text-gray-300 mb-2">
                  <SlidersHorizontal className="w-4 h-4 text-rose-400" />
                  Daily Budget ($)
                </label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={customBudget}
                  onChange={(e) => setCustomBudget(e.target.value)}
                  placeholder="e.g. 25"
                  className="w-full px-4 py-3 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white placeholder-gray-600 focus:outline-none focus:border-rose-500/40 focus:bg-white/[0.06] transition-all"
                />
              </div>
            )}
          </>
        )}

        {/* Approval notice (last step) */}
        {isLastStep && (
          <div className="flex items-center gap-3 glass rounded-xl px-4 py-3 mb-8">
            <Shield className="w-5 h-5 text-blue-400 shrink-0" />
            <p className="text-sm text-gray-400">
              <span className="text-white font-medium">Human-in-the-loop:</span> The AI will always draft content for your approval before posting.
            </p>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="flex items-center gap-2 bg-red-500/[0.06] border border-red-500/20 rounded-xl px-4 py-3 mb-4">
            <span className="text-sm text-red-400">{error}</span>
          </div>
        )}

        {/* Navigation */}
        <div className="flex items-center justify-between">
          <button
            onClick={back}
            disabled={step === 0}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${
              step === 0
                ? "text-gray-700 cursor-not-allowed"
                : "text-gray-400 hover:text-white hover:bg-white/[0.04]"
            }`}
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </button>
          <button
            onClick={next}
            disabled={!canProceed || saving}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm font-semibold transition-all ${
              canProceed
                ? "bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white glow-blue hover:scale-[1.02] active:scale-[0.98]"
                : "bg-white/[0.04] text-gray-600 cursor-not-allowed"
            }`}
          >
            {saving ? (
              "Saving..."
            ) : isLastStep ? (
              <>
                Launch Dashboard
                <Sparkles className="w-4 h-4" />
              </>
            ) : (
              <>
                Continue
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
