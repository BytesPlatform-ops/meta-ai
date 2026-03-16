"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import {
  Zap,
  Shield,
  TrendingUp,
  Loader2,
  Trash2,
  ToggleLeft,
  ToggleRight,
  Plus,
  AlertCircle,
} from "lucide-react";

type Rule = {
  id: string;
  name: string;
  status: string;
  execution_type?: string;
  [key: string]: unknown;
};

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [adAccountId, setAdAccountId] = useState<string | null>(null);
  const [campaigns, setCampaigns] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Kill rule form
  const [killForm, setKillForm] = useState({ campaign_id: "", spend_threshold: "50" });
  const [killSaving, setKillSaving] = useState(false);

  // Scale rule form
  const [scaleForm, setScaleForm] = useState({ campaign_id: "", roas_threshold: "3", scale_percent: "20" });
  const [scaleSaving, setScaleSaving] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      // Get ad accounts
      const { data: accounts } = await api.listAdAccounts();
      if (!accounts?.length) {
        setLoading(false);
        return;
      }
      const accountId = accounts[0].meta_account_id;
      setAdAccountId(accountId);

      // Load rules + campaigns in parallel
      const [rulesRes, campaignsRes] = await Promise.all([
        api.listRules(accountId).catch(() => ({ data: [] })),
        api.listCampaigns(accountId, "active").catch(() => ({ data: { campaigns: [] } })),
      ]);

      // Parse rules (may be text or structured)
      const rulesData = rulesRes.data;
      if (Array.isArray(rulesData)) {
        setRules(rulesData);
      } else if (rulesData?.content?.[0]?.text) {
        try {
          const parsed = JSON.parse(rulesData.content[0].text);
          setRules(Array.isArray(parsed) ? parsed : parsed?.data || []);
        } catch {
          setRules([]);
        }
      } else if (rulesData?.data) {
        setRules(Array.isArray(rulesData.data) ? rulesData.data : []);
      } else {
        setRules([]);
      }

      const c = campaignsRes.data?.campaigns || campaignsRes.data || [];
      setCampaigns(Array.isArray(c) ? c.map((x: { id: string; name: string }) => ({ id: x.id, name: x.name })) : []);
    } catch {
      /* no account */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreateKill = async () => {
    if (!adAccountId || !killForm.campaign_id) return;
    setKillSaving(true);
    setError(null);
    try {
      await api.createKillRule({
        ad_account_id: adAccountId,
        campaign_id: killForm.campaign_id,
        spend_threshold: parseFloat(killForm.spend_threshold),
      });
      setKillForm({ campaign_id: "", spend_threshold: "50" });
      await loadData();
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to create rule");
    } finally {
      setKillSaving(false);
    }
  };

  const handleCreateScale = async () => {
    if (!adAccountId || !scaleForm.campaign_id) return;
    setScaleSaving(true);
    setError(null);
    try {
      await api.createScaleRule({
        ad_account_id: adAccountId,
        campaign_id: scaleForm.campaign_id,
        roas_threshold: parseFloat(scaleForm.roas_threshold),
        scale_percent: parseFloat(scaleForm.scale_percent),
      });
      setScaleForm({ campaign_id: "", roas_threshold: "3", scale_percent: "20" });
      await loadData();
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Failed to create rule");
    } finally {
      setScaleSaving(false);
    }
  };

  const handleToggle = async (ruleId: string) => {
    try {
      await api.toggleRule(ruleId);
      await loadData();
    } catch {
      /* ignore */
    }
  };

  const handleDelete = async (ruleId: string) => {
    try {
      await api.deleteRule(ruleId);
      setRules((prev) => prev.filter((r) => r.id !== ruleId));
    } catch {
      /* ignore */
    }
  };

  const CampaignSelect = ({ value, onChange }: { value: string; onChange: (v: string) => void }) => (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-blue-500/40 transition-all"
    >
      <option value="">Select campaign...</option>
      {campaigns.map((c) => (
        <option key={c.id} value={c.id}>{c.name}</option>
      ))}
    </select>
  );

  return (
    <div className="p-8 w-full animate-fade-in">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-1">
          Automated <span className="gradient-text">Rules</span>
        </h1>
        <p className="text-sm text-gray-500">
          Set up kill and scale rules to automate campaign management.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 mb-6 px-4 py-3 rounded-xl bg-red-500/[0.08] border border-red-500/20 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {!adAccountId && !loading ? (
        <div className="glass rounded-2xl p-12 text-center">
          <Zap className="w-8 h-8 text-gray-600 mx-auto mb-3" />
          <p className="text-gray-400 text-sm">Connect an ad account in Settings to manage rules.</p>
        </div>
      ) : (
        <>
          {/* Create Rules */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
            {/* Kill Rule */}
            <div className="glass rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-xl bg-red-500/10 flex items-center justify-center">
                  <Shield className="w-4 h-4 text-red-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">Kill Rule</h3>
                  <p className="text-[11px] text-gray-500">Pause when spend exceeds threshold</p>
                </div>
              </div>
              <div className="space-y-3">
                <CampaignSelect value={killForm.campaign_id} onChange={(v) => setKillForm((f) => ({ ...f, campaign_id: v }))} />
                <div>
                  <label className="text-xs text-gray-500 mb-1 block">Spend Threshold ($)</label>
                  <input
                    type="number"
                    min="1"
                    value={killForm.spend_threshold}
                    onChange={(e) => setKillForm((f) => ({ ...f, spend_threshold: e.target.value }))}
                    className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-blue-500/40 transition-all"
                  />
                </div>
                <button
                  onClick={handleCreateKill}
                  disabled={!killForm.campaign_id || killSaving}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-all disabled:opacity-50"
                >
                  {killSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                  Create Kill Rule
                </button>
              </div>
            </div>

            {/* Scale Rule */}
            <div className="glass rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-xl bg-emerald-500/10 flex items-center justify-center">
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">Scale Rule</h3>
                  <p className="text-[11px] text-gray-500">Increase budget when ROAS exceeds target</p>
                </div>
              </div>
              <div className="space-y-3">
                <CampaignSelect value={scaleForm.campaign_id} onChange={(v) => setScaleForm((f) => ({ ...f, campaign_id: v }))} />
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">ROAS Threshold</label>
                    <input
                      type="number"
                      min="1"
                      step="0.5"
                      value={scaleForm.roas_threshold}
                      onChange={(e) => setScaleForm((f) => ({ ...f, roas_threshold: e.target.value }))}
                      className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-blue-500/40 transition-all"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 mb-1 block">Budget Increase %</label>
                    <input
                      type="number"
                      min="5"
                      max="100"
                      value={scaleForm.scale_percent}
                      onChange={(e) => setScaleForm((f) => ({ ...f, scale_percent: e.target.value }))}
                      className="w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-blue-500/40 transition-all"
                    />
                  </div>
                </div>
                <button
                  onClick={handleCreateScale}
                  disabled={!scaleForm.campaign_id || scaleSaving}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 transition-all disabled:opacity-50"
                >
                  {scaleSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                  Create Scale Rule
                </button>
              </div>
            </div>
          </div>

          {/* Existing Rules */}
          <div>
            <h2 className="text-sm font-semibold text-gray-300 mb-4">Active Rules</h2>
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-5 h-5 text-gray-600 animate-spin" />
              </div>
            ) : rules.length === 0 ? (
              <div className="glass rounded-2xl p-8 text-center">
                <Zap className="w-6 h-6 text-gray-600 mx-auto mb-2" />
                <p className="text-sm text-gray-500">No rules configured yet. Create one above.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {rules.map((rule) => (
                  <div key={rule.id} className="glass rounded-xl px-5 py-3 flex items-center gap-4">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-medium truncate">{rule.name || rule.id}</p>
                      <p className="text-[11px] text-gray-500">
                        {rule.execution_type || "custom"} &middot; {rule.status}
                      </p>
                    </div>
                    <button
                      onClick={() => handleToggle(rule.id)}
                      className="text-gray-400 hover:text-white transition-colors"
                    >
                      {rule.status === "ENABLED" ? (
                        <ToggleRight className="w-6 h-6 text-emerald-400" />
                      ) : (
                        <ToggleLeft className="w-6 h-6" />
                      )}
                    </button>
                    <button
                      onClick={() => handleDelete(rule.id)}
                      className="text-gray-500 hover:text-red-400 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
