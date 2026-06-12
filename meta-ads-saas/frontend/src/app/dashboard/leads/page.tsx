"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import {
  ClipboardList,
  Download,
  Loader2,
  FileText,
  Users,
  Calendar,
  RefreshCw,
  AlertCircle,
  Eye,
} from "lucide-react";

type LeadForm = {
  id: string | null;
  page_id: string;
  meta_form_id: string;
  form_name: string;
  questions: { type: string; key: string; label?: string }[];
  created_at: string;
  leads_count?: number;
  status?: string;
  campaign_name?: string;
  campaign_status?: string;
  source: "saved" | "meta";
};

type Lead = {
  id: string;
  created_time: string;
  [key: string]: string;
};

export default function LeadsPage() {
  const [forms, setForms] = useState<LeadForm[]>([]);
  const [loading, setLoading] = useState(true);
  const [warning, setWarning] = useState<string | null>(null);
  const [expandedForm, setExpandedForm] = useState<string | null>(null);
  const [leads, setLeads] = useState<Record<string, Lead[]>>({});
  const [loadingLeads, setLoadingLeads] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  const loadForms = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listLeadForms();
      const body = res.data;
      // New shape: { data: [...], warning: "..." }
      if (body && typeof body === "object" && "data" in body) {
        setForms(Array.isArray(body.data) ? body.data : []);
        setWarning(body.warning || null);
      } else {
        // Legacy shape: direct array
        setForms(Array.isArray(body) ? body : []);
        setWarning(null);
      }
    } catch {
      setForms([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadForms(); }, [loadForms]);

  const handleExpand = async (formId: string) => {
    if (expandedForm === formId) {
      setExpandedForm(null);
      return;
    }
    setExpandedForm(formId);
    if (!leads[formId]) {
      setLoadingLeads(formId);
      try {
        const res = await api.getLeadFormLeads(formId);
        setLeads((prev) => ({ ...prev, [formId]: res.data.leads || [] }));
      } catch {
        setLeads((prev) => ({ ...prev, [formId]: [] }));
      } finally {
        setLoadingLeads(null);
      }
    }
  };

  const handleDownload = async (formId: string, formName: string) => {
    setDownloading(formId);
    try {
      const res = await api.downloadLeadsCsv(formId);
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${formName.replace(/[^a-zA-Z0-9]/g, "_")}_leads.csv`;
      a.click();
      window.URL.revokeObjectURL(url);
    } catch {
      alert("No leads found or download failed.");
    } finally {
      setDownloading(null);
    }
  };

  const totalLeads = forms.reduce((sum, f) => sum + (f.leads_count ?? 0), 0);

  return (
    <div className="p-8 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <ClipboardList className="w-5 h-5 text-blue-400" /> Leads
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            View and download leads from your Meta Lead Gen Forms (Instant Forms).
          </p>
        </div>
        <button
          onClick={loadForms}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.04] border border-white/[0.08] text-gray-400 hover:text-white hover:bg-white/[0.06] transition-all"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <div className="rounded-2xl border border-blue-500/20 bg-blue-500/[0.03] p-4">
          <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2">
            <FileText className="w-3.5 h-3.5 text-blue-400" /> Lead Forms
          </div>
          <div className="text-2xl font-bold text-white">
            {loading ? <Loader2 className="w-5 h-5 animate-spin text-gray-600" /> : forms.length}
          </div>
          <p className="text-[10px] text-gray-600 mt-1">From your Meta Page</p>
        </div>
        <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/[0.03] p-4">
          <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2">
            <Users className="w-3.5 h-3.5 text-emerald-400" /> Total Leads
          </div>
          <div className="text-2xl font-bold text-white">
            {loading ? <Loader2 className="w-5 h-5 animate-spin text-gray-600" /> : totalLeads.toLocaleString()}
          </div>
          <p className="text-[10px] text-gray-600 mt-1">Across all forms</p>
        </div>
        <div className="rounded-2xl border border-violet-500/20 bg-violet-500/[0.03] p-4">
          <div className="flex items-center gap-2 text-gray-500 text-xs font-medium mb-2">
            <Download className="w-3.5 h-3.5 text-violet-400" /> Export
          </div>
          <div className="text-lg font-bold text-violet-400">CSV</div>
          <p className="text-[10px] text-gray-600 mt-1">Click any form to download</p>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-gray-600" />
        </div>
      )}

      {/* Permission Warning */}
      {!loading && warning === "missing_permissions" && forms.length === 0 && (
        <div className="rounded-2xl border border-red-500/20 bg-red-500/[0.05] p-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm text-red-300 font-medium">Missing Meta Permissions</p>
              <p className="text-xs text-gray-400 mt-1.5 leading-relaxed">
                Your Meta access token is missing the <span className="text-gray-300 font-medium">pages_manage_ads</span> and <span className="text-gray-300 font-medium">leads_retrieval</span> permissions
                required to list lead gen forms. To fix this:
              </p>
              <ol className="text-xs text-gray-400 mt-2 space-y-1 list-decimal list-inside">
                <li>Go to <span className="text-gray-300">Meta Developer Portal → Your App → Permissions</span></li>
                <li>Enable <span className="text-gray-300">pages_manage_ads</span> and <span className="text-gray-300">leads_retrieval</span></li>
                <li>Generate a new access token with those permissions</li>
                <li>Update the token in <span className="text-gray-300">Settings → Meta Connection</span></li>
              </ol>
            </div>
          </div>
        </div>
      )}

      {/* No Token Warning */}
      {!loading && warning === "no_token" && forms.length === 0 && (
        <div className="rounded-2xl border border-amber-500/10 bg-amber-500/[0.03] p-6 text-center">
          <AlertCircle className="w-8 h-8 text-amber-400 mx-auto mb-3" />
          <p className="text-sm text-amber-300 font-medium">No Meta account connected</p>
          <p className="text-xs text-gray-500 mt-2 max-w-md mx-auto">
            Connect your Meta ad account in Settings to view lead forms.
          </p>
        </div>
      )}

      {/* Empty State (no permission issue) */}
      {!loading && forms.length === 0 && !warning && (
        <div className="rounded-2xl border border-amber-500/10 bg-amber-500/[0.03] p-6 text-center">
          <AlertCircle className="w-8 h-8 text-amber-400 mx-auto mb-3" />
          <p className="text-sm text-amber-300 font-medium">No Lead Gen Forms found</p>
          <p className="text-xs text-gray-500 mt-2 max-w-md mx-auto">
            Lead forms appear here when you create campaigns with the &quot;Instant Form&quot; destination.
            Go to Drafts, create a new ad with Instant Form, and your forms will show up here.
          </p>
        </div>
      )}

      {/* Forms List */}
      {!loading && forms.length > 0 && (
        <div className="space-y-3">
          {forms.map((form) => {
            const fid = form.meta_form_id;
            const isExpanded = expandedForm === fid;
            const formLeads = leads[fid] || [];
            const isLoadingThis = loadingLeads === fid;
            const isDownloading = downloading === fid;

            return (
              <div
                key={fid}
                className="rounded-2xl border border-white/[0.06] bg-[#0a0a0f]/60 overflow-hidden"
              >
                {/* Form Header */}
                <div className="flex items-center justify-between p-4">
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center shrink-0">
                      <FileText className="w-5 h-5 text-blue-400" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold text-white truncate">{form.form_name}</h3>
                      {form.campaign_name && (
                        <p className="text-[11px] text-gray-400 truncate mt-0.5">
                          Campaign: <span className="text-gray-300 font-medium">{form.campaign_name}</span>
                          {form.campaign_status && (
                            <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                              form.campaign_status === "ACTIVE"
                                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                : "bg-red-500/10 text-red-400 border border-red-500/20"
                            }`}>
                              {form.campaign_status.charAt(0) + form.campaign_status.slice(1).toLowerCase().replace(/_/g, " ")}
                            </span>
                          )}
                        </p>
                      )}
                      <div className="flex items-center gap-3 mt-0.5">
                        <span className="text-[10px] text-gray-600 font-mono">{fid}</span>
                        {form.status && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                            form.status === "ACTIVE"
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                              : form.status === "PAUSED" || form.status === "ARCHIVED"
                              ? "bg-gray-500/10 text-gray-400 border border-gray-500/20"
                              : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                          }`}>
                            {form.status.charAt(0) + form.status.slice(1).toLowerCase()}
                          </span>
                        )}
                        {form.leads_count != null && form.leads_count > 0 && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                            {form.leads_count} leads
                          </span>
                        )}
                        {form.created_at && (
                          <span className="flex items-center gap-1 text-[10px] text-gray-600">
                            <Calendar className="w-3 h-3" />
                            {new Date(form.created_at).toLocaleDateString()}
                          </span>
                        )}
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                          form.source === "saved"
                            ? "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                            : "bg-violet-500/10 text-violet-400 border border-violet-500/20"
                        }`}>
                          {form.source === "saved" ? "Saved" : "Meta"}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => handleExpand(fid)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.04] border border-white/[0.08] text-gray-400 hover:text-white hover:bg-white/[0.06] transition-all"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      {isExpanded ? "Hide" : "Preview"}
                    </button>
                    <button
                      onClick={() => handleDownload(fid, form.form_name)}
                      disabled={isDownloading}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/20 transition-all disabled:opacity-50"
                    >
                      {isDownloading ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Download className="w-3.5 h-3.5" />
                      )}
                      Download CSV
                    </button>
                  </div>
                </div>

                {/* Expanded Leads Preview */}
                {isExpanded && (
                  <div className="border-t border-white/[0.06]">
                    {isLoadingThis ? (
                      <div className="flex items-center justify-center py-8">
                        <Loader2 className="w-5 h-5 animate-spin text-gray-600" />
                      </div>
                    ) : formLeads.length === 0 ? (
                      <div className="py-6 text-center text-xs text-gray-600">
                        No leads submitted yet.
                      </div>
                    ) : (() => {
                      // Build canonical column list from ALL leads (not just first)
                      const colSet = new Set<string>();
                      const columns: string[] = [];
                      for (const lead of formLeads) {
                        for (const key of Object.keys(lead)) {
                          if (key !== "id" && !colSet.has(key)) {
                            colSet.add(key);
                            columns.push(key);
                          }
                        }
                      }
                      return (
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-white/[0.06]">
                              {columns.map((key) => (
                                <th key={key} className="text-left text-gray-500 font-medium py-2 px-3 whitespace-nowrap">
                                  {key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {formLeads.slice(0, 20).map((lead) => (
                              <tr key={lead.id} className="border-b border-white/[0.04] hover:bg-white/[0.02]">
                                {columns.map((key) => (
                                  <td key={key} className="py-2 px-3 text-gray-300 whitespace-nowrap">
                                    {key === "created_time"
                                      ? new Date(lead[key]).toLocaleString()
                                      : lead[key] || "\u2014"}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {formLeads.length > 20 && (
                          <div className="px-3 py-2 text-[10px] text-gray-600 border-t border-white/[0.04]">
                            Showing 20 of {formLeads.length} leads. Download CSV for full data.
                          </div>
                        )}
                      </div>
                      );
                    })()}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Info */}
      <div className="rounded-2xl border border-white/[0.06] bg-[#0a0a0f]/60 p-5">
        <h2 className="text-sm font-semibold text-white mb-3">About Lead Downloads</h2>
        <div className="grid grid-cols-3 gap-4 text-xs text-gray-500">
          <div className="space-y-1">
            <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center mb-2">
              <FileText className="w-4 h-4 text-blue-400" />
            </div>
            <p className="text-white font-medium">Instant Forms Only</p>
            <p>Leads are downloadable when your ads use Meta&apos;s Instant Form destination. Website form leads are tracked by your pixel, not stored by Meta.</p>
          </div>
          <div className="space-y-1">
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center mb-2">
              <Download className="w-4 h-4 text-emerald-400" />
            </div>
            <p className="text-white font-medium">CSV Export</p>
            <p>Download includes all form fields (name, email, phone, custom questions) with timestamps. Import directly into your CRM or WhatsApp.</p>
          </div>
          <div className="space-y-1">
            <div className="w-8 h-8 rounded-lg bg-violet-500/10 flex items-center justify-center mb-2">
              <Users className="w-4 h-4 text-violet-400" />
            </div>
            <p className="text-white font-medium">Auto-Sync to Audiences</p>
            <p>Downloaded leads can be uploaded to the Audiences page as customer data to power Lookalike targeting.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
