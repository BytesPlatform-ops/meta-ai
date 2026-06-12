/**
 * Typed API client for the FastAPI backend.
 * Automatically attaches the Supabase JWT from the browser session.
 */
import axios from "axios";
import { createClient, isSupabaseConfigured } from "./supabase/client";
import type { AdAccount } from "@/app/dashboard/settings/page";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:54562";

export const apiClient = axios.create({ baseURL: BASE_URL });

/** Resolve image URLs — converts relative paths to full backend URLs */
export function resolveImageUrl(url: string | null | undefined): string {
  if (!url) return "";
  if (url.startsWith("http")) return url;
  // Relative URL from local upload (e.g. /uploads/files/...)
  return `${BASE_URL}${url}`;
}

// Attach the Supabase session token + active workspace before every request
apiClient.interceptors.request.use(async (config) => {
  if (!isSupabaseConfigured()) return config;
  const supabase = createClient();
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // Attach active workspace ID from localStorage
  if (typeof window !== "undefined") {
    const wsId = localStorage.getItem("meta-ads-active-workspace-id");
    if (wsId) {
      config.headers["X-Workspace-Id"] = wsId;
    }
  }
  return config;
});

// ── API helpers ───────────────────────────────────────────────────────────────

export const api = {
  /** Meta OAuth */
  getMetaAuthUrl: () =>
    apiClient.get<{ authorization_url: string; state: string }>(
      "/api/v1/oauth/meta/authorize"
    ),
  listAdAccounts: () =>
    apiClient.get<AdAccount[]>("/api/v1/oauth/meta/accounts"),
  disconnectAdAccount: (accountId: string) =>
    apiClient.delete(`/api/v1/oauth/meta/accounts/${accountId}`),

  /** Products */
  listProducts: () => apiClient.get("/api/v1/products/"),
  getProduct: (id: string) => apiClient.get(`/api/v1/products/${id}`),
  createProduct: (data: unknown) => apiClient.post("/api/v1/products/", data),
  updateProduct: (id: string, data: unknown) =>
    apiClient.patch(`/api/v1/products/${id}`, data),
  deleteProduct: (id: string) => apiClient.delete(`/api/v1/products/${id}`),

  /** Product Variants */
  listVariants: (productId: string) =>
    apiClient.get(`/api/v1/products/${productId}/variants`),
  createVariant: (productId: string, data: unknown) =>
    apiClient.post(`/api/v1/products/${productId}/variants`, data),
  updateVariant: (productId: string, variantId: string, data: unknown) =>
    apiClient.patch(`/api/v1/products/${productId}/variants/${variantId}`, data),
  deleteVariant: (productId: string, variantId: string) =>
    apiClient.delete(`/api/v1/products/${productId}/variants/${variantId}`),

  /** Hiring / Jobs */
  listJobs: () => apiClient.get("/api/v1/hiring/"),
  getJob: (id: string) => apiClient.get(`/api/v1/hiring/${id}`),
  createJob: (data: unknown) => apiClient.post("/api/v1/hiring/", data),
  updateJob: (id: string, data: unknown) => apiClient.patch(`/api/v1/hiring/${id}`, data),
  deleteJob: (id: string) => apiClient.delete(`/api/v1/hiring/${id}`),

  /** Uploads */
  uploadProductImage: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return apiClient.post<{ url: string }>("/api/v1/uploads/product-image", formData);
  },

  /** Preferences */
  getPreferences: () =>
    apiClient.get("/api/v1/preferences"),
  upsertPreferences: (data: Record<string, unknown>) =>
    apiClient.put("/api/v1/preferences", data),

  /** AI Generation */
  generateDrafts: (count: number = 3, productId?: string, abTest?: boolean, userGuidance?: string, conversionEvent?: string, destinationType?: string, whatsappNumber?: string, selectedMessagingApps?: string[], callPhoneNumber?: string, hiringData?: { job_title: string; target_candidate_profile: string; salary_and_perks: string; requirements?: string; responsibilities?: string }, jobId?: string) => {
    const params = new URLSearchParams({ count: String(count) });
    if (productId) params.set("product_id", productId);
    if (jobId) params.set("job_id", jobId);
    if (abTest) params.set("ab_test", "true");
    return apiClient.post(`/api/v1/generate/drafts?${params.toString()}`, {
      user_guidance: userGuidance || null,
      conversion_event: conversionEvent || null,
      destination_type: destinationType || null,
      whatsapp_number: whatsappNumber || null,
      selected_messaging_apps: selectedMessagingApps || null,
      call_phone_number: callPhoneNumber || null,
      hiring_data: hiringData || null,
    });
  },

  /** Drafts */
  listDrafts: (status?: string) =>
    apiClient.get("/api/v1/drafts", { params: status ? { status } : {} }),
  getDraft: (id: string) =>
    apiClient.get(`/api/v1/drafts/${id}`),
  createDraft: (data: {
    draft_type: string;
    body_text: string;
    headline?: string;
    image_url?: string;
    cta_type?: string;
    proposed_budget?: number;
    targeting?: Record<string, unknown>;
    ai_reasoning?: string;
    ad_account_id?: string;
  }) => apiClient.post("/api/v1/drafts", data),
  updateDraft: (id: string, data: { headline?: string; body_text?: string; image_url?: string; cta_type?: string; proposed_budget?: number; draft_type?: string; targeting?: Record<string, unknown>; pixel_id?: string; conversion_event?: string; thumbnail_url?: string; destination_type?: string; whatsapp_number?: string; media_items?: { type: string; url: string; thumbnail_url?: string }[]; lead_form_id?: string; selected_messaging_apps?: string[]; call_phone_number?: string; status?: string; error_message?: string | null; target_country?: string | null; destination_url?: string | null }) =>
    apiClient.patch(`/api/v1/drafts/${id}`, data),
  approveDraft: (id: string) =>
    apiClient.patch(`/api/v1/drafts/${id}/approve`),
  launchAbTest: (draftIds: string[]) =>
    apiClient.post("/api/v1/drafts/launch-ab", { draft_ids: draftIds }),
  rejectDraft: (id: string) =>
    apiClient.patch(`/api/v1/drafts/${id}/reject`),
  pauseDraft: (id: string) =>
    apiClient.patch(`/api/v1/drafts/${id}/pause`),

  /** Campaigns */
  getAccountOverview: (adAccountId: string) =>
    apiClient.get(`/api/v1/campaigns/${adAccountId}/overview`),
  getDefaultOverview: (since?: string, until?: string) =>
    apiClient.get("/api/v1/campaigns/overview/default", {
      params: { ...(since && until ? { since, until } : {}) },
    }),
  getDashboardMetrics: (datePreset?: string, since?: string, until?: string, statusFilter: string = "active") =>
    apiClient.get("/api/v1/campaigns/dashboard/metrics", {
      params: { ...(datePreset ? { date_preset: datePreset } : {}), ...(since && until ? { since, until } : {}), status_filter: statusFilter },
    }),
  listCampaigns: (adAccountId: string, statusFilter: string = "all", limit: number = 25, since?: string, until?: string) =>
    apiClient.get(`/api/v1/campaigns/${adAccountId}/list`, {
      params: { status_filter: statusFilter, limit, ...(since && until ? { since, until } : {}) },
    }),
  getCampaignInsights: (adAccountId: string, campaignId: string, datePreset: string = "last_30d", since?: string, until?: string) =>
    apiClient.get(`/api/v1/campaigns/${adAccountId}/insights/${campaignId}`, {
      params: { date_preset: datePreset, ...(since && until ? { since, until } : {}) },
    }),
  getCampaignDetail: (adAccountId: string, campaignId: string, datePreset: string = "last_30d", since?: string, until?: string) =>
    apiClient.get(`/api/v1/campaigns/${adAccountId}/detail/${campaignId}`, {
      params: { date_preset: datePreset, ...(since && until ? { since, until } : {}) },
    }),
  listAds: (adAccountId: string, campaignId: string, datePreset: string = "last_30d", statusFilter: string = "all", since?: string, until?: string) =>
    apiClient.get(`/api/v1/campaigns/${adAccountId}/ads/${campaignId}`, {
      params: { date_preset: datePreset, status_filter: statusFilter, ...(since && until ? { since, until } : {}) },
    }),
  pauseCampaign: (adAccountId: string, campaignId: string) =>
    apiClient.post(`/api/v1/campaigns/${adAccountId}/pause`, { campaign_id: campaignId }),
  getPagePosts: () =>
    apiClient.get("/api/v1/campaigns/posts/default"),
  getDefaultTimeSeries: (datePreset: string = "last_30d", since?: string, until?: string) =>
    apiClient.get("/api/v1/campaigns/time-series/default", {
      params: { date_preset: datePreset, ...(since && until ? { since, until } : {}) },
    }),

  /** Account Audits */
  runAudit: (adAccountId?: string, statusFilter: string = "active") =>
    apiClient.post("/api/v1/audits/sync", null, {
      params: { ...(adAccountId ? { ad_account_id: adAccountId } : {}), status_filter: statusFilter },
    }),
  getLatestAudit: () =>
    apiClient.get("/api/v1/audits/latest"),
  generateAuditActions: () =>
    apiClient.post("/api/v1/audits/generate-actions"),

  /** Pixel / Smart Tracking */
  listPixels: () =>
    apiClient.get<{ pixels: { id: string; name: string }[] }>("/api/v1/meta/pixels"),
  getPixelEvents: (pixelId: string) =>
    apiClient.get<{
      pixel_id: string;
      name?: string | null;
      events: { event: string; count: number }[];
      days?: number;
      last_fired_time?: string | null;
      is_unavailable?: boolean;
      stats_error?: string | null;
    }>(`/api/v1/meta/pixels/${pixelId}/events`),
  createPixel: (pixelName?: string) =>
    apiClient.post("/api/v1/meta/pixels/create", { pixel_name: pixelName || "AI Pixel" }),
  savePixel: (pixelId: string | null) =>
    apiClient.post("/api/v1/meta/save-pixel", { pixel_id: pixelId }),
  emailDeveloper: (data: { developer_email: string; pixel_id: string; platform: string }) =>
    apiClient.post("/api/v1/meta/email-developer", data),
  scrapeWebsite: (extraUrls?: string[]) =>
    apiClient.post("/api/v1/preferences/scrape-website", extraUrls?.length ? { urls: extraUrls } : {}),
  scrapeUrlForOnboarding: (url: string) =>
    apiClient.post<{ intel: Record<string, unknown> | null; error?: string }>("/api/v1/preferences/scrape-url", { url }),
  fetchSocialIdentities: () =>
    apiClient.get<{ pages: { page_id: string; page_name: string; instagram_actor_id: string | null; instagram_username: string | null; instagram_profile_pic: string | null }[] }>("/api/v1/meta/identities"),
  checkWhatsAppStatus: () =>
    apiClient.get<{
      connected: boolean;
      page_id?: string;
      page_name?: string;
      whatsapp_number?: string | null;
      waba_id?: string | null;
      reason?: string | null;
      signals?: Record<string, unknown>;
    }>("/api/v1/meta/whatsapp-status"),

  /** Geo City Search */
  searchGeoCities: (query: string, country: string) =>
    apiClient.get<{ cities: { key: string; name: string; region: string; country_code: string; country_name: string }[] }>(`/api/v1/meta/geo-search`, { params: { q: query, country } }),

  /** Lead Forms */
  generateLeadFormDraft: (data: { draft_id?: string; product_name?: string; ad_text?: string; target_country?: string }) =>
    apiClient.post<{ form_name: string; questions: { type: string; key: string; label?: string }[]; reasoning: string }>("/api/v1/lead-forms/generate-draft", data),
  createLeadForm: (data: { page_id: string; form_name: string; questions: { type: string; key: string; label?: string }[]; save_form?: boolean }) =>
    apiClient.post("/api/v1/lead-forms", data),
  listLeadForms: () =>
    apiClient.get("/api/v1/lead-forms"),

  /** Workspaces */
  listWorkspaces: () =>
    apiClient.get("/api/v1/workspaces/"),
  createWorkspace: (data: { name: string; [key: string]: unknown }) =>
    apiClient.post("/api/v1/workspaces/", data),
  getWorkspace: (id: string) =>
    apiClient.get(`/api/v1/workspaces/${id}`),
  updateWorkspace: (id: string, data: Record<string, unknown>) =>
    apiClient.put(`/api/v1/workspaces/${id}`, data),
  deleteWorkspace: (id: string) =>
    apiClient.delete(`/api/v1/workspaces/${id}`),
  getPageIntel: () =>
    apiClient.get<{ intel: Record<string, unknown> | null; error?: string }>("/api/v1/workspaces/page-intel"),

  /** Meta Account Picker */
  getAvailableAccounts: () =>
    apiClient.get<{ accounts: { id: string; name: string; currency: string; timezone_name: string; already_linked: boolean }[] }>(
      "/api/v1/oauth/meta/available-accounts"
    ),
  linkAccounts: (accountIds: string[]) =>
    apiClient.post<{ linked: number; accounts: { meta_account_id: string; account_name: string }[] }>(
      "/api/v1/oauth/meta/link-accounts",
      { account_ids: accountIds },
    ),

  /** Manual Meta Connect */
  manualConnect: (accessToken: string, adAccountId: string) =>
    apiClient.post<{ message: string; accounts: { meta_account_id: string; account_name: string }[] }>(
      "/api/v1/auth/manual-connect",
      { access_token: accessToken, ad_account_id: adAccountId },
    ),

  /** Automated Rules */
  listRules: (adAccountId: string) =>
    apiClient.get(`/api/v1/rules/${adAccountId}`),
  createKillRule: (data: { ad_account_id: string; campaign_id: string; spend_threshold: number }) =>
    apiClient.post("/api/v1/rules/kill", data),
  createScaleRule: (data: { ad_account_id: string; campaign_id: string; roas_threshold: number; scale_percent: number }) =>
    apiClient.post("/api/v1/rules/scale", data),
  toggleRule: (ruleId: string) =>
    apiClient.patch(`/api/v1/rules/${ruleId}/toggle`),
  deleteRule: (ruleId: string) =>
    apiClient.delete(`/api/v1/rules/${ruleId}`),

  /** Optimization Co-Pilot */
  analyzeOptimizations: (adAccountId?: string) =>
    apiClient.post("/api/v1/optimize/analyze", null, {
      params: adAccountId ? { ad_account_id: adAccountId } : {},
    }),
  analyzeAd: (adId: string, campaignId?: string, adName?: string) =>
    apiClient.post("/api/v1/optimize/analyze/ad", {
      ad_id: adId,
      campaign_id: campaignId,
      ad_name: adName,
    }),
  listProposals: (status: string = "pending") =>
    apiClient.get("/api/v1/optimize/proposals", { params: { status } }),
  updateProposalStatus: (proposalId: string, status: "approved" | "rejected", proposed_value?: Record<string, unknown>) =>
    apiClient.patch(`/api/v1/optimize/proposals/${proposalId}`, { status, ...(proposed_value ? { proposed_value } : {}) }),
  applyProposal: (proposalId: string) =>
    apiClient.post(`/api/v1/optimize/apply/${proposalId}`),
  generateProposalCopy: (proposalId: string) =>
    apiClient.post<{ new_body_text: string; new_headline: string; creative_direction: string }>(`/api/v1/optimize/generate-copy/${proposalId}`),
  applyAllProposals: () =>
    apiClient.post("/api/v1/optimize/apply-all"),
  bridgeAuditDiagnosis: (data: { ad_id: string; ad_name?: string; adset_id?: string; diagnosis: string; campaign_id?: string }) =>
    apiClient.post("/api/v1/optimize/bridge-audit", data),

  /** Audiences */
  uploadCustomers: (data: { customers: { email: string | null; phone: string | null }[]; niche: string; product_id?: string }) =>
    apiClient.post("/api/v1/meta/customers", data),
  getAudienceStats: () =>
    apiClient.get("/api/v1/meta/audience-stats"),
  listAudiences: (productId?: string, audienceType?: string) =>
    apiClient.get("/api/v1/meta/audiences", {
      params: { ...(productId ? { product_id: productId } : {}), ...(audienceType ? { audience_type: audienceType } : {}) },
    }),

  /** Lead Forms — Downloads */
  getLeadFormLeads: (formId: string) =>
    apiClient.get(`/api/v1/lead-forms/${formId}/leads`),
  downloadLeadsCsv: (formId: string) =>
    apiClient.get(`/api/v1/lead-forms/${formId}/leads/csv`, { responseType: "blob" }),
};
