"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import {
  BarChart3,
  TrendingUp,
  DollarSign,
  Target,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertCircle,
  Activity,
  Eye,
  MousePointerClick,
  ShoppingCart,
  Pause,
  RefreshCw,
  Filter,
  Inbox,
  ArrowUpRight,
  FileText,
  Users,
  Heart,
  Share2,
  Image,
  Calendar,
  Sparkles,
} from "lucide-react";
import { useRouter } from "next/navigation";

/* ── Types ────────────────────────────────────────────────── */

type AccountOverview = {
  name: string;
  status: string;
  currency: string;
  timezone: string;
  lifetime_spend: number;
  spend_cap: number | null;
  active_campaigns: number;
  spend_30d: number;
  roas_30d: number | null;
  purchases_30d: number;
  leads_30d: number;
  results_30d: number;
  result_type_30d: string;
  cost_per_result_30d: number;
  ad_account_id?: string;
};

type Campaign = {
  id: string;
  name: string;
  status: string;
  effective_status: string;
  objective: string;
  budget: number | null;
  budget_type: "daily" | "lifetime" | "cbo";
  created_time: string;
  spend_7d: number;
  roas_7d: number | null;
  purchases_7d: number;
  leads_7d: number;
  results_7d: number;
  result_type_7d: string;
  cost_per_result_7d: number;
  impressions_7d: number;
  ctr_7d: number;
  verdict: "scale" | "hold" | "underperforming" | "no_purchases" | "no_results" | "no_data" | "kill";
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
  cost_per_result: number;
  verdict: "scale" | "hold" | "underperforming" | "no_purchases" | "no_results" | "no_data" | "kill";
};

type FilterTab = "all" | "active" | "paused";

type PagePost = {
  id: string;
  message: string;
  created_time: string;
  likes: number;
  comments: number;
  reactions: number;
  shares: number;
  image_url: string | null;
  reach: number;
};

const FILTER_TABS: { value: FilterTab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
];

/* ── Verdict badge ────────────────────────────────────────── */

const VERDICT_STYLES: Record<string, { bg: string; icon: string; label: string }> = {
  scale:            { bg: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", icon: "🟢", label: "SCALE" },
  hold:             { bg: "bg-amber-500/10 text-amber-400 border-amber-500/20",    icon: "🟡", label: "HOLD" },
  underperforming:  { bg: "bg-red-500/10 text-red-400 border-red-500/20",          icon: "🔴", label: "UNDERPERFORMING" },
  no_purchases:     { bg: "bg-red-500/10 text-red-400 border-red-500/20",          icon: "🔴", label: "NO PURCHASES" },
  no_results:       { bg: "bg-red-500/10 text-red-400 border-red-500/20",          icon: "🔴", label: "NO RESULTS" },
  kill:             { bg: "bg-red-500/10 text-red-400 border-red-500/20",          icon: "🔴", label: "KILL" },
  no_data:          { bg: "bg-gray-500/10 text-gray-400 border-gray-500/20",       icon: "⚪", label: "NO DATA" },
};

function VerdictBadge({ verdict }: { verdict: string }) {
  const v = VERDICT_STYLES[verdict] ?? VERDICT_STYLES.no_data;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold uppercase tracking-wide border ${v.bg}`}>
      {v.icon} {v.label}
    </span>
  );
}

const RESULT_LABELS: Record<string, { label: string; costLabel: string; isCost: boolean }> = {
  purchases: { label: "Purchases", costLabel: "ROAS", isCost: false },
  leads: { label: "Leads", costLabel: "CPL", isCost: true },
  messaging_conversations: { label: "Chats", costLabel: "Cost/Chat", isCost: true },
  messaging_replies: { label: "Replies", costLabel: "Cost/Reply", isCost: true },
  link_clicks: { label: "Clicks", costLabel: "CPC", isCost: true },
  landing_page_views: { label: "LPV", costLabel: "Cost/LPV", isCost: true },
  none: { label: "Results", costLabel: "ROAS", isCost: false },
};

function getResultMeta(resultType: string) {
  return RESULT_LABELS[resultType] || RESULT_LABELS.none;
}

function StatusBadge({ status }: { status: string }) {
  const isActive = status === "ACTIVE";
  const bg = isActive
    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
    : "bg-gray-500/10 text-gray-400 border-gray-500/20";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold uppercase tracking-wide border ${bg}`}>
      {status}
    </span>
  );
}

/* ── Metric card ──────────────────────────────────────────── */

function MetricCard({
  label,
  value,
  icon: Icon,
  iconBg,
  change,
}: {
  label: string;
  value: string;
  icon: typeof DollarSign;
  iconBg: string;
  change?: string | null;
}) {
  return (
    <div className="glass rounded-2xl p-5 hover:bg-white/[0.04] transition-all duration-300">
      <div className="flex items-center justify-between mb-3">
        <div className={`w-9 h-9 rounded-xl ${iconBg} flex items-center justify-center`}>
          <Icon className="w-[18px] h-[18px]" />
        </div>
        {change && (
          <span className="flex items-center gap-0.5 text-xs text-emerald-400 font-medium">
            <ArrowUpRight className="w-3 h-3" />
            {change}
          </span>
        )}
      </div>
      <p className="text-sm text-gray-500 mb-0.5">{label}</p>
      <p className="text-2xl font-bold text-white tracking-tight">{value}</p>
    </div>
  );
}

/* ── Ad row ────────────────────────────────────────────────── */

function AdRow({ ad, currency, campaignId }: { ad: Ad; currency: string; campaignId: string }) {
  const router = useRouter();
  return (
    <div className="flex items-center gap-4 px-5 py-3 bg-white/[0.01] hover:bg-white/[0.03] transition-all border-b border-white/[0.04] last:border-b-0">
      {/* Thumbnail */}
      <div className="w-10 h-10 rounded-lg bg-white/[0.04] flex items-center justify-center shrink-0 overflow-hidden">
        {ad.thumbnail_url ? (
          <img src={ad.thumbnail_url} alt="" className="w-full h-full object-cover" />
        ) : (
          <Eye className="w-4 h-4 text-gray-600" />
        )}
      </div>

      {/* Name + status */}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-white font-medium truncate">{ad.name}</p>
        <div className="flex items-center gap-2 mt-0.5">
          <StatusBadge status={ad.effective_status} />
          <VerdictBadge verdict={ad.verdict} />
        </div>
      </div>

      {/* Metrics */}
      <div className="hidden md:flex items-center gap-6 text-xs text-gray-400">
        <div className="text-center w-20">
          <p className="text-gray-600">Spend</p>
          <p className="text-white font-medium">{ad.spend.toLocaleString()} {currency}</p>
        </div>
        <div className="text-center w-16">
          <p className="text-gray-600">{getResultMeta(ad.result_type).costLabel}</p>
          <p className="text-white font-medium">
            {getResultMeta(ad.result_type).isCost
              ? ad.cost_per_result > 0 ? `${ad.cost_per_result.toFixed(0)}` : "—"
              : ad.roas != null ? `${ad.roas.toFixed(2)}x` : "—"}
          </p>
        </div>
        <div className="text-center w-16">
          <p className="text-gray-600">CTR</p>
          <p className="text-white font-medium">{ad.ctr.toFixed(2)}%</p>
        </div>
        <div className="text-center w-16">
          <p className="text-gray-600">{getResultMeta(ad.result_type).label}</p>
          <p className="text-white font-medium">{ad.results}</p>
        </div>
      </div>

      {/* Get Suggestions button */}
      <button
        onClick={() => router.push(`/dashboard/copilot?ad_id=${ad.id}&campaign_id=${campaignId}&ad_name=${encodeURIComponent(ad.name)}`)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-500/10 text-violet-400 hover:bg-violet-500/20 border border-violet-500/20 transition-all shrink-0"
        title="Get AI suggestions for this ad"
      >
        <Sparkles className="w-3 h-3" />
        <span className="hidden lg:inline">Suggestions</span>
      </button>
    </div>
  );
}

/* ── Campaign card ─────────────────────────────────────────── */

function CampaignCard({
  campaign,
  currency,
  adAccountId,
  onPause,
  pauseLoading,
}: {
  campaign: Campaign;
  currency: string;
  adAccountId: string;
  onPause: (campaignId: string) => void;
  pauseLoading: string | null;
}) {
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const [ads, setAds] = useState<Ad[]>([]);
  const [loadingAds, setLoadingAds] = useState(false);

  const toggleExpand = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!expanded && ads.length === 0) {
      setLoadingAds(true);
      try {
        const { data } = await api.listAds(adAccountId, campaign.id);
        setAds(data.ads || []);
      } catch (err) {
        console.error("Failed to fetch ads:", err);
      } finally {
        setLoadingAds(false);
      }
    }
    setExpanded(!expanded);
  };

  const goToDetail = () => {
    router.push(`/dashboard/campaigns/${campaign.id}?ad_account_id=${adAccountId}`);
  };

  const budgetStr = campaign.budget
    ? `${campaign.budget.toLocaleString()} ${currency}${campaign.budget_type === "daily" ? "/day" : campaign.budget_type === "lifetime" ? " lifetime" : ""}`
    : "CBO";

  const isActive = campaign.effective_status === "ACTIVE";

  return (
    <div className="glass rounded-2xl overflow-hidden hover:bg-white/[0.02] transition-all duration-300">
      {/* Header row */}
      <div
        onClick={goToDetail}
        className="w-full flex items-center gap-4 p-5 text-left cursor-pointer"
      >
        <button
          onClick={toggleExpand}
          className="w-8 h-8 rounded-lg bg-white/[0.04] flex items-center justify-center shrink-0 hover:bg-white/[0.08] transition-all"
        >
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-400" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-white font-semibold truncate hover:text-blue-400 transition-colors">{campaign.name}</h3>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <StatusBadge status={campaign.effective_status} />
            <VerdictBadge verdict={campaign.verdict} />
            <span className="text-[11px] text-gray-600">{campaign.objective}</span>
          </div>
        </div>

        {/* Key metrics */}
        <div className="hidden lg:flex items-center gap-6 text-xs text-gray-400 shrink-0">
          <div className="text-center w-20">
            <p className="text-gray-600">Budget</p>
            <p className="text-white font-medium text-[11px]">{budgetStr}</p>
          </div>
          <div className="text-center w-20">
            <p className="text-gray-600">Spend (7d)</p>
            <p className="text-white font-medium">{campaign.spend_7d.toLocaleString()} {currency}</p>
          </div>
          <div className="text-center w-16">
            <p className="text-gray-600">{getResultMeta(campaign.result_type_7d).costLabel}</p>
            {getResultMeta(campaign.result_type_7d).isCost ? (
              <p className="font-bold text-white">
                {campaign.cost_per_result_7d > 0 ? `${campaign.cost_per_result_7d.toFixed(0)}` : "—"}
              </p>
            ) : (
              <p className={`font-bold ${(campaign.roas_7d ?? 0) >= 3 ? "text-emerald-400" : (campaign.roas_7d ?? 0) >= 1.5 ? "text-amber-400" : (campaign.roas_7d ?? 0) > 0 ? "text-red-400" : "text-gray-500"}`}>
                {campaign.roas_7d != null ? `${campaign.roas_7d.toFixed(2)}x` : "—"}
              </p>
            )}
          </div>
          <div className="text-center w-16">
            <p className="text-gray-600">CTR</p>
            <p className="text-white font-medium">{campaign.ctr_7d.toFixed(2)}%</p>
          </div>
          <div className="text-center w-16">
            <p className="text-gray-600">{getResultMeta(campaign.result_type_7d).label}</p>
            <p className="text-white font-medium">{campaign.results_7d}</p>
          </div>
        </div>
      </div>

      {/* Mobile metrics */}
      <div className="lg:hidden grid grid-cols-4 gap-2 px-5 pb-3 text-xs text-gray-400">
        <div>
          <p className="text-gray-600">Spend (7d)</p>
          <p className="text-white font-medium">{campaign.spend_7d.toLocaleString()}</p>
        </div>
        <div>
          <p className="text-gray-600">{getResultMeta(campaign.result_type_7d).costLabel}</p>
          {getResultMeta(campaign.result_type_7d).isCost ? (
            <p className="font-bold text-white">
              {campaign.cost_per_result_7d > 0 ? `${campaign.cost_per_result_7d.toFixed(0)}` : "—"}
            </p>
          ) : (
            <p className={`font-bold ${(campaign.roas_7d ?? 0) >= 3 ? "text-emerald-400" : (campaign.roas_7d ?? 0) >= 1.5 ? "text-amber-400" : (campaign.roas_7d ?? 0) > 0 ? "text-red-400" : "text-gray-500"}`}>
              {campaign.roas_7d != null ? `${campaign.roas_7d.toFixed(2)}x` : "—"}
            </p>
          )}
        </div>
        <div>
          <p className="text-gray-600">CTR</p>
          <p className="text-white font-medium">{campaign.ctr_7d.toFixed(2)}%</p>
        </div>
        <div>
          <p className="text-gray-600">{getResultMeta(campaign.result_type_7d).label}</p>
          <p className="text-white font-medium">{campaign.results_7d}</p>
        </div>
      </div>

      {/* Expanded: Ads list */}
      {expanded && (
        <div className="border-t border-white/[0.06]">
          {/* Actions bar */}
          <div className="flex items-center justify-between px-5 py-2 bg-white/[0.02]">
            <p className="text-xs text-gray-500">
              {ads.length > 0 ? `${ads.length} ad(s)` : "Loading ads..."}
            </p>
            {isActive && (
              <button
                onClick={(e) => { e.stopPropagation(); onPause(campaign.id); }}
                disabled={pauseLoading === campaign.id}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-amber-400 bg-amber-500/[0.06] border border-amber-500/20 hover:bg-amber-500/[0.12] transition-all disabled:opacity-50"
              >
                {pauseLoading === campaign.id ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Pause className="w-3 h-3" />
                )}
                Pause Campaign
              </button>
            )}
          </div>

          {loadingAds ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 text-gray-600 animate-spin" />
            </div>
          ) : ads.length === 0 ? (
            <div className="py-6 text-center text-sm text-gray-600">
              No ads found in this campaign.
            </div>
          ) : (
            <div>
              {ads.map((ad) => (
                <AdRow key={ad.id} ad={ad} currency={currency} campaignId={campaign.id} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Post card ─────────────────────────────────────────────── */

function PostCard({ post }: { post: PagePost }) {
  const date = post.created_time
    ? new Date(post.created_time).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "";

  return (
    <div className="glass rounded-2xl overflow-hidden hover:bg-white/[0.02] transition-all duration-300">
      <div className="flex gap-4 p-5">
        {/* Image thumbnail */}
        <div className="w-16 h-16 rounded-xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center shrink-0 overflow-hidden">
          {post.image_url ? (
            <img src={post.image_url} alt="" className="w-full h-full object-cover" />
          ) : (
            <FileText className="w-6 h-6 text-gray-600" />
          )}
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <p className="text-sm text-white font-medium line-clamp-2 mb-1.5">
            {post.message || "No text content"}
          </p>
          <div className="flex items-center gap-2 text-[11px] text-gray-500">
            <Calendar className="w-3 h-3" />
            <span>{date}</span>
          </div>
        </div>

        {/* Metrics */}
        <div className="hidden md:flex items-center gap-5 text-xs text-gray-400 shrink-0">
          <div className="text-center w-16">
            <div className="flex items-center justify-center gap-1 text-gray-600 mb-0.5">
              <Heart className="w-3 h-3" />
              <span>Likes</span>
            </div>
            <p className="text-white font-medium">{post.likes.toLocaleString()}</p>
          </div>
          <div className="text-center w-20">
            <div className="flex items-center justify-center gap-1 text-gray-600 mb-0.5">
              <FileText className="w-3 h-3" />
              <span>Comments</span>
            </div>
            <p className="text-white font-medium">{post.comments.toLocaleString()}</p>
          </div>
          <div className="text-center w-20">
            <div className="flex items-center justify-center gap-1 text-gray-600 mb-0.5">
              <Users className="w-3 h-3" />
              <span>Reactions</span>
            </div>
            <p className="text-white font-medium">{post.reactions.toLocaleString()}</p>
          </div>
          <div className="text-center w-16">
            <div className="flex items-center justify-center gap-1 text-gray-600 mb-0.5">
              <Share2 className="w-3 h-3" />
              <span>Shares</span>
            </div>
            <p className="text-white font-medium">{post.shares}</p>
          </div>
          {post.reach > 0 && (
            <div className="text-center w-16">
              <div className="flex items-center justify-center gap-1 text-gray-600 mb-0.5">
                <Eye className="w-3 h-3" />
                <span>Reach</span>
              </div>
              <p className="text-white font-medium">{post.reach.toLocaleString()}</p>
            </div>
          )}
        </div>
      </div>

      {/* Mobile metrics */}
      <div className="md:hidden grid grid-cols-4 gap-2 px-5 pb-4 text-xs text-gray-400">
        <div>
          <p className="text-gray-600">Likes</p>
          <p className="text-white font-medium">{post.likes.toLocaleString()}</p>
        </div>
        <div>
          <p className="text-gray-600">Comments</p>
          <p className="text-white font-medium">{post.comments.toLocaleString()}</p>
        </div>
        <div>
          <p className="text-gray-600">Reactions</p>
          <p className="text-white font-medium">{post.reactions.toLocaleString()}</p>
        </div>
        <div>
          <p className="text-gray-600">Shares</p>
          <p className="text-white font-medium">{post.shares}</p>
        </div>
      </div>
    </div>
  );
}

/* ── Page ──────────────────────────────────────────────────── */

export default function CampaignsPage() {
  const [overview, setOverview] = useState<AccountOverview | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [currency, setCurrency] = useState("USD");
  const [adAccountId, setAdAccountId] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterTab>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pauseLoading, setPauseLoading] = useState<string | null>(null);
  const [posts, setPosts] = useState<PagePost[]>([]);
  const [postsLoading, setPostsLoading] = useState(true);
  const [pageName, setPageName] = useState<string | null>(null);

  // Restore cached data on mount so page renders instantly
  useEffect(() => {
    try {
      const cached = sessionStorage.getItem("campaigns_cache");
      if (cached) {
        const c = JSON.parse(cached);
        if (c.overview) { setOverview(c.overview); setAdAccountId(c.overview.ad_account_id); setCurrency(c.overview.currency || "USD"); }
        if (c.campaigns) setCampaigns(c.campaigns);
        if (c.posts) setPosts(c.posts);
        if (c.pageName) setPageName(c.pageName);
        setLoading(false);
        setPostsLoading(false);
      }
    } catch { /* ignore */ }
  }, []);

  const fetchData = useCallback(async () => {
    // Only show full spinner if no cached data
    if (!overview) setLoading(true);
    setError(null);
    try {
      // First get the default overview to discover the ad account ID
      const { data: overviewData } = await api.getDefaultOverview();
      setOverview(overviewData);
      setAdAccountId(overviewData.ad_account_id);
      setCurrency(overviewData.currency || "USD");

      // Then fetch campaigns
      if (overviewData.ad_account_id) {
        const { data: campaignsData } = await api.listCampaigns(
          overviewData.ad_account_id,
          filter,
        );
        const sorted = (campaignsData.campaigns || []).sort((a: Campaign, b: Campaign) => b.spend_7d - a.spend_7d);
        setCampaigns(sorted);
        if (campaignsData.currency) setCurrency(campaignsData.currency);

        // Cache for instant next visit
        try {
          sessionStorage.setItem("campaigns_cache", JSON.stringify({
            overview: overviewData,
            campaigns: sorted,
          }));
        } catch { /* quota exceeded — ignore */ }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load campaign data";
      console.error("Campaign fetch error:", err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  const fetchPosts = useCallback(async () => {
    if (posts.length === 0) setPostsLoading(true);
    try {
      const { data } = await api.getPagePosts();
      setPosts(data.posts || []);
      if (data.page_name) setPageName(data.page_name);
      // Cache posts too
      try {
        const existing = JSON.parse(sessionStorage.getItem("campaigns_cache") || "{}");
        sessionStorage.setItem("campaigns_cache", JSON.stringify({
          ...existing,
          posts: data.posts || [],
          pageName: data.page_name || null,
        }));
      } catch { /* ignore */ }
    } catch (err) {
      console.error("Posts fetch error:", err);
    } finally {
      setPostsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchPosts();
  }, [fetchData, fetchPosts]);

  const handlePause = async (campaignId: string) => {
    if (!adAccountId) return;
    setPauseLoading(campaignId);
    try {
      await api.pauseCampaign(adAccountId, campaignId);
      // Optimistic UI update
      setCampaigns((prev) =>
        prev.map((c) =>
          c.id === campaignId ? { ...c, effective_status: "PAUSED", status: "PAUSED" } : c
        )
      );
      // Invalidate frontend cache so next visit fetches fresh data
      try { sessionStorage.removeItem("campaigns_cache"); } catch { /* ignore */ }
    } catch (err) {
      console.error("Pause failed:", err);
    } finally {
      setPauseLoading(null);
    }
  };

  return (
    <div className="p-8 w-full animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-white mb-1">
            Campaigns & <span className="gradient-text">Ads</span>
          </h1>
          <p className="text-sm text-gray-500">
            Monitor running ads and posts with real-time performance analysis.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { try { sessionStorage.removeItem("campaigns_cache"); } catch {} fetchData(); fetchPosts(); }}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-white/[0.04] border border-white/[0.08] text-gray-300 hover:bg-white/[0.06] transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
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

      {/* Error state */}
      {error && (
        <div className="glass rounded-2xl p-5 mb-6 border border-red-500/20 bg-red-500/[0.05]">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0" />
            <div>
              <p className="text-sm font-medium text-red-300">Failed to load campaign data</p>
              <p className="text-xs text-gray-500 mt-0.5">{error}</p>
            </div>
          </div>
        </div>
      )}

      {/* Account Overview Stats */}
      {overview && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <MetricCard
            label="Active Campaigns"
            value={String(overview.active_campaigns)}
            icon={Target}
            iconBg="bg-blue-500/10 text-blue-400"
          />
          <MetricCard
            label="Spend (30d)"
            value={`${overview.spend_30d.toLocaleString()} ${currency}`}
            icon={DollarSign}
            iconBg="bg-emerald-500/10 text-emerald-400"
          />
          {(() => {
            const ovMeta = getResultMeta(overview.result_type_30d);
            return ovMeta.isCost ? (
              <MetricCard
                label={`${ovMeta.costLabel} (30d)`}
                value={overview.cost_per_result_30d > 0 ? `${overview.cost_per_result_30d.toFixed(0)} ${currency}` : "—"}
                icon={TrendingUp}
                iconBg="bg-violet-500/10 text-violet-400"
              />
            ) : (
              <MetricCard
                label="ROAS (30d)"
                value={overview.roas_30d != null ? `${overview.roas_30d.toFixed(2)}x` : "—"}
                icon={TrendingUp}
                iconBg="bg-violet-500/10 text-violet-400"
                change={overview.roas_30d != null && overview.roas_30d >= 3 ? "Scaling" : overview.roas_30d != null && overview.roas_30d >= 1.5 ? "Profitable" : undefined}
              />
            );
          })()}
          <MetricCard
            label={`${getResultMeta(overview.result_type_30d).label} (30d)`}
            value={String(overview.results_30d)}
            icon={ShoppingCart}
            iconBg="bg-amber-500/10 text-amber-400"
          />
        </div>
      )}

      {/* Verdict Legend */}
      <div className="flex items-center gap-4 mb-4 text-[11px] text-gray-500 flex-wrap">
        <span className="font-medium text-gray-400">Verdicts (vs account baseline):</span>
        <span>🟢 Scale (20%+ better)</span>
        <span>🟡 Hold (within range)</span>
        <span>🔴 Underperforming (30%+ worse)</span>
        <span>⚪ No data</span>
      </div>

      {/* Campaign List */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 text-gray-600 animate-spin" />
        </div>
      ) : campaigns.length === 0 && !error ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-14 h-14 rounded-2xl bg-white/[0.04] border border-white/[0.06] flex items-center justify-center mb-4">
            <Inbox className="w-7 h-7 text-gray-600" />
          </div>
          <h2 className="text-lg font-semibold text-gray-300 mb-1">No campaigns found</h2>
          <p className="text-sm text-gray-600 max-w-sm">
            {filter !== "all"
              ? `No ${filter} campaigns. Try changing the filter.`
              : "Create your first campaign by approving an ad draft."}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {campaigns.map((campaign) => (
            <CampaignCard
              key={campaign.id}
              campaign={campaign}
              currency={currency}
              adAccountId={adAccountId || ""}
              onPause={handlePause}
              pauseLoading={pauseLoading}
            />
          ))}
        </div>
      )}

      {/* ── Page Posts Section ────────────────────────────────── */}
      <div className="mt-10">
        <div className="flex items-center gap-2.5 mb-4">
          <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
            <FileText className="w-4 h-4 text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">
              Page Posts
            </h2>
            <p className="text-xs text-gray-500">
              {pageName ? `Recent posts from ${pageName}` : "Organic posts from your Facebook Page"}
            </p>
          </div>
          {posts.length > 0 && (
            <span className="ml-auto text-[11px] font-medium text-gray-500 bg-white/[0.04] border border-white/[0.06] px-2.5 py-1 rounded-full">
              {posts.length} post{posts.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        {postsLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-5 h-5 text-gray-600 animate-spin" />
          </div>
        ) : posts.length === 0 ? (
          <div className="glass rounded-2xl p-10 text-center">
            <div className="w-12 h-12 rounded-2xl bg-white/[0.03] border border-white/[0.06] flex items-center justify-center mx-auto mb-3">
              <FileText className="w-5 h-5 text-gray-600" />
            </div>
            <p className="text-sm text-gray-400 font-medium mb-1">No posts yet</p>
            <p className="text-xs text-gray-600 max-w-xs mx-auto">
              Posts published to your Facebook Page will appear here with reach and engagement stats.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {posts.map((post) => (
              <PostCard key={post.id} post={post} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
