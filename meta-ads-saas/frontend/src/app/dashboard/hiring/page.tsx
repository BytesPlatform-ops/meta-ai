"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Briefcase, Plus, Pencil, Trash2, X, Sparkles, Rocket, MapPin,
  Clock, DollarSign, GraduationCap, Building2, Monitor, Users,
  Loader2, Tag,
} from "lucide-react";
import { api } from "@/lib/api";

/* ── Types ───────────────────────────────────────────────────── */

interface Job {
  id: string;
  job_title: string;
  department: string | null;
  company_name: string | null;
  company_logo_url: string | null;
  work_mode: string;
  location: string | null;
  employment_type: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  salary_period: string;
  perks: string | null;
  experience_level: string;
  experience_years_min: number;
  experience_years_max: number | null;
  education_level: string | null;
  skills: string[];
  target_candidate_profile: string | null;
  requirements: string | null;
  responsibilities: string | null;
  application_url: string | null;
  application_email: string | null;
  target_country: string;
  target_cities: { name: string; key?: string }[] | null;
  status: string;
  tags: string[];
  created_at: string;
}

interface FormData {
  job_title: string;
  department: string;
  company_name: string;
  work_mode: string;
  location: string;
  employment_type: string;
  salary_min: string;
  salary_max: string;
  salary_currency: string;
  salary_period: string;
  perks: string;
  experience_level: string;
  experience_years_min: string;
  experience_years_max: string;
  education_level: string;
  skills: string;
  target_candidate_profile: string;
  requirements: string;
  responsibilities: string;
  application_url: string;
  application_email: string;
  target_country: string;
  status: string;
  tags: string;
}

const EMPTY_FORM: FormData = {
  job_title: "", department: "", company_name: "", work_mode: "onsite",
  location: "", employment_type: "full_time", salary_min: "", salary_max: "",
  salary_currency: "PKR", salary_period: "month", perks: "",
  experience_level: "entry", experience_years_min: "0", experience_years_max: "",
  education_level: "", skills: "", target_candidate_profile: "",
  requirements: "", responsibilities: "", application_url: "",
  application_email: "", target_country: "PK", status: "open", tags: "",
};

const WORK_MODES = [
  { value: "onsite", label: "On-site", icon: Building2 },
  { value: "remote", label: "Remote", icon: Monitor },
  { value: "hybrid", label: "Hybrid", icon: Users },
];

const EMP_TYPES = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" },
  { value: "freelance", label: "Freelance" },
];

const EXP_LEVELS = [
  { value: "entry", label: "Entry Level" },
  { value: "mid", label: "Mid Level" },
  { value: "senior", label: "Senior" },
  { value: "lead", label: "Lead / Manager" },
  { value: "executive", label: "Executive" },
];

const CURRENCIES = [
  { value: "PKR", symbol: "₨" }, { value: "USD", symbol: "$" },
  { value: "GBP", symbol: "£" }, { value: "EUR", symbol: "€" },
  { value: "AED", symbol: "د.إ" }, { value: "SAR", symbol: "﷼" },
  { value: "INR", symbol: "₹" }, { value: "CAD", symbol: "C$" },
];

const COUNTRIES: Record<string, string> = {
  PK: "Pakistan", US: "United States", GB: "United Kingdom",
  AE: "UAE", SA: "Saudi Arabia", IN: "India", CA: "Canada",
  AU: "Australia", DE: "Germany", FR: "France", TR: "Turkey",
  MY: "Malaysia", NG: "Nigeria", KE: "Kenya", BD: "Bangladesh",
};

/* ── Page Component ──────────────────────────────────────────── */

export default function HiringPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState<string | null>(null);
  const [genStep, setGenStep] = useState("");

  const fetchJobs = async () => {
    try {
      const { data } = await api.listJobs();
      setJobs(data as Job[]);
    } catch { setJobs([]); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchJobs(); }, []);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setEditingId(null);
    setShowForm(true);
  };

  const openEdit = (job: Job) => {
    setForm({
      job_title: job.job_title,
      department: job.department || "",
      company_name: job.company_name || "",
      work_mode: job.work_mode,
      location: job.location || "",
      employment_type: job.employment_type,
      salary_min: job.salary_min ? String(job.salary_min) : "",
      salary_max: job.salary_max ? String(job.salary_max) : "",
      salary_currency: job.salary_currency,
      salary_period: job.salary_period,
      perks: job.perks || "",
      experience_level: job.experience_level,
      experience_years_min: String(job.experience_years_min),
      experience_years_max: job.experience_years_max ? String(job.experience_years_max) : "",
      education_level: job.education_level || "",
      skills: (job.skills || []).join(", "),
      target_candidate_profile: job.target_candidate_profile || "",
      requirements: job.requirements || "",
      responsibilities: job.responsibilities || "",
      application_url: job.application_url || "",
      application_email: job.application_email || "",
      target_country: job.target_country,
      status: job.status,
      tags: (job.tags || []).join(", "),
    });
    setEditingId(job.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.job_title.trim()) return;
    setSaving(true);
    const data = {
      job_title: form.job_title.trim(),
      department: form.department.trim() || null,
      company_name: form.company_name.trim() || null,
      work_mode: form.work_mode,
      location: form.location.trim() || null,
      employment_type: form.employment_type,
      salary_min: form.salary_min ? parseFloat(form.salary_min) : null,
      salary_max: form.salary_max ? parseFloat(form.salary_max) : null,
      salary_currency: form.salary_currency,
      salary_period: form.salary_period,
      perks: form.perks.trim() || null,
      experience_level: form.experience_level,
      experience_years_min: parseInt(form.experience_years_min) || 0,
      experience_years_max: form.experience_years_max ? parseInt(form.experience_years_max) : null,
      education_level: form.education_level.trim() || null,
      skills: form.skills.split(",").map(s => s.trim()).filter(Boolean),
      target_candidate_profile: form.target_candidate_profile.trim() || null,
      requirements: form.requirements.trim() || null,
      responsibilities: form.responsibilities.trim() || null,
      application_url: form.application_url.trim() || null,
      application_email: form.application_email.trim() || null,
      target_country: form.target_country,
      status: form.status,
      tags: form.tags.split(",").map(t => t.trim()).filter(Boolean),
    };
    try {
      if (editingId) {
        await api.updateJob(editingId, data);
      } else {
        await api.createJob(data);
      }
      setShowForm(false);
      fetchJobs();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("Save failed:", msg, err);
      alert("Failed to save job: " + msg);
    } finally { setSaving(false); }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteJob(id);
      setJobs(prev => prev.filter(j => j.id !== id));
    } catch (err) { console.error("Delete failed:", err); }
  };

  const handleGenerate = async (job: Job) => {
    setGenerating(job.id);
    setGenStep("Analyzing job market...");
    const t1 = setTimeout(() => setGenStep("Crafting creative filters..."), 3000);
    const t2 = setTimeout(() => setGenStep("Writing 3 hiring ad angles..."), 7000);
    try {
      const salaryStr = [
        job.salary_min ? `${CURRENCIES.find(c => c.value === job.salary_currency)?.symbol || ""}${job.salary_min}` : "",
        job.salary_max ? `${CURRENCIES.find(c => c.value === job.salary_currency)?.symbol || ""}${job.salary_max}` : "",
      ].filter(Boolean).join(" – ") + (job.salary_period ? `/${job.salary_period}` : "");

      const hiringData = {
        job_title: job.job_title,
        target_candidate_profile: job.target_candidate_profile || `${job.experience_level} level candidate for ${job.job_title}`,
        salary_and_perks: [salaryStr, job.perks].filter(Boolean).join(" + "),
        requirements: job.requirements || undefined,
        responsibilities: job.responsibilities || undefined,
      };

      await api.generateDrafts(
        3, undefined, false, undefined, undefined, undefined,
        undefined, undefined, undefined, hiringData, job.id,
      );
      router.push("/dashboard/drafts");
    } catch (err) { console.error("Generation failed:", err); }
    finally {
      clearTimeout(t1); clearTimeout(t2);
      setGenerating(null); setGenStep("");
    }
  };

  const getSalaryDisplay = (job: Job) => {
    const sym = CURRENCIES.find(c => c.value === job.salary_currency)?.symbol || "";
    if (job.salary_min && job.salary_max) return `${sym}${job.salary_min.toLocaleString()} – ${sym}${job.salary_max.toLocaleString()}`;
    if (job.salary_min) return `${sym}${job.salary_min.toLocaleString()}+`;
    if (job.salary_max) return `Up to ${sym}${job.salary_max.toLocaleString()}`;
    return "Not specified";
  };

  const f = (key: keyof FormData, value: string) => setForm(p => ({ ...p, [key]: value }));
  const inputCls = "w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-emerald-500/40 transition-all";
  const labelCls = "text-xs text-gray-500 mb-1.5 block";

  return (
    <div className="space-y-6 px-6 py-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Hiring <span className="text-emerald-400">& Recruitment Ads</span>
          </h1>
          <p className="text-sm text-gray-500 mt-1">Create job listings and generate HEC-compliant Meta recruitment ads.</p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white transition-all"
        >
          <Plus className="w-4 h-4" /> Add Job
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 text-emerald-400 animate-spin" />
        </div>
      )}

      {/* Empty state */}
      {!loading && jobs.length === 0 && (
        <div className="text-center py-20">
          <Briefcase className="w-12 h-12 text-gray-700 mx-auto mb-4" />
          <p className="text-gray-500 text-sm">No job listings yet.</p>
          <button onClick={openCreate} className="mt-4 text-sm text-emerald-400 hover:text-emerald-300 transition-colors">
            + Create your first job listing
          </button>
        </div>
      )}

      {/* Job Cards Grid */}
      {!loading && jobs.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {jobs.map((job) => (
            <div key={job.id} className="glass rounded-2xl overflow-hidden group hover:border-emerald-500/20 transition-all">
              <div className="p-5 space-y-3">
                {/* Title & Status */}
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-white font-semibold text-sm truncate">{job.job_title}</h3>
                    {job.department && <p className="text-[11px] text-gray-500 mt-0.5">{job.department}</p>}
                  </div>
                  <span className={`ml-2 shrink-0 px-2 py-0.5 rounded-md text-[10px] font-semibold uppercase border ${
                    job.status === "open" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                    job.status === "closed" ? "bg-red-500/10 text-red-400 border-red-500/20" :
                    "bg-gray-500/10 text-gray-400 border-gray-500/20"
                  }`}>{job.status}</span>
                </div>

                {/* Badges row */}
                <div className="flex flex-wrap gap-1.5">
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-blue-500/10 text-[10px] text-blue-400 border border-blue-500/15">
                    <Clock className="w-2.5 h-2.5" />{EMP_TYPES.find(t => t.value === job.employment_type)?.label || job.employment_type}
                  </span>
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-violet-500/10 text-[10px] text-violet-400 border border-violet-500/15">
                    {WORK_MODES.find(w => w.value === job.work_mode)?.label || job.work_mode}
                  </span>
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-amber-500/10 text-[10px] text-amber-400 border border-amber-500/15">
                    <GraduationCap className="w-2.5 h-2.5" />{EXP_LEVELS.find(e => e.value === job.experience_level)?.label || job.experience_level}
                  </span>
                </div>

                {/* Salary */}
                <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                  <DollarSign className="w-3.5 h-3.5" />
                  <span className="font-medium">{getSalaryDisplay(job)}</span>
                  {job.salary_period && <span className="text-gray-600">/{job.salary_period}</span>}
                </div>

                {/* Location */}
                {job.location && (
                  <div className="flex items-center gap-1.5 text-xs text-gray-500">
                    <MapPin className="w-3 h-3" />{job.location}
                  </div>
                )}

                {/* Perks */}
                {job.perks && (
                  <p className="text-[11px] text-gray-500 line-clamp-1">🎁 {job.perks}</p>
                )}

                {/* Skills */}
                {job.skills && job.skills.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {job.skills.slice(0, 4).map((s, i) => (
                      <span key={i} className="px-1.5 py-0.5 rounded bg-white/[0.04] text-[10px] text-gray-400 border border-white/[0.06]">{s}</span>
                    ))}
                    {job.skills.length > 4 && <span className="text-[10px] text-gray-600">+{job.skills.length - 4} more</span>}
                  </div>
                )}

                {/* Tags */}
                {job.tags && job.tags.length > 0 && (
                  <div className="flex items-center gap-1">
                    <Tag className="w-2.5 h-2.5 text-gray-600" />
                    {job.tags.map((t, i) => (
                      <span key={i} className="text-[10px] text-gray-600">{t}{i < job.tags.length - 1 ? "," : ""}</span>
                    ))}
                  </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-2 pt-2 border-t border-white/[0.04]">
                  <button
                    onClick={() => handleGenerate(job)}
                    disabled={generating === job.id}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-gradient-to-r from-emerald-600/80 to-teal-600/80 hover:from-emerald-500 hover:to-teal-500 text-white transition-all disabled:opacity-50"
                  >
                    {generating === job.id ? (
                      <><Loader2 className="w-3 h-3 animate-spin" /><span className="truncate">{genStep || "Generating..."}</span></>
                    ) : (
                      <><Sparkles className="w-3 h-3" />Generate Hiring Ads</>
                    )}
                  </button>
                  <button onClick={() => openEdit(job)} className="p-2 rounded-xl text-gray-500 hover:text-emerald-400 hover:bg-emerald-500/[0.06] transition-all">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => handleDelete(job.id)} className="p-2 rounded-xl text-gray-500 hover:text-red-400 hover:bg-red-500/[0.06] transition-all">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Create / Edit Modal ──────────────────────────────────── */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="glass rounded-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.06] sticky top-0 bg-[#0a0a0f]/95 backdrop-blur-sm z-10">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                  <Briefcase className="w-4 h-4 text-emerald-400" />
                </div>
                <p className="text-sm font-semibold text-white">{editingId ? "Edit Job" : "New Job Listing"}</p>
              </div>
              <button onClick={() => setShowForm(false)} className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-white/[0.06] transition-all">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {/* Job Title */}
              <div>
                <label className={labelCls}>Job Title *</label>
                <input type="text" value={form.job_title} onChange={e => f("job_title", e.target.value)} placeholder="e.g. Junior Graphic Designer" className={inputCls} />
              </div>

              {/* Department + Company */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Department</label>
                  <input type="text" value={form.department} onChange={e => f("department", e.target.value)} placeholder="e.g. Marketing" className={inputCls} />
                </div>
                <div>
                  <label className={labelCls}>Company Name</label>
                  <input type="text" value={form.company_name} onChange={e => f("company_name", e.target.value)} placeholder="e.g. Bytes Platform" className={inputCls} />
                </div>
              </div>

              {/* Work Mode */}
              <div>
                <label className={labelCls}>Work Mode</label>
                <div className="grid grid-cols-3 gap-2">
                  {WORK_MODES.map(wm => {
                    const Icon = wm.icon;
                    return (
                      <button key={wm.value} type="button" onClick={() => f("work_mode", wm.value)}
                        className={`flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl text-xs font-medium border transition-all ${form.work_mode === wm.value ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" : "bg-white/[0.03] border-white/[0.08] text-gray-500 hover:text-gray-300"}`}>
                        <Icon className="w-3.5 h-3.5" />{wm.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Location */}
              <div>
                <label className={labelCls}>Location</label>
                <input type="text" value={form.location} onChange={e => f("location", e.target.value)} placeholder="e.g. Lahore, Pakistan" className={inputCls} />
              </div>

              {/* Employment Type */}
              <div>
                <label className={labelCls}>Employment Type</label>
                <select value={form.employment_type} onChange={e => f("employment_type", e.target.value)} className={inputCls}>
                  {EMP_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>

              {/* Salary */}
              <div>
                <label className={labelCls}>Salary Range</label>
                <div className="flex gap-2">
                  <select value={form.salary_currency} onChange={e => f("salary_currency", e.target.value)} className="w-20 px-2 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-emerald-500/40 transition-all">
                    {CURRENCIES.map(c => <option key={c.value} value={c.value}>{c.symbol} {c.value}</option>)}
                  </select>
                  <input type="number" value={form.salary_min} onChange={e => f("salary_min", e.target.value)} placeholder="Min" className={`flex-1 ${inputCls}`} />
                  <span className="flex items-center text-gray-600 text-sm">–</span>
                  <input type="number" value={form.salary_max} onChange={e => f("salary_max", e.target.value)} placeholder="Max" className={`flex-1 ${inputCls}`} />
                  <select value={form.salary_period} onChange={e => f("salary_period", e.target.value)} className="w-24 px-2 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm focus:outline-none focus:border-emerald-500/40 transition-all">
                    <option value="month">/month</option>
                    <option value="year">/year</option>
                    <option value="hour">/hour</option>
                    <option value="project">/project</option>
                  </select>
                </div>
              </div>

              {/* Perks */}
              <div>
                <label className={labelCls}>Perks & Benefits</label>
                <input type="text" value={form.perks} onChange={e => f("perks", e.target.value)} placeholder="e.g. Medical + Transport + Lunch + Annual Bonus" className={inputCls} />
              </div>

              {/* Experience */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Experience Level</label>
                  <select value={form.experience_level} onChange={e => f("experience_level", e.target.value)} className={inputCls}>
                    {EXP_LEVELS.map(l => <option key={l.value} value={l.value}>{l.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Education Level</label>
                  <input type="text" value={form.education_level} onChange={e => f("education_level", e.target.value)} placeholder="e.g. Bachelor's, O/A Levels" className={inputCls} />
                </div>
              </div>

              {/* Skills */}
              <div>
                <label className={labelCls}>Required Skills (comma-separated)</label>
                <input type="text" value={form.skills} onChange={e => f("skills", e.target.value)} placeholder="e.g. Figma, Photoshop, Canva, After Effects" className={inputCls} />
              </div>

              {/* Creative Filter */}
              <div className="bg-emerald-500/[0.04] border border-emerald-500/10 rounded-xl px-4 py-3">
                <label className="text-xs text-emerald-400 font-semibold mb-1.5 block flex items-center gap-1.5">
                  <Sparkles className="w-3 h-3" /> Target Candidate Profile (Creative Filter)
                </label>
                <input type="text" value={form.target_candidate_profile} onChange={e => f("target_candidate_profile", e.target.value)}
                  placeholder="e.g. O/A level grads, fluent English, confident communicators"
                  className={inputCls} />
                <p className="text-[10px] text-gray-500 mt-1">This becomes the ad hook — the first sentence that filters the right candidates.</p>
              </div>

              {/* Requirements */}
              <div>
                <label className={labelCls}>Requirements</label>
                <textarea value={form.requirements} onChange={e => f("requirements", e.target.value)} rows={3} placeholder="Detailed requirements..." className={`${inputCls} resize-none`} />
              </div>

              {/* Responsibilities */}
              <div>
                <label className={labelCls}>Responsibilities</label>
                <textarea value={form.responsibilities} onChange={e => f("responsibilities", e.target.value)} rows={3} placeholder="Day-to-day responsibilities..." className={`${inputCls} resize-none`} />
              </div>

              {/* Application */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Application URL</label>
                  <input type="text" value={form.application_url} onChange={e => f("application_url", e.target.value)} placeholder="https://careers.example.com" className={inputCls} />
                </div>
                <div>
                  <label className={labelCls}>Application Email</label>
                  <input type="email" value={form.application_email} onChange={e => f("application_email", e.target.value)} placeholder="hr@company.com" className={inputCls} />
                </div>
              </div>

              {/* Country + Status */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Target Country</label>
                  <select value={form.target_country} onChange={e => f("target_country", e.target.value)} className={inputCls}>
                    {Object.entries(COUNTRIES).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Status</label>
                  <select value={form.status} onChange={e => f("status", e.target.value)} className={inputCls}>
                    <option value="open">Open</option>
                    <option value="draft">Draft</option>
                    <option value="closed">Closed</option>
                  </select>
                </div>
              </div>

              {/* Tags */}
              <div>
                <label className={labelCls}>Tags (comma-separated)</label>
                <input type="text" value={form.tags} onChange={e => f("tags", e.target.value)} placeholder="e.g. urgent, tech, creative" className={inputCls} />
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-white/[0.06] sticky bottom-0 bg-[#0a0a0f]/95 backdrop-blur-sm">
              <button onClick={() => setShowForm(false)} className="px-4 py-2 rounded-xl text-sm text-gray-400 hover:text-white bg-white/[0.03] border border-white/[0.06] transition-all">
                Cancel
              </button>
              <button onClick={handleSave} disabled={saving || !form.job_title.trim()}
                className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-semibold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white transition-all disabled:opacity-40">
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Briefcase className="w-3.5 h-3.5" />}
                {editingId ? "Save Changes" : "Create Job"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
