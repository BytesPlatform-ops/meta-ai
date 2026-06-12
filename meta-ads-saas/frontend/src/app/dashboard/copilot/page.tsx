"use client";

import { useEffect, useState, useRef, useMemo } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { Loader2, Sparkles, Check, X, Play, ChevronDown, ChevronUp, TrendingUp, TrendingDown, Pause, Zap, RefreshCw, Scissors, Merge, Shield, Copy, ArrowRightLeft, Users, ArrowLeft, Search, Target, XCircle, PenLine, FilePlus2, CheckSquare } from "lucide-react";
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

type AuditAd = {
  ad_id: string;
  ad_name: string;
  campaign_id?: string;
  spend?: number;
  verdict?: string;
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
  create_engagement_audience: { label: "Retarget Engagers", color: "text-purple-400", icon: Users },
  exclude_demographics: { label: "Exclude Demographics", color: "text-amber-400", icon: Users },
  update_placements: { label: "Update Placements", color: "text-rose-400", icon: Scissors },
  expand_audience: { label: "Expand Audience", color: "text-cyan-400", icon: Users },
  enable_advantage_plus: { label: "Enable Advantage+", color: "text-cyan-400", icon: Zap },
};

function isNewProposal(createdAt: string, newSince: number | null): boolean {
  if (!newSince) return false;
  return new Date(createdAt).getTime() >= newSince;
}

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

function NewBadge() {
  return (
    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 border border-blue-400/30 animate-pulse">
      NEW
    </span>
  );
}

// Actions that create a new ad vs edit existing entity
const CREATES_NEW_AD = new Set(["refresh_creative", "mutate_winner"]);
const ADVISORY_ONLY = new Set(["custom", "audience_shift"]);

function ActionModeBadge({ actionType }: { actionType: string }) {
  if (ADVISORY_ONLY.has(actionType)) {
    return (
      <span className="inline-flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-gray-500/10 text-gray-400 border border-gray-500/15">
        Advisory
      </span>
    );
  }
  if (CREATES_NEW_AD.has(actionType)) {
    return (
      <span className="inline-flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/15">
        <FilePlus2 className="w-2.5 h-2.5" /> New Ad
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/15">
      <PenLine className="w-2.5 h-2.5" /> Edits Existing
    </span>
  );
}

const BUDGET_ACTIONS = new Set(["increase_budget", "decrease_budget"]);
const CREATIVE_ACTIONS = new Set(["refresh_creative", "mutate_winner"]);

function CreativeCopySection({
  proposal,
  editedCopy,
  setEditedCopy,
}: {
  proposal: Proposal;
  editedCopy: string;
  setEditedCopy: (v: string) => void;
}) {
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(!!proposal.proposed_value?.new_body_text);
  const direction = String(proposal.proposed_value?.creative_direction || "");
  const currentHook = String(proposal.proposed_value?.current_hook || "");
  const targetHook = String(proposal.proposed_value?.target_hook || "");
  const bodyText = String(proposal.proposed_value?.new_body_text || "");

  // If proposal already has body text (old-style or already generated), show editor
  useEffect(() => {
    if (bodyText && !editedCopy) {
      setEditedCopy(bodyText);
      setGenerated(true);
    }
  }, [bodyText]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const res = await api.generateProposalCopy(proposal.id);
      const data = (res as { data: { new_body_text: string } }).data;
      if (data?.new_body_text) {
        setEditedCopy(data.new_body_text);
        setGenerated(true);
      }
    } catch {
      /* empty */
    }
    setGenerating(false);
  };

  return (
    <div className="mt-3 bg-white/[0.03] rounded-xl p-4 border border-white/[0.06] space-y-3">
      {/* Creative Direction */}
      {direction && (
        <div>
          <p className="text-[10px] font-semibold text-orange-400/70 uppercase tracking-wider mb-1.5">
            Creative Direction
          </p>
          <p className="text-xs text-gray-300 leading-relaxed">{direction}</p>
          {currentHook && targetHook && (
            <div className="flex items-center gap-2 mt-2">
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-500/10 text-gray-400 border border-gray-500/15">
                {currentHook}
              </span>
              <span className="text-gray-600 text-[10px]">→</span>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-orange-500/10 text-orange-400 border border-orange-500/15">
                {targetHook}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Generate Copy button — only if no body text yet */}
      {!generated && (
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium bg-orange-500/10 text-orange-400 hover:bg-orange-500/20 border border-orange-500/20 transition-all disabled:opacity-50 w-full justify-center"
        >
          {generating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
          {generating ? "Generating copy with product context..." : "Generate Ad Copy"}
        </button>
      )}

      {/* Editable copy — after generation */}
      {generated && editedCopy && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-semibold text-emerald-400/70 uppercase tracking-wider">
              {proposal.action_type === "mutate_winner" ? "A/B Variant Copy" : "New Ad Copy"}
            </p>
            <div className="flex items-center gap-2">
              {proposal.proposed_value?.copy_source === "content_generator" && (
                <span className="text-[9px] text-emerald-400/60">AI-generated with brand context</span>
              )}
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="text-[10px] text-orange-400 hover:text-orange-300 transition-colors disabled:opacity-50"
              >
                {generating ? "Regenerating..." : "Regenerate"}
              </button>
            </div>
          </div>
          <textarea
            value={editedCopy}
            onChange={(e) => setEditedCopy(e.target.value)}
            rows={4}
            className="w-full bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-white leading-relaxed focus:outline-none focus:border-orange-500/50 focus:ring-1 focus:ring-orange-500/20 transition-all resize-none"
          />
        </div>
      )}

      {Boolean(proposal.proposed_value?.new_cta) && (
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-500">CTA:</span>
          <span className="text-[10px] text-orange-400 font-medium bg-orange-500/10 px-2 py-0.5 rounded-full">
            {String(proposal.proposed_value.new_cta)}
          </span>
        </div>
      )}
    </div>
  );
}

function ProposalCard({
  proposal,
  isNew,
  selected,
  onToggleSelect,
  onApprove,
  onReject,
  onApply,
}: {
  proposal: Proposal;
  isNew: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  onApprove: (overrideProposedValue?: Record<string, unknown>) => void;
  onReject: () => void;
  onApply: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isBudgetAction = BUDGET_ACTIONS.has(proposal.action_type);
  const isCreativeAction = CREATIVE_ACTIONS.has(proposal.action_type);
  const isShiftBudget = proposal.action_type === "shift_budget";

  // Editable state for budget actions
  const rawBudget = isBudgetAction ? parseFloat(String(proposal.proposed_value?.daily_budget ?? "0").replace(/[^0-9.]/g, "")) : 0;
  const aiDailyBudget = isNaN(rawBudget) ? 0 : rawBudget;
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
    <div className={`bg-white/[0.02] border rounded-2xl p-5 hover:bg-white/[0.04] transition-all ${selected ? "border-blue-500/40 ring-1 ring-blue-500/20" : isNew ? "border-blue-500/30 ring-1 ring-blue-500/10" : "border-white/[0.06]"}`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {/* Selection checkbox — only for pending proposals */}
          {isPending && (
            <button
              onClick={(e) => { e.stopPropagation(); onToggleSelect(); }}
              className={`w-5 h-5 rounded-md border-2 flex items-center justify-center shrink-0 transition-all ${selected ? "bg-blue-500 border-blue-500" : "border-white/20 hover:border-blue-400/50"}`}
            >
              {selected && <Check className="w-3 h-3 text-white" />}
            </button>
          )}
          <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${config.color} bg-white/[0.05]`}>
            <Icon className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h4 className="text-sm font-semibold text-white truncate">{proposal.entity_name || proposal.entity_id}</h4>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-xs font-medium ${config.color}`}>{config.label}</span>
              <span className="text-gray-600 text-[10px]">{proposal.entity_type}</span>
              <ActionModeBadge actionType={proposal.action_type} />
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isNew && <NewBadge />}
          <ImpactBadge score={proposal.impact_score} />
          <StatusBadge status={proposal.status} />
        </div>
      </div>

      {/* Reasoning */}
      <p className="text-gray-400 text-xs mt-3 leading-relaxed">{proposal.ai_reasoning}</p>

      {/* Learning phase reset warning for placement changes */}
      {["update_placements", "prune_placements", "enable_advantage_plus"].includes(proposal.action_type) && isPending && (
        <div className="mt-2 flex items-start gap-2 bg-amber-500/5 border border-amber-500/15 rounded-lg px-3 py-2">
          <span className="text-amber-400 text-sm mt-0.5">⚠</span>
          <p className="text-[10px] text-amber-400/80 leading-relaxed">
            <span className="font-semibold">Learning Phase Reset:</span> Changing placements resets Meta&apos;s learning phase for 3-7 days. CPA may temporarily increase due to the breakdown effect — Meta optimizes placement distribution based on predicted future performance, not past data.
          </p>
        </div>
      )}

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

      {/* Creative direction + copy generation — refresh_creative & mutate_winner */}
      {isCreativeAction && isPending && (
        <CreativeCopySection proposal={proposal} editedCopy={editedCopy} setEditedCopy={setEditedCopy} />
      )}

      {/* Demographics editor */}
      {proposal.action_type === "exclude_demographics" && isPending && (
        <div className="mt-3 bg-white/[0.03] rounded-xl px-4 py-3 border border-white/[0.06]">
          <span className="text-xs text-gray-500 block mb-2">Demographic Change</span>
          <div className="flex items-center gap-3 flex-wrap">
            {proposal.proposed_value?.age_min != null && proposal.proposed_value?.age_max != null && (
              <span className="text-sm text-white px-2 py-0.5 rounded-full bg-amber-500/10">Age: {String(proposal.proposed_value.age_min)}–{String(proposal.proposed_value.age_max)}</span>
            )}
            {proposal.proposed_value?.genders && (
              <span className="text-sm text-white px-2 py-0.5 rounded-full bg-blue-500/10">
                Gender: {(proposal.proposed_value.genders as number[]).map((g: number) => g === 1 ? "Male" : "Female").join(", ")}
              </span>
            )}
          </div>
          {proposal.proposed_value?.excluded_segments && (
            <p className="text-[11px] text-amber-400/80 mt-2 leading-relaxed">{String(proposal.proposed_value.excluded_segments)}</p>
          )}
        </div>
      )}

      {/* Placements editor */}
      {proposal.action_type === "update_placements" && isPending && (
        <div className="mt-3 bg-white/[0.03] rounded-xl px-4 py-3 border border-white/[0.06]">
          <span className="text-xs text-gray-500 block mb-2">Placement Change</span>
          <div className="flex items-center gap-2 flex-wrap">
            {(proposal.proposed_value?.publisher_platforms as string[] || []).map((p: string) => (
              <span key={p} className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 text-xs">{p}</span>
            ))}
            {(proposal.proposed_value?.facebook_positions as string[] || []).map((p: string) => (
              <span key={`fb-${p}`} className="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 text-xs">FB {p}</span>
            ))}
            {(proposal.proposed_value?.instagram_positions as string[] || []).map((p: string) => (
              <span key={`ig-${p}`} className="px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 text-xs">IG {p}</span>
            ))}
          </div>
          {proposal.proposed_value?.removed_placements && (
            <p className="text-[11px] text-red-400/80 mt-2">Removing: {String(proposal.proposed_value.removed_placements)}</p>
          )}
        </div>
      )}

      {/* Audience expansion */}
      {proposal.action_type === "expand_audience" && isPending && (
        <div className="mt-3 bg-white/[0.03] rounded-xl px-4 py-3 border border-white/[0.06]">
          <span className="text-xs text-gray-500 block mb-2">Audience Expansion</span>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 text-xs">Advantage+ Audience</span>
            <span className="text-[11px] text-gray-400">Enable Meta to find users beyond your interest targeting</span>
          </div>
          {proposal.proposed_value?.reason && (
            <p className="text-[11px] text-cyan-400/80 mt-2">{String(proposal.proposed_value.reason)}</p>
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
            {Object.entries(proposal.current_value).filter(([, v]) => typeof v !== "object" || v === null).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5">
                <span className="text-gray-500">{k.replace(/_/g, " ")}</span>
                <span className="text-gray-300 font-medium">{String(v)}</span>
              </div>
            ))}
          </div>
          <div className="bg-white/[0.02] rounded-xl p-3 border border-white/[0.04]">
            <p className="text-[10px] font-semibold text-blue-400/60 uppercase tracking-wider mb-2">Proposed</p>
            {Object.entries(proposal.proposed_value).filter(([, v]) => typeof v !== "object" || v === null).map(([k, v]) => (
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
                 isCreativeAction ? "Approve Copy" :
                 proposal.action_type === "exclude_demographics" ? "Apply Demographics" :
                 proposal.action_type === "update_placements" ? "Apply Placements" :
                 proposal.action_type === "expand_audience" ? "Expand Audience" : "Approve"}
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

// ── Targeted Analysis Combobox ──────────────────────────────────────────────

function AdSearchCombobox({
  ads,
  loading,
  onSelect,
}: {
  ads: AuditAd[];
  loading: boolean;
  onSelect: (ad: AuditAd) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = useMemo(() => {
    if (!query.trim()) return ads;
    const q = query.toLowerCase();
    return ads.filter((a) => a.ad_name.toLowerCase().includes(q) || a.ad_id.includes(q));
  }, [ads, query]);

  return (
    <div ref={ref} className="relative flex-1 max-w-sm">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
        <input
          type="text"
          placeholder={loading ? "Loading ads..." : "Search ads by name or ID..."}
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          disabled={loading}
          className="w-full pl-9 pr-3 py-2 bg-white/[0.04] border border-white/[0.08] rounded-xl text-xs text-white placeholder-gray-600 focus:outline-none focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/20 transition-all disabled:opacity-50"
        />
      </div>
      {open && filtered.length > 0 && (
        <div className="absolute z-50 mt-1 w-full max-h-60 overflow-y-auto bg-[#1a1a2e] border border-white/[0.08] rounded-xl shadow-2xl">
          {filtered.map((ad) => (
            <button
              key={ad.ad_id}
              onClick={() => { onSelect(ad); setQuery(ad.ad_name); setOpen(false); }}
              className="w-full text-left px-4 py-2.5 hover:bg-white/[0.06] transition-colors border-b border-white/[0.04] last:border-0"
            >
              <p className="text-xs text-white font-medium truncate">{ad.ad_name}</p>
              <p className="text-[10px] text-gray-500 mt-0.5">
                ID: {ad.ad_id}
                {ad.spend != null && <span className="ml-2">Spend: ${ad.spend.toFixed(0)}</span>}
                {ad.verdict && <span className={`ml-2 capitalize ${ad.verdict === "scale" ? "text-emerald-400" : ad.verdict === "kill" ? "text-red-400" : "text-amber-400"}`}>{ad.verdict}</span>}
              </p>
            </button>
          ))}
        </div>
      )}
      {open && !loading && filtered.length === 0 && query.trim() && (
        <div className="absolute z-50 mt-1 w-full bg-[#1a1a2e] border border-white/[0.08] rounded-xl shadow-2xl px-4 py-3">
          <p className="text-xs text-gray-500">No ads match &quot;{query}&quot;</p>
        </div>
      )}
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

export default function CoPilotPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // URL params
  const adId = searchParams.get("ad_id");
  const campaignId = searchParams.get("campaign_id");
  const adName = searchParams.get("ad_name");
  const filterAdId = searchParams.get("filter_ad_id");
  const generatedAt = searchParams.get("_t"); // timestamp from Fix/Suggestions navigation
  const isAdMode = !!adId;

  // State
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [campaignFilter, setCampaignFilter] = useState<string>("all");

  // Track when new proposals were generated (from URL _t param or local analysis)
  const [newSince, setNewSince] = useState<number | null>(
    generatedAt ? parseInt(generatedAt, 10) - 30000 : null // 30s buffer for server processing
  );

  // Multi-select state for batch operations
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Ad filter state (from filter_ad_id param or targeted analysis)
  const [adFilter, setAdFilter] = useState<string | null>(filterAdId);
  const [adFilterName, setAdFilterName] = useState<string | null>(
    filterAdId ? (adName || null) : null
  );

  // Targeted analysis state
  const [auditAds, setAuditAds] = useState<AuditAd[]>([]);
  const [auditAdsLoading, setAuditAdsLoading] = useState(false);
  const [selectedAd, setSelectedAd] = useState<AuditAd | null>(null);
  const [targetedAnalyzing, setTargetedAnalyzing] = useState(false);

  // Fetch ad list from latest audit on mount
  useEffect(() => {
    const loadAuditAds = async () => {
      setAuditAdsLoading(true);
      try {
        const res = await api.getLatestAudit();
        const audit = (res as { data: Record<string, unknown> }).data;
        if (audit) {
          // winning_ads contains ALL evaluated ads (the naming is legacy)
          let allAds: AuditAd[] = [];
          const winningRaw = audit.winning_ads;
          if (typeof winningRaw === "string") {
            try { allAds = JSON.parse(winningRaw); } catch { /* empty */ }
          } else if (Array.isArray(winningRaw)) {
            allAds = winningRaw as AuditAd[];
          }
          setAuditAds(allAds.filter((a) => a.ad_id && a.ad_name));
        }
      } catch {
        /* empty — audit may not exist yet */
      }
      setAuditAdsLoading(false);
    };
    loadAuditAds();
  }, []);

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

  useAutoRefresh(fetchProposals);

  // Auto-analyze when arriving with ad_id param and no existing proposals
  useEffect(() => {
    if (isAdMode && adId) {
      runAdAnalysis();
    }
  }, [adId]);

  const runAnalysis = async () => {
    setAnalyzing(true);
    setError(null);
    const analysisStart = Date.now() - 5000; // 5s buffer
    try {
      const res = isAdMode && adId
        ? await api.analyzeAd(adId, campaignId || undefined, adName || undefined)
        : await api.analyzeOptimizations();
      const newProposals = (res as { data: { proposals: Proposal[] } }).data?.proposals || [];
      setNewSince(analysisStart);
      if (newProposals.length > 0) {
        setProposals(newProposals);
        setStatusFilter("pending");
      } else {
        fetchProposals();
      }
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Analysis failed. Check your ad account connection.");
    }
    setAnalyzing(false);
  };

  const runAdAnalysis = async () => {
    if (!adId) return;
    setAnalyzing(true);
    setLoading(true);
    const analysisStart = Date.now() - 5000;
    try {
      const res = await api.analyzeAd(adId, campaignId || undefined, adName || undefined);
      const newProposals = (res as { data: { proposals: Proposal[] } }).data?.proposals || [];
      setNewSince(analysisStart);
      setProposals(newProposals);
      setStatusFilter("pending");
    } catch {
      /* empty */
    }
    setAnalyzing(false);
    setLoading(false);
  };

  // Targeted analysis for a specific ad from the combobox
  const runTargetedAnalysis = async () => {
    if (!selectedAd) return;
    setTargetedAnalyzing(true);
    setError(null);
    const analysisStart = Date.now() - 5000;
    try {
      const res = await api.analyzeAd(selectedAd.ad_id, selectedAd.campaign_id || undefined, selectedAd.ad_name);
      const newProposals = (res as { data: { proposals: Proposal[] } }).data?.proposals || [];
      setNewSince(analysisStart);
      if (newProposals.length > 0) {
        // Merge new proposals into existing list (avoid duplicates by id)
        setProposals((prev) => {
          const existingIds = new Set(prev.map((p) => p.id));
          const fresh = newProposals.filter((p: Proposal) => !existingIds.has(p.id));
          return [...fresh, ...prev];
        });
        setStatusFilter("all");
      }
      // Auto-set filter to this ad
      setAdFilter(selectedAd.ad_id);
      setAdFilterName(selectedAd.ad_name);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "Targeted analysis failed.");
    }
    setTargetedAnalyzing(false);
  };

  const clearAdFilter = () => {
    setAdFilter(null);
    setAdFilterName(null);
    setSelectedAd(null);
    // Remove filter_ad_id from URL without full reload
    router.replace("/dashboard/copilot", { scroll: false });
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

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const selectAllPending = () => {
    const pendingIds = displayedProposals.filter((p) => p.status === "pending").map((p) => p.id);
    setSelectedIds((prev) => {
      const allSelected = pendingIds.every((id) => prev.has(id));
      if (allSelected) return new Set(); // deselect all
      return new Set(pendingIds);
    });
  };

  const [batchApplying, setBatchApplying] = useState(false);

  const applySelected = async () => {
    if (selectedIds.size === 0) return;
    setBatchApplying(true);
    // First approve all selected, then apply them sequentially
    for (const id of selectedIds) {
      const p = proposals.find((pr) => pr.id === id);
      if (!p || p.status === "rejected" || p.status === "applied") continue;
      try {
        // Approve if pending
        if (p.status === "pending") {
          await api.updateProposalStatus(id, "approved");
        }
        // Apply
        await api.applyProposal(id);
        setProposals((prev) => prev.map((pr) => (pr.id === id ? { ...pr, status: "applied" } : pr)));
      } catch {
        setProposals((prev) => prev.map((pr) => (pr.id === id ? { ...pr, status: "failed" } : pr)));
      }
    }
    setSelectedIds(new Set());
    setBatchApplying(false);
  };

  // Apply all filters: status, campaign, and ad filter
  const displayedProposals = useMemo(() => {
    return proposals
      .filter((p) => statusFilter === "all" || p.status === statusFilter)
      .filter((p) => campaignFilter === "all" || p.entity_name === campaignFilter)
      .filter((p) => !adFilter || p.entity_id === adFilter || p.entity_name === adFilterName)
      .sort((a, b) => {
        // New proposals float to top
        const aNew = isNewProposal(a.created_at, newSince) ? 1 : 0;
        const bNew = isNewProposal(b.created_at, newSince) ? 1 : 0;
        if (aNew !== bNew) return bNew - aNew;
        return b.impact_score - a.impact_score;
      });
  }, [proposals, statusFilter, campaignFilter, adFilter, adFilterName, newSince]);

  const approvedCount = proposals.filter((p) => p.status === "approved").length;
  const pendingCount = proposals.filter((p) => p.status === "pending").length;
  const filteredCount = adFilter ? displayedProposals.length : null;

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

      {/* ── Targeted Analysis Section ─────────────────────────────── */}
      {!isAdMode && (
        <div className="bg-white/[0.02] border border-white/[0.06] rounded-2xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Target className="w-4 h-4 text-violet-400" />
            <h3 className="text-sm font-semibold text-white">Targeted Analysis</h3>
            <span className="text-[10px] text-gray-600">Analyze a specific ad</span>
          </div>
          <div className="flex items-center gap-3">
            <AdSearchCombobox
              ads={auditAds}
              loading={auditAdsLoading}
              onSelect={(ad) => setSelectedAd(ad)}
            />
            <button
              onClick={runTargetedAnalysis}
              disabled={!selectedAd || targetedAnalyzing}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium bg-violet-500/10 text-violet-400 hover:bg-violet-500/20 border border-violet-500/20 transition-all disabled:opacity-40 shrink-0"
            >
              {targetedAnalyzing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
              {targetedAnalyzing ? "Analyzing..." : "Run Specific Analysis"}
            </button>
          </div>
        </div>
      )}

      {/* ── Active Ad Filter Banner ───────────────────────────────── */}
      {adFilter && !isAdMode && (
        <div className="flex items-center gap-3 bg-violet-500/10 border border-violet-500/20 rounded-xl px-4 py-2.5">
          <Target className="w-4 h-4 text-violet-400 shrink-0" />
          <p className="text-xs text-violet-300 flex-1">
            Showing proposals for: <span className="text-white font-semibold">{adFilterName || adFilter}</span>
            {filteredCount !== null && <span className="text-violet-400 ml-1">({filteredCount} found)</span>}
          </p>
          <button
            onClick={clearAdFilter}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium text-violet-400 hover:text-white hover:bg-violet-500/20 border border-violet-500/20 transition-all"
          >
            <XCircle className="w-3 h-3" /> Clear Filter
          </button>
        </div>
      )}

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

      {/* Campaign filter — only in account mode (not ad mode) and no ad filter active */}
      {!isAdMode && !adFilter && proposals.length > 0 && (() => {
        const entityNames = Array.from(new Set(proposals.map((p: Proposal) => p.entity_name).filter(Boolean))) as string[];
        if (entityNames.length <= 1) return null;
        return (
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">Filter by:</span>
            <select
              value={campaignFilter}
              onChange={(e) => setCampaignFilter(e.target.value)}
              className="bg-white/[0.04] border border-white/[0.08] rounded-lg px-3 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-blue-500/50 transition-all"
            >
              <option value="all">All entities</option>
              {entityNames.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </div>
        );
      })()}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-24">
          <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && displayedProposals.length === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-gray-500">
          <Sparkles className="w-12 h-12 mb-4 text-gray-700" />
          {error ? (
            <>
              <p className="text-lg font-medium text-red-400">Analysis Failed</p>
              <p className="text-sm mt-1 text-red-400/80">{error}</p>
            </>
          ) : adFilter ? (
            <>
              <p className="text-lg font-medium">No proposals for this ad</p>
              <p className="text-sm mt-1">Try running a targeted analysis above, or <button onClick={clearAdFilter} className="text-violet-400 hover:underline">clear the filter</button> to see all proposals.</p>
            </>
          ) : (
            <>
              <p className="text-lg font-medium">No proposals yet</p>
              <p className="text-sm mt-1">Click &quot;Run Analysis&quot; above to have the AI review your campaign performance and generate optimization proposals.</p>
            </>
          )}
        </div>
      )}

      {/* ── Batch Action Bar ──────────────────────────────────────── */}
      {!loading && displayedProposals.length > 0 && displayedProposals.some((p) => p.status === "pending") && (
        <div className="flex items-center justify-between bg-white/[0.02] border border-white/[0.06] rounded-xl px-4 py-2.5">
          <div className="flex items-center gap-3">
            <button
              onClick={selectAllPending}
              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white transition-colors"
            >
              <CheckSquare className="w-3.5 h-3.5" />
              {selectedIds.size > 0 && selectedIds.size === displayedProposals.filter((p) => p.status === "pending").length
                ? "Deselect All"
                : "Select All Pending"}
            </button>
            {selectedIds.size > 0 && (
              <span className="text-[10px] text-blue-400 font-medium">
                {selectedIds.size} selected
              </span>
            )}
          </div>
          {selectedIds.size > 0 && (
            <button
              onClick={applySelected}
              disabled={batchApplying}
              className="flex items-center gap-2 px-4 py-1.5 rounded-xl text-xs font-medium bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border border-blue-500/20 transition-all disabled:opacity-50"
            >
              {batchApplying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              {batchApplying ? "Applying..." : `Approve & Apply Selected (${selectedIds.size})`}
            </button>
          )}
        </div>
      )}

      {/* Proposals grid */}
      {!loading && displayedProposals.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {displayedProposals.map((p) => (
              <ProposalCard
                key={p.id}
                proposal={p}
                isNew={isNewProposal(p.created_at, newSince)}
                selected={selectedIds.has(p.id)}
                onToggleSelect={() => toggleSelect(p.id)}
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
