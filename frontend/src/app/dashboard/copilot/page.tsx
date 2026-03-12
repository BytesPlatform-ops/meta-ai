"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Loader2, Sparkles, Check, X, Play, ChevronDown, ChevronUp, TrendingUp, TrendingDown, Pause, Zap, RefreshCw, Scissors, Merge, Shield, Copy, ArrowRightLeft, Users, ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";

type Proposal = {
  id: string;
  entity_id: string;
  entity_type: string;
  entity_name: string;
  action_type: string;
  current_value: Record<string, unknown>;
  proposed_value: Record<string, unknown>;
  ai_reasoning: string;
  impact_score: number;
  status: string;
  applied_at: string | null;
  created_at: string;
};

const ACTION_CONFIG: Record<string, { label: string; color: string; icon: typeof TrendingUp }> = {
  increase_budget: { label: "Increase Budget", color: "text-emerald-400", icon: TrendingUp },
  decrease_budget: { label: "Decrease Budget", color: "text-amber-400", icon: TrendingDown },
  pause: { label: "Pause", color: "text-red-400", icon: Pause },
  enable: { label: "Enable", color: "text-emerald-400", icon: Play },
  reallocate: { label: "Reallocate", color: "text-blue-400", icon: Zap },
  audience_shift: { label: "Audience Shift", color: "text-violet-400", icon: Sparkles },
  custom: { label: "Custom", color: "text-gray-400", icon: Zap },
  refresh_creative: { label: "Refresh Creative", color: "text-orange-400", icon: RefreshCw },
  prune_placements: { label: "Prune Placements", color: "text-rose-400", icon: Scissors },
  consolidate_adsets: { label: "Consolidate Adsets", color: "text-cyan-400", icon: Merge },
  apply_cost_cap: { label: "Apply Cost Cap", color: "text-yellow-400", icon: Shield },
  mutate_winner: { label: "A/B Test Winner", color: "text-indigo-400", icon: Copy },
  shift_budget: { label: "Shift Budget", color: "text-pink-400", icon: ArrowRightLeft },
  create_lookalike: { label: "Create Lookalike", color: "text-teal-400", icon: Users },
};

function ImpactBadge({ score }: { score: number }) {
  const color = score >= 8 ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/20"
    : score >= 5 ? "bg-amber-500/15 text-amber-400 border-amber-500/20"
    : "bg-gray-500/15 text-gray-400 border-gray-500/20";
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${color}`}>
      Impact {score}/10
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: "bg-blue-500/10 text-blue-400",
    approved: "bg-emerald-500/10 text-emerald-400",
    applied: "bg-violet-500/10 text-violet-400",
    rejected: "bg-gray-500/10 text-gray-500",
    failed: "bg-red-500/10 text-red-400",
  };
  return (
    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${styles[status] || styles.pending}`}>
      {status.toUpperCase()}
    </span>
  );
}

const BUDGET_ACTIONS = new Set(["increase_budget", "decrease_budget"]);
const CREATIVE_ACTIONS = new Set(["refresh_creative", "mutate_winner"]);

function ProposalCard({
  proposal,
  onApprove,
  onReject,
  onApply,
}: {
  proposal: Proposal;
  onApprove: (overrideProposedValue?: Record<string, unknown>) => void;
  onReject: () => void;
  onApply: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isBudgetAction = BUDGET_ACTIONS.has(proposal.action_type);
  const isCreativeAction = CREATIVE_ACTIONS.has(proposal.action_type);
  const isShiftBudget = proposal.action_type === "shift_budget";

  // Editable state for budget actions
  const aiDailyBudget = isBudgetAction ? Number(proposal.proposed_value?.daily_budget ?? 0) : 0;
  const [editedBudget, setEditedBudget] = useState<number>(aiDailyBudget);

  // Editable state for creative actions (ad copy textarea)
  const aiBodyText = isCreativeAction ? String(proposal.proposed_value?.new_body_text ?? "") : "";
  const [editedCopy, setEditedCopy] = useState<string>(aiBodyText);

  // Editable state for shift_budget
  const aiShiftAmount = isShiftBudget ? Number(proposal.proposed_value?.amount_display ?? (Number(proposal.proposed_value?.amount_cents ?? 0) / 100)) : 0;
  const [editedShiftAmount, setEditedShiftAmount] = useState<number>(aiShiftAmount);

  const config = ACTION_CONFIG[proposal.action_type] || ACTION_CONFIG.custom;
  const Icon = config.icon;
  const isPending = proposal.status === "pending";
  const isApproved = proposal.status === "approved";

  const handleApprove = () => {
    if (isBudgetAction) {
      onApprove({ ...proposal.proposed_value, daily_budget: editedBudget });
    } else if (isCreativeAction) {
      onApprove({ ...proposal.proposed_value, new_body_text: editedCopy });
    } else if (isShiftBudget) {
      onApprove({
        ...proposal.proposed_value,
        amount_cents: Math.round(editedShiftAmount * 100),
        amount_display: editedShiftAmount,
      });
    } else {
      onApprove();
    }
  };

  return (
    <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-5 hover:bg-white/[0.04] transition-all">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${config.color} bg-white/[0.05]`}>
            <Icon className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-semibold text-white truncate">{proposal.entity_name || proposal.entity_id}</h4>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-xs font-medium ${config.color}`}>{config.label}</span>
              <span className="text-gray-600 text-[10px]">{proposal.entity_type}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <ImpactBadge score={proposal.impact_score} />
          <StatusBadge status={proposal.status} />
        </div>
      </div>

      {/* Reasoning */}
      <p className="text-gray-400 text-xs mt-3 leading-relaxed">{proposal.ai_reasoning}</p>

      {/* --- Interactive Editors --- */}

      {/* Budget editor */}
      {isBudgetAction && isPending && (
        <div className="mt-3 flex items-center gap-3 bg-white/[0.03] rounded-xl px-4 py-2.5 border border-white/[0.06]">
          <span className="text-xs text-gray-500 shrink-0">New Daily Budget</span>
          <div className="flex items-center gap-1">
            <span className="text-sm text-gray-400">$</span>
            <input
              type="number"
              min={1}
              step={0.01}
              value={editedBudget}
              onChange={(e) => setEditedBudget(parseFloat(e.target.value) || 0)}
              className="w-24 bg-white/[0.05] border border-white/[0.1] rounded-lg px-2.5 py-1.5 text-sm text-white font-medium focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 transition-all"
            />
          </div>
          {editedBudget !== aiDailyBudget && (
            <span className="text-[10px] text-amber-400">edited</span>
          )}
        </div>
      )}

      {/* Shift budget editor — Robin Hood */}
      {isShiftBudget && isPending && (
        <div className="mt-3 bg-white/[0.03] rounded-xl p-4 border border-white/[0.06] space-y-2">
          <div className="flex items-center gap-2 text-xs">
            <span className="text-red-400 font-medium truncate max-w-[140px]">{String(proposal.proposed_value?.from_name || proposal.proposed_value?.from_entity)}</span>
            <ArrowRightLeft className="w-3.5 h-3.5 text-pink-400 shrink-0" />
            <span className="text-emerald-400 font-medium truncate max-w-[140px]">{String(proposal.proposed_value?.to_name || proposal.proposed_value?.to_entity)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Move</span>
            <span className="text-sm text-gray-400">$</span>
            <input
              type="number"
              min={1}
              step={1}
              value={editedShiftAmount}
              onChange={(e) => setEditedShiftAmount(parseFloat(e.target.value) || 0)}
              className="w-24 bg-white/[0.05] border border-white/[0.1] rounded-lg px-2.5 py-1.5 text-sm text-white font-medium focus:outline-none focus:border-pink-500/50 focus:ring-1 focus:ring-pink-500/20 transition-all"
            />
            <span className="text-xs text-gray-500">from loser → winner</span>
            {editedShiftAmount !== aiShiftAmount && (
              <span className="text-[10px] text-amber-400">edited</span>
            )}
          </div>
        </div>
      )}

      {/* Creative copy editor — refresh_creative & mutate_winner */}
      {isCreativeAction && isPending && aiBodyText && (
        <div className="mt-3 bg-white/[0.03] rounded-xl p-4 border border-white/[0.06] space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-semibold text-orange-400/70 uppercase tracking-wider">
              {proposal.action_type === "mutate_winner" ? "A/B Variant Copy" : "New Ad Copy"}
            </p>
            {editedCopy !== aiBodyText && (
              <span className="text-[10px] text-amber-400">edited</span>
            )}
          </div>
          <textarea
            value={editedCopy}
            onChange={(e) => setEditedCopy(e.target.value)}
            rows={4}
            className="w-full bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-white leading-relaxed focus:outline-none focus:border-orange-500/50 focus:ring-1 focus:ring-orange-500/20 transition-all resize-none"
          />
          {proposal.proposed_value?.new_cta && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-gray-500">CTA:</span>
              <span className="text-[10px] text-orange-400 font-medium bg-orange-500/10 px-2 py-0.5 rounded-full">
                {String(proposal.proposed_value.new_cta)}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Expandable details */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-[11px] text-gray-600 hover:text-gray-400 mt-2 transition-colors"
      >
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {expanded ? "Hide" : "Show"} details
      </button>

      {expanded && (
        <div className="mt-3 grid grid-cols-2 gap-3">
          <div className="bg-white/[0.02] rounded-xl p-3 border border-white/[0.04]">
            <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wider mb-2">Current</p>
            {Object.entries(proposal.current_value).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5">
                <span className="text-gray-500">{k.replace(/_/g, " ")}</span>
                <span className="text-gray-300 font-medium">{String(v)}</span>
              </div>
            ))}
          </div>
          <div className="bg-white/[0.02] rounded-xl p-3 border border-white/[0.04]">
            <p className="text-[10px] font-semibold text-blue-400/60 uppercase tracking-wider mb-2">Proposed</p>
            {Object.entries(proposal.proposed_value).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5">
                <span className="text-gray-500">{k.replace(/_/g, " ")}</span>
                <span className="text-blue-400 font-medium">
                  {k === "daily_budget" && isBudgetAction ? `$${Number(v).toFixed(2)}`
                    : k === "amount_display" ? `$${Number(v).toFixed(2)}`
                    : k === "new_body_text" ? `${String(v).slice(0, 50)}...`
                    : String(v)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      {(isPending || isApproved) && (
        <div className="flex items-center gap-2 mt-4 pt-3 border-t border-white/[0.04]">
          {isPending && (
            <>
              <button
                onClick={handleApprove}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20 transition-all"
              >
                <Check className="w-3 h-3" />
                {isBudgetAction ? `Approve ($${editedBudget.toFixed(2)})` :
                 isShiftBudget ? `Approve ($${editedShiftAmount.toFixed(2)} shift)` :
                 isCreativeAction ? "Approve Copy" : "Approve"}
              </button>
              <button
                onClick={onReject}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.03] text-gray-500 hover:text-red-400 hover:bg-red-500/10 border border-white/[0.06] transition-all"
              >
                <X className="w-3 h-3" /> Reject
              </button>
            </>
          )}
          {isApproved && (
            <button
              onClick={onApply}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border border-blue-500/20 transition-all"
            >
              <Play className="w-3 h-3" /> Apply Now
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function CoPilotPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const adId = searchParams.get("ad_id");
  const campaignId = searchParams.get("campaign_id");
  const adName = searchParams.get("ad_name");
  const isAdMode = !!adId;

  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");

  const fetchProposals = async () => {
    setLoading(true);
    try {
      const res = await api.listProposals(statusFilter);
      let allProposals = (res as { data: { proposals: Proposal[] } }).data?.proposals || [];
      // In ad mode, filter to show only proposals for this ad
      if (isAdMode) {
        allProposals = allProposals.filter((p) => p.entity_id === adId || p.entity_name === adName);
      }
      setProposals(allProposals);
    } catch {
      /* empty */
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchProposals();
  }, [statusFilter]);

  // Auto-analyze when arriving with ad_id param and no existing proposals
  useEffect(() => {
    if (isAdMode && adId) {
      runAdAnalysis();
    }
  }, [adId]);

  const runAnalysis = async () => {
    setAnalyzing(true);
    try {
      const res = isAdMode && adId
        ? await api.analyzeAd(adId, campaignId || undefined, adName || undefined)
        : await api.analyzeOptimizations();
      const newProposals = (res as { data: { proposals: Proposal[] } }).data?.proposals || [];
      if (newProposals.length > 0) {
        setProposals(newProposals);
        setStatusFilter("pending");
      } else {
        fetchProposals();
      }
    } catch {
      /* empty */
    }
    setAnalyzing(false);
  };

  const runAdAnalysis = async () => {
    if (!adId) return;
    setAnalyzing(true);
    setLoading(true);
    try {
      const res = await api.analyzeAd(adId, campaignId || undefined, adName || undefined);
      const newProposals = (res as { data: { proposals: Proposal[] } }).data?.proposals || [];
      setProposals(newProposals);
      setStatusFilter("pending");
    } catch {
      /* empty */
    }
    setAnalyzing(false);
    setLoading(false);
  };

  const updateStatus = async (id: string, status: "approved" | "rejected", proposedValueOverride?: Record<string, unknown>) => {
    try {
      await api.updateProposalStatus(id, status, proposedValueOverride);
      setProposals((prev) => prev.map((p) => (p.id === id ? {
        ...p,
        status,
        ...(proposedValueOverride ? { proposed_value: proposedValueOverride } : {}),
      } : p)));
    } catch {
      /* empty */
    }
  };

  const applyProposal = async (id: string) => {
    try {
      await api.applyProposal(id);
      setProposals((prev) => prev.map((p) => (p.id === id ? { ...p, status: "applied" } : p)));
    } catch {
      setProposals((prev) => prev.map((p) => (p.id === id ? { ...p, status: "failed" } : p)));
    }
  };

  const applyAll = async () => {
    try {
      await api.applyAllProposals();
      fetchProposals();
    } catch {
      /* empty */
    }
  };

  const approvedCount = proposals.filter((p) => p.status === "approved").length;
  const pendingCount = proposals.filter((p) => p.status === "pending").length;

  const FILTERS = ["all", "pending", "approved", "applied", "rejected", "failed"];

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          {isAdMode && (
            <button
              onClick={() => router.push("/dashboard/copilot")}
              className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 mb-2 transition-colors"
            >
              <ArrowLeft className="w-3 h-3" /> Back to Account Analysis
            </button>
          )}
          <h1 className="text-2xl font-bold text-white">
            <span className="bg-gradient-to-r from-blue-400 to-violet-400 bg-clip-text text-transparent">
              {isAdMode ? "Ad Suggestions" : "AI Co-Pilot"}
            </span>
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            {isAdMode
              ? <>Focused analysis for <span className="text-white font-medium">{adName || adId}</span></>
              : "AI-powered optimization proposals for your ad campaigns."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {approvedCount > 0 && (
            <button
              onClick={applyAll}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20 transition-all"
            >
              <Play className="w-4 h-4" /> Apply All ({approvedCount})
            </button>
          )}
          <button
            onClick={isAdMode ? runAdAnalysis : runAnalysis}
            disabled={analyzing}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-gradient-to-r from-blue-500/20 to-violet-500/20 text-blue-400 hover:from-blue-500/30 hover:to-violet-500/30 border border-blue-500/20 transition-all disabled:opacity-50"
          >
            {analyzing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {analyzing ? "Analyzing..." : isAdMode ? "Re-Analyze Ad" : "Run Analysis"}
          </button>
        </div>
      </div>

      {/* Stats bar */}
      <div className="flex gap-3">
        {FILTERS.map((f) => {
          const count = f === "all" ? proposals.length : proposals.filter((p) => p.status === f).length;
          return (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                statusFilter === f
                  ? "bg-blue-500/20 text-blue-400 shadow-[inset_0_0_0_1px_rgba(59,130,246,0.3)]"
                  : "text-gray-500 hover:text-gray-300 bg-white/[0.03]"
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)} {count > 0 && `(${count})`}
            </button>
          );
        })}
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && proposals.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-gray-500">
          <Sparkles className="w-12 h-12 mb-4 text-gray-700" />
          <p className="text-lg font-medium">No proposals yet</p>
          <p className="text-sm mt-1">Click &quot;Run Analysis&quot; above to have the AI review your campaign performance and generate optimization proposals.</p>
        </div>
      )}

      {/* Proposals grid */}
      {!loading && proposals.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {proposals
            .filter((p) => statusFilter === "all" || p.status === statusFilter)
            .sort((a, b) => b.impact_score - a.impact_score)
            .map((p) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                onApprove={(override) => updateStatus(p.id, "approved", override)}
                onReject={() => updateStatus(p.id, "rejected")}
                onApply={() => applyProposal(p.id)}
              />
            ))}
        </div>
      )}

      {/* Summary footer */}
      {!loading && proposals.length > 0 && (
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4 flex items-center justify-between">
          <div className="flex gap-6 text-xs">
            <div>
              <span className="text-gray-600">Total: </span>
              <span className="text-white font-medium">{proposals.length}</span>
            </div>
            <div>
              <span className="text-gray-600">Pending: </span>
              <span className="text-blue-400 font-medium">{pendingCount}</span>
            </div>
            <div>
              <span className="text-gray-600">Approved: </span>
              <span className="text-emerald-400 font-medium">{approvedCount}</span>
            </div>
            <div>
              <span className="text-gray-600">Applied: </span>
              <span className="text-violet-400 font-medium">{proposals.filter((p) => p.status === "applied").length}</span>
            </div>
          </div>
          <p className="text-[10px] text-gray-600">Proposals are generated from 7-day performance data broken down by age, gender, and placement.</p>
        </div>
      )}
    </div>
  );
}
