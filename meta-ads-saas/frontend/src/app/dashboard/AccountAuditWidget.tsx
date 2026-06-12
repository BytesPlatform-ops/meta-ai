"use client";

import { useEffect, useState } from "react";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import {
  Activity,
  DollarSign,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  AlertCircle,
  Loader2,
  Trophy,
  ThumbsDown,
  Sparkles,
  BarChart3,
  ChevronDown,
  ChevronRight,
  Zap,
  Target,
  PauseCircle,
  ArrowRightLeft,
  Lightbulb,
  CheckCircle2,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import { api } from "@/lib/api";

interface AuditAd {
  ad_name: string;
  ad_id?: string;
  spend: number;
  roas: number | null;
  purchases: number;
  leads: number;
  results: number;
  result_type: string;
  ctr: number;
  cpc?: number;
  cpm?: number;
  frequency?: number;
  cost_per_purchase?: number | null;
  cost_per_lead?: number | null;
  cost_per_result?: number | null;
  score?: number;
  verdict?: string;
  components?: { creative: number; efficiency: number; health: number; maturity: number };
  days_running?: number | null;
  is_learning?: boolean;
  diagnosis?: string;
  campaign_id?: string;
}

interface Demographics {
  age_groups?: Record<string, number>;
  gender?: Record<string, number>;
}

interface Baselines {
  avg_cpl: number | null;
  avg_cpa: number | null;
  avg_roas: number | null;
  avg_ctr: number;
  avg_cpc: number;
  avg_cpm: number;
  total_spend: number;
  total_leads: number;
  total_purchases: number;
  dominant_type: string;
  sample_size: number;
  source: string;
  win_threshold: number | null;
  lose_threshold: number | null;
}

interface Audit {
  id: string;
  status: string;
  total_spend: number | null;
  roas: number | null;
  winning_ads: AuditAd[] | string;
  losing_ads: AuditAd[] | string;
  ai_strategy_report: string | null;
  audience_demographics: Demographics | string | null;
  tone_recommendation: string | null;
  baselines: Baselines | string | null;
  error_message: string | null;
  created_at: string;
}

function parseAds(ads: AuditAd[] | string): AuditAd[] {
  if (typeof ads === "string") {
    try { return JSON.parse(ads); } catch { return []; }
  }
  return ads || [];
}

function formatMd(text: string): string {
  // Split into sections by double newline or header patterns
  const lines = text.split("\n");
  let html = "";
  let inList = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    if (!line) {
      if (inList) { html += "</ul>"; inList = false; }
      continue;
    }

    // Markdown headers
    if (line.startsWith("### ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h4 class="text-white font-semibold text-sm mt-5 mb-2 flex items-center gap-2"><span class="w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0"></span>${applyInline(line.slice(4))}</h4>`;
    } else if (line.startsWith("## ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h3 class="text-white font-semibold text-base mt-6 mb-2">${applyInline(line.slice(3))}</h3>`;
    } else if (line.startsWith("# ")) {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<h2 class="text-white font-bold text-lg mt-6 mb-3">${applyInline(line.slice(2))}</h2>`;
    }
    // Section-style headers: "Title:" or "Title" followed by content on next line
    else if (/^[A-Z][\w\s/&]+:/.test(line) && !line.startsWith("-") && !line.startsWith("*")) {
      if (inList) { html += "</ul>"; inList = false; }
      const colonIdx = line.indexOf(":");
      const title = line.slice(0, colonIdx);
      const rest = line.slice(colonIdx + 1).trim();
      html += `<div class="mt-5 mb-2 px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">`;
      html += `<h4 class="text-white font-semibold text-sm mb-1">${applyInline(title)}</h4>`;
      if (rest) html += `<p class="text-sm text-gray-300 leading-relaxed">${applyInline(rest)}</p>`;
      html += `</div>`;
    }
    // Bullet points (- or *)
    else if (/^[-*] /.test(line)) {
      if (!inList) { html += '<ul class="space-y-1.5 my-2">'; inList = true; }
      html += `<li class="flex items-start gap-2 text-sm text-gray-300"><span class="w-1 h-1 rounded-full bg-gray-500 mt-2 shrink-0"></span><span>${applyInline(line.slice(2))}</span></li>`;
    }
    // Numbered list
    else if (/^\d+\.\s/.test(line)) {
      if (!inList) { html += '<ol class="space-y-2 my-2">'; inList = true; }
      const match = line.match(/^(\d+)\.\s(.+)/);
      if (match) {
        html += `<li class="flex items-start gap-3 text-sm text-gray-300"><span class="w-5 h-5 rounded-lg bg-blue-500/10 text-blue-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">${match[1]}</span><span>${applyInline(match[2])}</span></li>`;
      }
    }
    // Plain paragraph
    else {
      if (inList) { html += "</ul>"; inList = false; }
      html += `<p class="text-sm text-gray-300 leading-relaxed my-1.5">${applyInline(line)}</p>`;
    }
  }

  if (inList) html += "</ul>";
  return html;
}

function applyInline(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-medium">$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>');
}

function parseDemographics(d: Demographics | string | null): Demographics | null {
  if (!d) return null;
  if (typeof d === "string") {
    try { return JSON.parse(d); } catch { return null; }
  }
  return d;
}

function parseBaselines(b: Baselines | string | null): Baselines | null {
  if (!b) return null;
  if (typeof b === "string") {
    try { return JSON.parse(b); } catch { return null; }
  }
  return b;
}

function DemoBar({ label, pct }: { label: string; pct: number }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-14 text-gray-500 text-right shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-white/[0.04] rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-blue-500 to-violet-500 rounded-full"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className="w-10 text-gray-400 text-right">{pct.toFixed(1)}%</span>
    </div>
  );
}

/* ── Strategy Report — Visual renderer ─────────────────────────────── */

interface ReportSection {
  title: string;
  content: string;
  type: "health" | "winners" | "losers" | "budget" | "quick" | "strategy" | "general";
}

function parseReport(raw: string): { healthScore: number | null; healthReason: string; sections: ReportSection[] } {
  const lines = raw.split("\n");
  let healthScore: number | null = null;
  let healthReason = "";
  const sections: ReportSection[] = [];
  let currentTitle = "";
  let currentLines: string[] = [];
  let currentType: ReportSection["type"] = "general";

  const detectType = (title: string): ReportSection["type"] => {
    const t = title.toLowerCase();
    if (t.includes("health") || t.includes("score")) return "health";
    if (t.includes("top") || t.includes("winning") || t.includes("work")) return "winners";
    if (t.includes("under") || t.includes("losing") || t.includes("diagnos")) return "losers";
    if (t.includes("budget") || t.includes("realloc")) return "budget";
    if (t.includes("quick") || t.includes("checklist") || t.includes("start now") || t.includes("micro")) return "quick";
    if (t.includes("strateg") || t.includes("recommend") || t.includes("long")) return "strategy";
    return "general";
  };

  const flush = () => {
    if (currentTitle && currentLines.length > 0) {
      sections.push({ title: currentTitle, content: currentLines.join("\n").trim(), type: currentType });
    }
    currentLines = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();

    // Detect numbered section headers like "1) ...", "## ...", "**...**"
    const numMatch = trimmed.match(/^(\d+)\)\s+(.+)/);
    const headerMatch = trimmed.match(/^#{1,3}\s+(.+)/);
    const boldHeaderMatch = trimmed.match(/^\*\*(\d+)\)\s*(.+?)\*\*/);

    if (numMatch || headerMatch || boldHeaderMatch) {
      flush();
      const title = numMatch ? numMatch[2] : headerMatch ? headerMatch[1] : boldHeaderMatch ? `${boldHeaderMatch[1]}) ${boldHeaderMatch[2]}` : trimmed;
      currentTitle = title.replace(/\*\*/g, "").replace(/:$/, "").trim();
      currentType = detectType(currentTitle);

      // Extract health score
      if (currentType === "health") {
        const scoreMatch = raw.match(/(\d+)\s*\/\s*10/);
        if (scoreMatch) healthScore = parseInt(scoreMatch[1]);
        const whyMatch = trimmed.match(/[Ww]hy:?\s*(.+)/);
        if (whyMatch) healthReason = whyMatch[1];
      }
    } else if (trimmed) {
      // Check if this line has the "Why:" for health section inline
      if (currentType === "health" && trimmed.toLowerCase().startsWith("why")) {
        healthReason = trimmed.replace(/^[Ww]hy:?\s*/, "");
      }
      currentLines.push(line);
    } else {
      currentLines.push("");
    }
  }
  flush();

  return { healthScore, healthReason, sections };
}

function CollapsibleSection({ section, defaultOpen = false }: { section: ReportSection; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);

  const iconMap: Record<ReportSection["type"], any> = {
    health: Sparkles,
    winners: Trophy,
    losers: AlertTriangle,
    budget: ArrowRightLeft,
    quick: Zap,
    strategy: Target,
    general: Lightbulb,
  };

  const colorMap: Record<ReportSection["type"], { bg: string; text: string; border: string }> = {
    health: { bg: "bg-blue-500/10", text: "text-blue-400", border: "border-blue-500/20" },
    winners: { bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/20" },
    losers: { bg: "bg-red-500/10", text: "text-red-400", border: "border-red-500/20" },
    budget: { bg: "bg-violet-500/10", text: "text-violet-400", border: "border-violet-500/20" },
    quick: { bg: "bg-amber-500/10", text: "text-amber-400", border: "border-amber-500/20" },
    strategy: { bg: "bg-cyan-500/10", text: "text-cyan-400", border: "border-cyan-500/20" },
    general: { bg: "bg-gray-500/10", text: "text-gray-400", border: "border-gray-500/20" },
  };

  const Icon = iconMap[section.type];
  const colors = colorMap[section.type];

  // Parse content into structured blocks: sub-headings become cards, bullets become lists
  const renderContent = (text: string) => {
    const lines = text.split("\n");
    const blocks: any[] = [];
    let key = 0;
    let currentCard: { heading: string; lines: string[] } | null = null;

    const formatLine = (t: string) => {
      const parts = t.split(/(\*\*.*?\*\*)/g);
      return parts.map((p: string, i: number) => {
        if (p.startsWith("**") && p.endsWith("**")) {
          return <strong key={i} className="text-white font-medium">{p.slice(2, -2)}</strong>;
        }
        // Highlight metrics: $numbers, percentages, CPL/ROAS values
        const highlighted = p.replace(
          /(\$[\d,.]+|\d+\.?\d*%|\d+\.?\d*x\b|CPL\s*[\d$.]+|ROAS\s*[\d.]+)/gi,
          '##METRIC##$1##END##'
        );
        if (highlighted.includes('##METRIC##')) {
          return highlighted.split(/(##METRIC##.*?##END##)/g).map((seg: string, j: number) => {
            if (seg.startsWith('##METRIC##')) {
              const val = seg.replace('##METRIC##', '').replace('##END##', '');
              return <span key={`${i}-${j}`} className={`font-semibold ${colors.text}`}>{val}</span>;
            }
            return seg;
          });
        }
        return p;
      });
    };

    const flushCard = () => {
      if (currentCard) {
        blocks.push(
          <div key={key++} className={`rounded-xl bg-white/[0.02] border border-white/[0.05] p-3.5 space-y-1.5`}>
            <p className={`text-[13px] font-semibold ${colors.text}`}>{currentCard.heading}</p>
            {currentCard.lines.map((l, li) => (
              <p key={li} className="text-[12px] text-gray-400 leading-relaxed">{formatLine(l)}</p>
            ))}
          </div>
        );
        currentCard = null;
      }
    };

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;

      // Detect ad-name-style sub-headers: "Web Lead OTP (CPL 7.79; CTR 3.74)" or "Tracking & Data:" style
      const isSubHeader = (
        (/^[A-Z][\w\s]+\(/.test(trimmed) && trimmed.includes(")")) ||
        (/^[A-Z][\w\s/&,]+:\s*$/.test(trimmed)) ||
        (/^[A-Z][\w\s]+\s+—\s+/.test(trimmed) && trimmed.length < 80)
      );

      if (isSubHeader) {
        flushCard();
        currentCard = { heading: trimmed.replace(/:\s*$/, ""), lines: [] };
      } else if (currentCard) {
        currentCard.lines.push(trimmed.replace(/^[-*•]\s*/, ""));
      } else if (/^[-*•]\s/.test(trimmed)) {
        blocks.push(
          <div key={key++} className="flex items-start gap-2.5 py-0.5">
            <span className={`w-1.5 h-1.5 rounded-full mt-[7px] shrink-0 ${colors.bg.replace("/10", "/50")}`} />
            <span className="text-[12px] text-gray-400 leading-relaxed">{formatLine(trimmed.slice(2))}</span>
          </div>
        );
      } else if (/^\d+\)\s/.test(trimmed)) {
        const match = trimmed.match(/^(\d+)\)\s(.+)/);
        if (match) {
          blocks.push(
            <div key={key++} className="flex items-start gap-2.5 py-1">
              <span className={`w-5 h-5 rounded-md ${colors.bg} ${colors.text} flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5`}>
                {match[1]}
              </span>
              <span className="text-[12px] text-gray-300 leading-relaxed flex-1">{formatLine(match[2])}</span>
            </div>
          );
        }
      } else if (/^[A-Z][\w\s/&,]+:/.test(trimmed) && trimmed.length < 100) {
        flushCard();
        const colonIdx = trimmed.indexOf(":");
        const label = trimmed.slice(0, colonIdx);
        const rest = trimmed.slice(colonIdx + 1).trim();
        blocks.push(
          <div key={key++} className="mt-2">
            <span className={`text-[11px] font-bold uppercase tracking-wider ${colors.text}`}>{label}</span>
            {rest && <p className="text-[12px] text-gray-400 mt-0.5 leading-relaxed">{formatLine(rest)}</p>}
          </div>
        );
      } else {
        blocks.push(
          <p key={key++} className="text-[12px] text-gray-400 leading-relaxed">{formatLine(trimmed)}</p>
        );
      }
    }
    flushCard();
    return blocks;
  };

  return (
    <div className={`glass rounded-2xl overflow-hidden border ${open ? colors.border : "border-white/[0.04]"} transition-all duration-200`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-5 py-4 hover:bg-white/[0.02] transition-colors text-left"
      >
        <div className={`w-9 h-9 rounded-xl ${colors.bg} ${colors.text} flex items-center justify-center shrink-0`}>
          <Icon className="w-[18px] h-[18px]" />
        </div>
        <div className="flex-1 min-w-0">
          <span className="text-[13px] font-bold text-white block">{section.title}</span>
          {!open && (
            <span className="text-[11px] text-gray-600 block mt-0.5">
              {section.type === "winners" ? "What\u2019s working and why" :
               section.type === "losers" ? "Root causes and fixes" :
               section.type === "budget" ? "Where to move your spend" :
               section.type === "strategy" ? "Long-term growth plan" :
               "Click to expand"}
            </span>
          )}
        </div>
        <ChevronDown className={`w-4 h-4 text-gray-500 shrink-0 transition-transform duration-200 ${open ? "" : "-rotate-90"}`} />
      </button>
      {open && (
        <div className="px-5 pb-5 pt-0">
          <div className="pt-3 space-y-2">
            {renderContent(section.content)}
          </div>
        </div>
      )}
    </div>
  );
}

function HealthScoreRing({ score }: { score: number }) {
  const pct = (score / 10) * 100;
  const color = score >= 7 ? "text-emerald-400" : score >= 4 ? "text-amber-400" : "text-red-400";
  const bgColor = score >= 7 ? "from-emerald-500/20 to-emerald-500/5" : score >= 4 ? "from-amber-500/20 to-amber-500/5" : "from-red-500/20 to-red-500/5";
  const label = score >= 7 ? "Healthy" : score >= 4 ? "Needs Work" : "Critical";
  const circumference = 2 * Math.PI * 40;
  const dashoffset = circumference - (pct / 100) * circumference;

  return (
    <div className={`glass rounded-2xl p-6 bg-gradient-to-br ${bgColor} flex items-center gap-6`}>
      <div className="relative w-24 h-24 shrink-0">
        <svg className="w-24 h-24 -rotate-90" viewBox="0 0 100 100">
          <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="8" />
          <circle
            cx="50" cy="50" r="40" fill="none"
            stroke="currentColor"
            className={color}
            strokeWidth="8"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashoffset}
            style={{ transition: "stroke-dashoffset 1s ease-out" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={`text-2xl font-bold ${color}`}>{score}</span>
          <span className="text-[10px] text-gray-500 font-medium">/10</span>
        </div>
      </div>
      <div>
        <p className="text-lg font-bold text-white mb-0.5">Account Health</p>
        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold ${
          score >= 7 ? "bg-emerald-500/10 text-emerald-400" : score >= 4 ? "bg-amber-500/10 text-amber-400" : "bg-red-500/10 text-red-400"
        }`}>
          {score >= 7 ? <CheckCircle2 className="w-3 h-3" /> : score >= 4 ? <AlertTriangle className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
          {label}
        </span>
      </div>
    </div>
  );
}

/* ── Proposal types ──────────────────────────────────────────────── */

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
};

const ACTION_STYLES: Record<string, { label: string; color: string; bg: string; icon: typeof Zap }> = {
  increase_budget: { label: "Scale Budget", color: "text-emerald-400", bg: "bg-emerald-500/10", icon: TrendingUp },
  decrease_budget: { label: "Cut Budget", color: "text-amber-400", bg: "bg-amber-500/10", icon: TrendingDown },
  pause: { label: "Pause", color: "text-red-400", bg: "bg-red-500/10", icon: PauseCircle },
  shift_budget: { label: "Shift Budget", color: "text-pink-400", bg: "bg-pink-500/10", icon: ArrowRightLeft },
  refresh_creative: { label: "Refresh Creative", color: "text-orange-400", bg: "bg-orange-500/10", icon: RefreshCw },
  mutate_winner: { label: "A/B Test", color: "text-indigo-400", bg: "bg-indigo-500/10", icon: Sparkles },
  create_lookalike: { label: "Lookalike", color: "text-teal-400", bg: "bg-teal-500/10", icon: Target },
  create_engagement_audience: { label: "Retarget Engagers", color: "text-purple-400", bg: "bg-purple-500/10", icon: Target },
  custom: { label: "Recommendation", color: "text-gray-400", bg: "bg-gray-500/10", icon: Lightbulb },
};

function ProposalActionCard({
  proposal,
  onStatusChange,
}: {
  proposal: Proposal;
  onStatusChange: (id: string, status: string) => void;
}) {
  const [applying, setApplying] = useState(false);
  const style = ACTION_STYLES[proposal.action_type] || ACTION_STYLES.custom;
  const Icon = style.icon;
  const isPending = proposal.status === "pending";
  const isApproved = proposal.status === "approved";

  const handleApprove = async () => {
    try {
      await api.updateProposalStatus(proposal.id, "approved");
      onStatusChange(proposal.id, "approved");
    } catch { /* ignore */ }
  };

  const handleReject = async () => {
    try {
      await api.updateProposalStatus(proposal.id, "rejected");
      onStatusChange(proposal.id, "rejected");
    } catch { /* ignore */ }
  };

  const handleApply = async () => {
    setApplying(true);
    try {
      await api.applyProposal(proposal.id);
      onStatusChange(proposal.id, "applied");
    } catch {
      onStatusChange(proposal.id, "failed");
    } finally {
      setApplying(false);
    }
  };

  const statusColors: Record<string, string> = {
    pending: "bg-blue-500/10 text-blue-400",
    approved: "bg-emerald-500/10 text-emerald-400",
    applied: "bg-violet-500/10 text-violet-400",
    rejected: "bg-gray-500/10 text-gray-500",
    failed: "bg-red-500/10 text-red-400",
  };

  return (
    <div className="glass rounded-xl p-4 hover:bg-white/[0.03] transition-all">
      <div className="flex items-start gap-3">
        <div className={`w-9 h-9 rounded-lg ${style.bg} ${style.color} flex items-center justify-center shrink-0`}>
          <Icon className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <h4 className="text-sm font-semibold text-white truncate">{proposal.entity_name || proposal.entity_id}</h4>
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
              proposal.impact_score >= 8 ? "bg-emerald-500/15 text-emerald-400" :
              proposal.impact_score >= 5 ? "bg-amber-500/15 text-amber-400" :
              "bg-gray-500/15 text-gray-400"
            }`}>
              {proposal.impact_score}/10
            </span>
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${statusColors[proposal.status] || statusColors.pending}`}>
              {proposal.status.toUpperCase()}
            </span>
          </div>
          <div className="flex items-center gap-1.5 mb-2">
            <span className={`text-[11px] font-medium ${style.color}`}>{style.label}</span>
            <span className="text-[10px] text-gray-600">{proposal.entity_type}</span>
          </div>
          <p className="text-xs text-gray-400 leading-relaxed">{proposal.ai_reasoning}</p>

          {/* Budget detail */}
          {(proposal.action_type === "increase_budget" || proposal.action_type === "decrease_budget") && (
            <div className="mt-2 flex items-center gap-2 text-xs">
              <span className="text-gray-500">
                ${Number(proposal.current_value?.daily_budget || 0).toFixed(2)}/day
              </span>
              <span className="text-gray-600">&rarr;</span>
              <span className={proposal.action_type === "increase_budget" ? "text-emerald-400 font-medium" : "text-amber-400 font-medium"}>
                ${Number(proposal.proposed_value?.daily_budget || 0).toFixed(2)}/day
              </span>
            </div>
          )}

          {/* Shift budget detail */}
          {proposal.action_type === "shift_budget" && (
            <div className="mt-2 flex items-center gap-2 text-xs">
              <span className="text-red-400 truncate max-w-[120px]">{String(proposal.proposed_value?.from_name || "Source")}</span>
              <ArrowRightLeft className="w-3 h-3 text-pink-400 shrink-0" />
              <span className="text-emerald-400 truncate max-w-[120px]">{String(proposal.proposed_value?.to_name || "Target")}</span>
              <span className="text-white font-medium">${Number(proposal.proposed_value?.amount_display || 0).toFixed(0)}</span>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1.5 shrink-0">
          {isPending && (
            <>
              <button
                onClick={handleApprove}
                className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 flex items-center justify-center transition-all"
                title="Approve"
              >
                <CheckCircle2 className="w-4 h-4" />
              </button>
              <button
                onClick={handleReject}
                className="w-8 h-8 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 flex items-center justify-center transition-all"
                title="Reject"
              >
                <XCircle className="w-4 h-4" />
              </button>
            </>
          )}
          {isApproved && (
            <button
              onClick={handleApply}
              disabled={applying}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all disabled:opacity-50"
            >
              {applying ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
              Apply
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function StrategyReport({ report }: { report: string }) {
  const { healthScore, healthReason, sections } = parseReport(report);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [generatingActions, setGeneratingActions] = useState(false);
  const [actionsGenerated, setActionsGenerated] = useState(false);

  // Separate quick wins for special treatment
  const quickWins = sections.find(s => s.type === "quick");
  const otherSections = sections.filter(s => s.type !== "health" && s.type !== "quick");

  const handleGenerateActions = async () => {
    setGeneratingActions(true);
    try {
      const { data } = await api.generateAuditActions();
      setProposals(data.proposals || []);
      setActionsGenerated(true);
    } catch (err) {
      console.error("Failed to generate actions:", err);
    } finally {
      setGeneratingActions(false);
    }
  };

  const handleStatusChange = (id: string, status: string) => {
    setProposals(prev => prev.map(p => p.id === id ? { ...p, status } : p));
  };

  const handleApproveAll = async () => {
    const pending = proposals.filter(p => p.status === "pending");
    for (const p of pending) {
      try {
        await api.updateProposalStatus(p.id, "approved");
        handleStatusChange(p.id, "approved");
      } catch { /* ignore */ }
    }
  };

  const handleApplyAll = async () => {
    try {
      await api.applyAllProposals();
      setProposals(prev => prev.map(p => p.status === "approved" ? { ...p, status: "applied" } : p));
    } catch { /* ignore */ }
  };

  const pendingCount = proposals.filter(p => p.status === "pending").length;
  const approvedCount = proposals.filter(p => p.status === "approved").length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500/20 to-violet-500/10 border border-blue-500/20 flex items-center justify-center">
            <Sparkles className="w-[18px] h-[18px] text-blue-400" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">AI Strategy Report</h3>
            <p className="text-xs text-gray-500">Powered by AI &middot; Based on your all-time</p>
          </div>
        </div>
      </div>

      {/* Health score + Quick wins side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {healthScore !== null && <HealthScoreRing score={healthScore} />}

        {quickWins && (
          <div className="glass rounded-2xl p-5 bg-gradient-to-br from-amber-500/[0.08] to-transparent">
            <div className="flex items-center gap-2 mb-3">
              <Zap className="w-4 h-4 text-amber-400" />
              <h4 className="text-sm font-semibold text-white">Quick Wins</h4>
              <span className="text-[10px] text-amber-400/60 font-medium uppercase tracking-wider ml-auto">Do This Week</span>
            </div>
            <div className="space-y-2">
              {quickWins.content.split("\n").filter((l: string) => l.trim()).slice(0, 5).map((line: string, i: number) => {
                const cleaned = line.trim().replace(/^[\d]+\)\s*/, "").replace(/^[-*]\s*/, "").replace(/\*\*/g, "");
                if (!cleaned) return null;
                return (
                  <div key={i} className="flex items-start gap-2.5">
                    <span className="w-5 h-5 rounded-md bg-amber-500/10 text-amber-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">
                      {i + 1}
                    </span>
                    <p className="text-xs text-gray-300 leading-relaxed">{cleaned}</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Health reason */}
      {healthReason && (
        <div className="glass rounded-xl px-4 py-3">
          <p className="text-xs text-gray-400 leading-relaxed">
            <span className="text-white font-medium">Summary: </span>
            {healthReason}
          </p>
        </div>
      )}

      {/* ── Action Plan ──────────────────────────────────────────────── */}
      {!actionsGenerated ? (
        <div className="glass rounded-2xl p-6 bg-gradient-to-br from-blue-500/[0.06] to-violet-500/[0.04] border border-blue-500/20">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500/20 to-violet-500/20 flex items-center justify-center shrink-0">
              <Zap className="w-6 h-6 text-blue-400" />
            </div>
            <div className="flex-1">
              <h4 className="text-sm font-bold text-white mb-0.5">Turn insights into action</h4>
              <p className="text-xs text-gray-400">
                Generate executable proposals from this report. Pause underperformers, scale winners, shift budgets — all with one click.
              </p>
            </div>
            <button
              onClick={handleGenerateActions}
              disabled={generatingActions}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 shrink-0"
            >
              {generatingActions ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
              {generatingActions ? "Analyzing..." : "Generate Action Plan"}
            </button>
          </div>
        </div>
      ) : proposals.length > 0 ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-white flex items-center gap-2">
              <Zap className="w-4 h-4 text-blue-400" />
              Action Plan
              <span className="text-xs text-gray-500 font-normal">{proposals.length} proposals</span>
            </h4>
            <div className="flex items-center gap-2">
              {pendingCount > 0 && (
                <button
                  onClick={handleApproveAll}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20 transition-all"
                >
                  <CheckCircle2 className="w-3 h-3" />
                  Approve All ({pendingCount})
                </button>
              )}
              {approvedCount > 0 && (
                <button
                  onClick={handleApplyAll}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-gradient-to-r from-blue-600 to-violet-600 text-white hover:from-blue-500 hover:to-violet-500 transition-all"
                >
                  <Zap className="w-3 h-3" />
                  Apply All ({approvedCount})
                </button>
              )}
            </div>
          </div>
          {proposals.map((p) => (
            <ProposalActionCard key={p.id} proposal={p} onStatusChange={handleStatusChange} />
          ))}
        </div>
      ) : (
        <div className="glass rounded-xl p-4 text-center text-sm text-gray-500">
          No actionable proposals could be generated. Try re-running the audit with fresh data.
        </div>
      )}

      {/* Detailed Analysis sections */}
      <div className="space-y-2">
        {otherSections.map((section, i) => (
          <CollapsibleSection key={i} section={section} defaultOpen={false} />
        ))}
      </div>

      {/* View Campaigns CTA */}
      <div className="glass rounded-xl p-4 flex items-center gap-3">
        <Lightbulb className="w-4 h-4 text-gray-500 shrink-0" />
        <p className="text-xs text-gray-500 flex-1">
          Head to the <strong className="text-gray-300">Campaigns</strong> page for detailed per-ad performance.
        </p>
        <a href="/dashboard/campaigns" className="text-xs font-medium text-blue-400 hover:text-blue-300 shrink-0">
          View Campaigns &rarr;
        </a>
      </div>
    </div>
  );
}

export function AccountAuditWidget() {
  const [audit, setAudit] = useState<Audit | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toneApplied, setToneApplied] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"active" | "all">("active");

  const fetchAudit = async () => {
    try {
      const { data } = await api.getLatestAudit();
      setAudit(data);
    } catch {
      // No audit yet
    } finally {
      setLoading(false);
    }
  };

  const runAudit = async () => {
    setSyncing(true);
    setError(null);
    try {
      const { data } = await api.runAudit(undefined, statusFilter);
      setAudit(data);
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Audit failed";
      setError(msg);
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    fetchAudit();
  }, []);
  useAutoRefresh(fetchAudit);

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="mb-8 space-y-4 animate-pulse">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1, 2].map((i) => (
            <div key={i} className="glass rounded-2xl p-6 h-28" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="glass rounded-2xl p-6 h-48" />
          <div className="glass rounded-2xl p-6 h-48" />
        </div>
        <div className="glass rounded-2xl p-6 h-32" />
        <p className="text-center text-sm text-gray-500 flex items-center justify-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />
          Syncing Account Data...
        </p>
      </div>
    );
  }

  // ── Empty / failed state ──────────────────────────────────────────────────
  if (!audit || audit.status === "failed") {
    return (
      <div className="glass rounded-2xl overflow-hidden mb-8">
        <div className="relative p-8">
          <div className="absolute top-0 right-0 w-[300px] h-[200px] bg-gradient-to-bl from-emerald-500/[0.08] to-transparent rounded-bl-full pointer-events-none" />
          <div className="relative flex flex-col sm:flex-row items-start sm:items-center gap-6">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-blue-500/10 border border-emerald-500/20 flex items-center justify-center shrink-0">
              <BarChart3 className="w-6 h-6 text-emerald-400" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-lg font-semibold text-white mb-1">
                Account Health &amp; Strategy Report
              </h2>
              <p className="text-sm text-gray-500 leading-relaxed max-w-xl">
                {audit?.status === "failed"
                  ? `Last audit failed: ${audit.error_message || "Unknown error"}. Click below to try again.`
                  : "Run an AI-powered audit to analyze your all-time of ad performance — identify winning ads, wasted spend, and get strategic recommendations."}
              </p>
            </div>
            <button
              onClick={runAudit}
              disabled={syncing}
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-emerald-600 to-blue-600 hover:from-emerald-500 hover:to-blue-500 rounded-xl text-sm font-semibold transition-all glow-blue hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
            >
              {syncing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  Run Initial Audit
                </>
              )}
            </button>
          </div>
          {error && (
            <div className="mt-4 flex items-center gap-2 text-red-400 text-sm">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Processing state ──────────────────────────────────────────────────────
  if (audit.status === "processing" || audit.status === "pending") {
    return (
      <div className="mb-8 space-y-4 animate-pulse">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1, 2].map((i) => (
            <div key={i} className="glass rounded-2xl p-6 h-28" />
          ))}
        </div>
        <div className="glass rounded-2xl p-8 flex items-center justify-center gap-3 text-blue-400">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm font-medium">
            Analyzing your ad account — fetching 30 days of performance data...
          </span>
        </div>
      </div>
    );
  }

  // ── Completed audit ───────────────────────────────────────────────────────
  const winners = parseAds(audit.winning_ads);
  const losers = parseAds(audit.losing_ads);
  const bl = parseBaselines(audit.baselines);

  // Per-ad result type labels
  const RESULT_META: Record<string, { label: string; resultLabel: string; costLabel: string }> = {
    purchases: { label: "Purchases", resultLabel: "purchases", costLabel: "CPA" },
    registrations: { label: "Registrations", resultLabel: "registrations", costLabel: "Cost/Reg" },
    leads: { label: "Leads", resultLabel: "leads", costLabel: "CPL" },
    messaging_conversations: { label: "Conversations", resultLabel: "chats", costLabel: "Cost/Chat" },
    messaging_replies: { label: "Replies", resultLabel: "replies", costLabel: "Cost/Reply" },
    link_clicks: { label: "Clicks", resultLabel: "clicks", costLabel: "CPC" },
    landing_page_views: { label: "Page Views", resultLabel: "views", costLabel: "Cost/View" },
    none: { label: "Results", resultLabel: "results", costLabel: "CPR" },
  };
  const getAdMeta = (ad: any) => RESULT_META[ad.result_type] || RESULT_META.none;

  return (
    <div className="mb-8 space-y-4 animate-fade-in">
      {/* Section header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-500/20 to-blue-500/10 flex items-center justify-center">
            <BarChart3 className="w-[18px] h-[18px] text-emerald-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">
              Account Health Report
            </h2>
            <p className="text-xs text-gray-500">
              {statusFilter === "all" ? "All" : "Active"} campaigns &middot; Updated{" "}
              {new Date(audit.created_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-white/[0.04] rounded-lg p-0.5">
            <button
              onClick={() => setStatusFilter("active")}
              className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-all ${
                statusFilter === "active"
                  ? "bg-emerald-500/20 text-emerald-400"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              Active
            </button>
            <button
              onClick={() => setStatusFilter("all")}
              className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-all ${
                statusFilter === "all"
                  ? "bg-emerald-500/20 text-emerald-400"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              All
            </button>
          </div>
          <button
            onClick={runAudit}
            disabled={syncing}
            className="inline-flex items-center gap-2 px-3 py-1.5 glass rounded-lg text-xs text-gray-400 hover:text-white transition-colors disabled:opacity-50"
          >
            {syncing ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <RefreshCw className="w-3 h-3" />
            )}
            Re-run Audit
          </button>
        </div>
      </div>

      {/* ── Top metric cards ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Total Spend */}
        <div className="glass rounded-2xl p-5 hover:bg-white/[0.04] transition-all duration-300">
          <div className="flex items-center justify-between mb-3">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center">
              <DollarSign className="w-[18px] h-[18px]" />
            </div>
            <span className="text-xs text-gray-600 font-medium">ALL-TIME</span>
          </div>
          <p className="text-sm text-gray-500 mb-0.5">Total Spend</p>
          <p className="text-2xl font-bold text-white tracking-tight">
            $
            {audit.total_spend?.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            }) ?? "0.00"}
          </p>
        </div>

        {/* Total Results / ROAS */}
        <div className="glass rounded-2xl p-5 hover:bg-white/[0.04] transition-all duration-300">
          <div className="flex items-center justify-between mb-3">
            <div className="w-9 h-9 rounded-xl bg-violet-500/10 text-violet-400 flex items-center justify-center">
              <TrendingUp className="w-[18px] h-[18px]" />
            </div>
            {audit.roas && Number(audit.roas) > 0 ? (
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                Number(audit.roas) >= 3 ? "bg-emerald-500/10 text-emerald-400"
                : Number(audit.roas) >= 1.5 ? "bg-yellow-500/10 text-yellow-400"
                : "bg-red-500/10 text-red-400"
              }`}>
                {Number(audit.roas) >= 3 ? "Healthy" : Number(audit.roas) >= 1.5 ? "Needs Work" : "At Risk"}
              </span>
            ) : (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400">
                {RESULT_META[bl?.dominant_type || ""]?.label || bl?.dominant_type || "Mixed"}
              </span>
            )}
          </div>
          {audit.roas && Number(audit.roas) > 0 ? (
            <>
              <p className="text-sm text-gray-500 mb-0.5">Blended ROAS</p>
              <p className="text-2xl font-bold text-white tracking-tight">
                {Number(audit.roas).toFixed(2)}x
              </p>
            </>
          ) : (
            <>
              <p className="text-sm text-gray-500 mb-0.5">Total Results</p>
              <p className="text-2xl font-bold text-white tracking-tight">
                {[...winners, ...losers].reduce((s, a) => s + (a.results || 0), 0)}
              </p>
            </>
          )}
        </div>
      </div>

      {/* ── Audience Demographics ──────────────────────────────────────── */}
      {(() => {
        const demo = parseDemographics(audit.audience_demographics);
        if (!demo) return null;
        return (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {demo.age_groups && Object.keys(demo.age_groups).length > 0 && (
              <div className="glass rounded-2xl p-5">
                <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                  <Activity className="w-4 h-4 text-blue-400" />
                  Age Distribution (by spend)
                </h3>
                <div className="space-y-2">
                  {Object.entries(demo.age_groups).map(([age, pct]) => (
                    <DemoBar key={age} label={age} pct={pct} />
                  ))}
                </div>
              </div>
            )}
            {demo.gender && Object.keys(demo.gender).length > 0 && (
              <div className="glass rounded-2xl p-5">
                <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                  <Activity className="w-4 h-4 text-violet-400" />
                  Gender Distribution (by spend)
                </h3>
                <div className="space-y-2">
                  {Object.entries(demo.gender).map(([g, pct]) => (
                    <DemoBar key={g} label={g} pct={pct} />
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })()}

      {/* ── Tone Recommendation ────────────────────────────────────────── */}
      {audit.tone_recommendation && (
        <div className="glass rounded-2xl p-4 flex items-center gap-4">
          <div className="w-9 h-9 rounded-xl bg-amber-500/10 flex items-center justify-center shrink-0">
            <Sparkles className="w-[18px] h-[18px] text-amber-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-white font-medium">
              Recommended Tone: <span className="capitalize text-amber-400">{audit.tone_recommendation}</span>
            </p>
            <p className="text-xs text-gray-500">Based on your top-performing ad patterns</p>
          </div>
          {!toneApplied ? (
            <button
              onClick={async () => {
                try {
                  const { data: prefs } = await api.getPreferences();
                  if (prefs) {
                    await api.upsertPreferences({
                      ...prefs,
                      content_tone: audit.tone_recommendation!,
                    });
                    setToneApplied(true);
                  }
                } catch { /* ignore */ }
              }}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20 transition-all shrink-0"
            >
              Apply
            </button>
          ) : (
            <span className="text-xs text-emerald-400 font-medium shrink-0">Applied!</span>
          )}
        </div>
      )}

      {/* ── All Ads — Scored & Categorized ──────────────────────────────── */}
      {(() => {
        // All evaluated ads are now stored in winning_ads (with score + verdict)
        // losers is kept for backward compat but we use winners as the master list
        const allAds = winners.length > losers.length
          ? [...winners].sort((a: any, b: any) => (b.score || 0) - (a.score || 0))
          : [...winners, ...losers].sort((a: any, b: any) => (b.score || 0) - (a.score || 0));
        const scaleAds = allAds.filter((a: any) => a.verdict === "scale");
        const holdAds = allAds.filter((a: any) => a.verdict === "hold");
        const underAds = allAds.filter((a: any) => a.verdict === "underperforming" || a.verdict === "kill");
        const learnAds = allAds.filter((a: any) => a.verdict === "learning");

        const VERDICT_STYLES: Record<string, { bg: string; text: string; label: string }> = {
          scale: { bg: "bg-emerald-500/10", text: "text-emerald-400", label: "Scale" },
          hold: { bg: "bg-amber-500/10", text: "text-amber-400", label: "Hold" },
          underperforming: { bg: "bg-red-500/10", text: "text-red-400", label: "Underperforming" },
          kill: { bg: "bg-red-500/10", text: "text-red-400", label: "Kill" },
          learning: { bg: "bg-blue-500/10", text: "text-blue-400", label: "Learning" },
        };

        const renderAdRow = (ad: any, i: number) => {
          const m = getAdMeta(ad);
          const vs = VERDICT_STYLES[ad.verdict] || VERDICT_STYLES.hold;
          return (
            <div key={i} className="border-b border-white/5 last:border-0">
              <div className="grid grid-cols-[32px_1fr_65px_70px_55px_55px] gap-2 py-2.5 items-center">
                {/* Score badge */}
                <div className={`w-8 h-8 rounded-lg ${vs.bg} flex items-center justify-center`}>
                  <span className={`text-xs font-bold ${vs.text}`}>{ad.score ?? "—"}</span>
                </div>
                {/* Name + result type */}
                <div className="min-w-0">
                  <p className="text-sm text-white truncate">{ad.ad_name}</p>
                  <div className="flex items-center gap-2 text-[10px]">
                    <span className={`font-medium ${vs.text}`}>
                      {ad.results || 0} {m.resultLabel}
                    </span>
                    {ad.days_running != null && (
                      <span className="text-gray-600">{ad.days_running}d</span>
                    )}
                    <span className={`px-1.5 py-0 rounded-full ${vs.bg} ${vs.text} text-[9px] font-medium`}>
                      {vs.label}
                    </span>
                  </div>
                </div>
                {/* Spend */}
                <span className="text-xs text-gray-400 text-right">${ad.spend?.toFixed(0)}</span>
                {/* Cost per result */}
                <div className="text-right">
                  <span className="text-xs text-gray-400">{ad.cost_per_result ? `$${ad.cost_per_result.toFixed(2)}` : "—"}</span>
                  <span className="text-[9px] text-gray-600 block">{m.costLabel}</span>
                </div>
                {/* CTR */}
                <span className="text-xs text-gray-400 text-right">{Number(ad.ctr || 0).toFixed(2)}%</span>
                {/* CPC */}
                <span className="text-xs text-gray-400 text-right">${Number(ad.cpc || 0).toFixed(2)}</span>
              </div>
              {ad.diagnosis && ad.verdict !== "scale" && (
                <div className="flex items-center gap-2 pb-2 pl-10">
                  <p className="text-[11px] text-amber-400/80 leading-relaxed flex-1">{ad.diagnosis}</p>
                  <button
                    onClick={async (e) => {
                      e.stopPropagation();
                      const btn = e.currentTarget;
                      btn.disabled = true;
                      btn.textContent = "Generating...";
                      try {
                        await api.bridgeAuditDiagnosis({
                          ad_id: ad.ad_id || "",
                          ad_name: ad.ad_name || "",
                          adset_id: "",
                          diagnosis: ad.diagnosis || "",
                          campaign_id: ad.campaign_id || "",
                        });
                        const adIdParam = encodeURIComponent(ad.ad_id || "");
                        const adNameParam = encodeURIComponent(ad.ad_name || "");
                        window.location.href = `/dashboard/copilot?filter_ad_id=${adIdParam}&ad_name=${adNameParam}&_t=${Date.now()}`;
                      } catch {
                        btn.textContent = "Failed";
                        setTimeout(() => { btn.textContent = "Fix →"; btn.disabled = false; }, 2000);
                      }
                    }}
                    className="text-[10px] px-2 py-0.5 rounded-full bg-violet-500/10 text-violet-400 hover:bg-violet-500/20 border border-violet-500/20 shrink-0 transition-all disabled:opacity-50"
                  >
                    Fix →
                  </button>
                </div>
              )}
            </div>
          );
        };

        const renderSection = (title: string, icon: any, ads: any[], color: string) => {
          if (ads.length === 0) return null;
          const Icon = icon;
          return (
            <div className="glass rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <Icon className={`w-4 h-4 ${color}`} />
                <h3 className="text-sm font-semibold text-white">{title}</h3>
                <span className="text-xs text-gray-600 ml-auto">{ads.length} ad{ads.length !== 1 ? "s" : ""}</span>
              </div>
              <div className="grid grid-cols-[32px_1fr_65px_70px_55px_55px] gap-2 text-[9px] text-gray-600 uppercase tracking-wider pb-2 border-b border-white/5">
                <span></span>
                <span>Ad Name</span>
                <span className="text-right">Spend</span>
                <span className="text-right">Cost/Res</span>
                <span className="text-right">CTR</span>
                <span className="text-right">CPC</span>
              </div>
              {ads.map(renderAdRow)}
            </div>
          );
        };

        return (
          <div className="space-y-4">
            {renderSection("Scale — Top Performers", Trophy, scaleAds, "text-emerald-400")}
            {renderSection("Hold — Average Performers", Activity, holdAds, "text-amber-400")}
            {renderSection("Underperforming — Needs Action", ThumbsDown, underAds, "text-red-400")}
            {renderSection("Learning — Still Optimizing", Sparkles, learnAds, "text-blue-400")}
            {allAds.length === 0 && (
              <div className="glass rounded-2xl p-5 text-center">
                <p className="text-sm text-gray-500">No ad data found. Run a new audit.</p>
              </div>
            )}
          </div>
        );
      })()}

      {/* ── AI Strategy Report ──────────────────────────────────────────── */}
      {audit.ai_strategy_report && audit.ai_strategy_report.trim() ? (
        <StrategyReport report={audit.ai_strategy_report} />
      ) : (
        <div className="glass rounded-2xl p-5 flex items-center gap-4">
          <div className="w-9 h-9 rounded-xl bg-blue-500/10 flex items-center justify-center shrink-0">
            <Sparkles className="w-[18px] h-[18px] text-blue-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-white font-medium">AI Strategy Report</p>
            <p className="text-xs text-gray-500">Report was empty — click &quot;Re-run Audit&quot; above to regenerate.</p>
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}
    </div>
  );
}
