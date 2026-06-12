# 1-Click Hiring Ads — Feature Documentation

## Overview

Hiring Ads is a dedicated vertical in the Meta Ads SaaS platform that lets users create job listings and generate HEC-compliant Meta recruitment ads with one click. Because Meta enforces strict **Housing, Employment, Credit (HEC)** policies on job ads — banning all age, gender, and demographic targeting — this feature relies entirely on **Creative Filtering**: writing ad hooks that naturally attract the right candidates and repel unqualified ones.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     FRONTEND                                  │
│  /dashboard/hiring/page.tsx                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │ Job Cards   │  │ Create/Edit  │  │ "Generate Hiring Ads" │ │
│  │ Grid View   │  │ Modal (CRUD) │  │ Button per card       │ │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬───────────┘ │
│         │                │                      │             │
│         ▼                ▼                      ▼             │
│  GET /hiring/     POST/PATCH /hiring/    POST /generate/drafts│
│                                          ?job_id=xxx          │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     BACKEND                                   │
│                                                               │
│  routes/hiring.py ──── CRUD for jobs table                    │
│  routes/generate.py ── Loads job record → builds hiring_data  │
│  services/content_generator.py ── Hiring prompt branch        │
│  services/ad_executor.py ── Injects EMPLOYMENT category       │
│                                                               │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     MCP SERVER                                │
│  stage_advanced_campaign()                                    │
│  - special_ad_categories: ["EMPLOYMENT"]                      │
│  - Strips age/gender/demographic targeting from adset         │
│  - Creates campaign → adset → creative → ad                   │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
                    Meta Marketing API
                  (HEC-compliant campaign)
```

---

## Database Schema

### `jobs` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `user_id` | UUID | Owner (FK → users) |
| `workspace_id` | UUID | Workspace (FK → workspaces) |
| `job_title` | TEXT | e.g. "Full Stack Developer" |
| `department` | TEXT | e.g. "Engineering", "Sales" |
| `company_name` | TEXT | Override workspace business name |
| `company_logo_url` | TEXT | Logo for ad creative |
| `work_mode` | TEXT | `onsite` \| `remote` \| `hybrid` |
| `location` | TEXT | e.g. "Lahore, Pakistan" |
| `employment_type` | TEXT | `full_time` \| `part_time` \| `contract` \| `internship` \| `freelance` |
| `salary_min` | NUMERIC | Minimum salary |
| `salary_max` | NUMERIC | Maximum salary |
| `salary_currency` | TEXT | PKR, USD, GBP, etc. |
| `salary_period` | TEXT | `month` \| `year` \| `hour` \| `project` |
| `perks` | TEXT | e.g. "Medical + Transport + Lunch" |
| `experience_level` | TEXT | `entry` \| `mid` \| `senior` \| `lead` \| `executive` |
| `experience_years_min` | INT | Minimum years required |
| `experience_years_max` | INT | Maximum years (optional) |
| `education_level` | TEXT | e.g. "Bachelor's", "O/A Levels" |
| `skills` | TEXT[] | Array: ["React", "Node.js", "Docker"] |
| `target_candidate_profile` | TEXT | Creative filter hook — becomes the ad's first sentence |
| `requirements` | TEXT | Detailed requirements |
| `responsibilities` | TEXT | Day-to-day responsibilities |
| `application_url` | TEXT | External apply link |
| `application_email` | TEXT | Email to apply |
| `target_country` | TEXT | ISO code (PK, US, etc.) |
| `target_cities` | JSONB | Optional city-level targeting |
| `status` | TEXT | `open` \| `closed` \| `draft` |
| `is_active` | BOOLEAN | Soft delete flag |
| `tags` | TEXT[] | Searchable tags |

### `content_drafts` additions

| Column | Type | Description |
|--------|------|-------------|
| `is_employment_ad` | BOOLEAN | Flags the draft for HEC treatment |
| `hiring_data` | JSONB | Snapshot of hiring fields used for generation |
| `job_id` | UUID | Links draft back to the source job |

---

## Generation Flow (Step by Step)

### 1. User clicks "Generate Hiring Ads" on a job card

Frontend (`hiring/page.tsx`) calls:
```
POST /api/v1/generate/drafts?count=3&job_id={job.id}
Body: { hiring_data: { job_title, target_candidate_profile, salary_and_perks, ... } }
```

### 2. Backend loads the full job record

`routes/generate.py` — When `job_id` is present, the backend **always** loads the full job from the `jobs` table, regardless of what the frontend sent. This ensures `target_country`, `skills`, `work_mode`, and all other fields come from the database (single source of truth).

```python
# Extracted from the job record:
hiring_data = {
    "job_title": job["job_title"],
    "target_candidate_profile": "...",
    "salary_and_perks": "PKR 120000 – 300000 + Medical + ...",
    "requirements": "...",
    "responsibilities": "...",
    "target_country": "PK",        # ← Critical for geo targeting
    "location": "Lahore, Pakistan",
    "work_mode": "hybrid",
    "employment_type": "full_time",
    "company_name": "Bytes Platform",
    "skills": ["React", "Next.js", ...],
    "experience_level": "mid",
    "education_level": "Bachelor in CS/SE",
}
```

### 3. Content Generator — Hiring Branch

`services/content_generator.py` detects `hiring_data` is present and:

**a) Overrides target_country early** (before any research/targeting runs):
```python
if hiring_data and hiring_data.get("target_country"):
    target_country = hiring_data["target_country"]  # PK, not workspace default
```

**b) Skips the hybrid targeting pipeline entirely:**
```python
if hiring_data:
    # Skip — the business-profile targeting picks employer interests
    # (Shopify, QuickBooks) which is wrong for job ads
    pass
elif access_token_for_research:
    # Normal flow: LLM search terms → Meta API interest grounding
    ...
```

**c) Uses a dedicated hiring prompt** with 3 steps:

#### Step 1 — Research Analysis
The LLM analyzes what makes top-performing recruitment ads in 2024-2026:
- Salary transparency
- Clear hooks
- Company culture signals
- Mobile readability

#### Step 2 — Creative Filtering (HEC Compliance)
Since Meta bans demographic targeting for employment ads, the **first sentence of the ad IS the targeting**:

> "Your FIRST SENTENCE (the Hook) MUST call out the specific target_candidate_profile so that unqualified people naturally scroll past."

Example hooks:
- "O/A Level grads who can hold a conversation in English — we're hiring."
- "Designers who think Figma is a lifestyle, not just a tool."
- "Developers who ship fast, write clean code, and can own features end-to-end."

#### Step 3 — Generate 3 Distinct Angles
Always produces exactly 3 drafts:

| Angle | Focus | Appeal |
|-------|-------|--------|
| **Culture & Perks** | Why it's a great place to work — salary, benefits, team vibe | Emotional / lifestyle |
| **Direct & Transparent** | Bullet-point requirements and responsibilities, no fluff | Pragmatic / self-qualifying |
| **Career Growth** | Learning, mentorship, stepping-stone opportunities | Ambitious / long-term thinkers |

### 4. Draft Records Created

Each draft is saved to `content_drafts` with:
- `is_employment_ad = True`
- `hiring_data = {snapshot of job fields}`
- `job_id = {source job UUID}`
- `target_country = {from job, e.g. "PK"}`
- `draft_type = "paid"`
- `cta_type = "APPLY_NOW"` or `"LEARN_MORE"` (never SHOP_NOW)

---

## Interest Targeting Flow

### Why Hiring Ads Need Different Targeting

Normal product ads use the **Hybrid Targeting Pipeline**:
1. LLM analyzes business profile → generates buyer persona search terms
2. Search Meta's Interest API with those terms
3. Filter forbidden industry terms
4. Sniper LLM picks top 5 niche interests

This pipeline targets **customers/buyers** — people interested in the business's products. For a web dev agency, it finds interests like "Shopify", "Entrepreneurship", "E-commerce" — people who BUY websites.

**For hiring ads, we need to target JOB SEEKERS** — people looking for work. The buyer-persona pipeline would pick completely wrong interests.

### How Hiring Interest Targeting Works — Candidate Ecosystem Matrix

We do NOT target job-seekers. We target **passive talent** — people who are excellent at their job and not actively looking. The LLM acts as a **Behavioral Analyst** using a 3-pillar **Candidate Ecosystem Matrix** that works for ANY role — from Software Engineer to HR Manager to Head Chef.

```
┌──────────────────────────────────────────────────────┐
│      CANDIDATE ECOSYSTEM MATRIX (Chain-of-Thought)    │
│                                                       │
│  1. Hybrid targeting pipeline: SKIPPED                │
│     (would pick business-owner interests)             │
│                                                       │
│  2. LLM acts as "Elite Behavioral Analyst"            │
│     Maps the candidate's professional world           │
│     using 3 pillars, generates 12-15 terms,           │
│     picks best 5                                      │
│                                                       │
│  ❌ ANTI-DESPERATION RULE (always enforced):          │
│     BANNED: "Job hunting", "Indeed", "Resume",        │
│     "Career development", "LinkedIn" (too broad)      │
│                                                       │
│  PILLAR 1 — TOOLS & METHODOLOGIES                     │
│  "What do they USE daily?"                            │
│     ✅ IT: "React.js", "Docker", "Jira"              │
│     ✅ Sales: "HubSpot", "Salesforce"                │
│     ✅ HR/Ops: "SAP", "Six Sigma", "Workday"         │
│     ✅ Trades: "AutoCAD", "OSHA"                     │
│     ✅ Medical: "Epic Systems", "EHR"                │
│     ✅ Finance: "Bloomberg Terminal", "ACCA"         │
│                                                       │
│  PILLAR 2 — THE WATERCOOLER                          │
│  "What do they CONSUME/FOLLOW?"                       │
│     ✅ "Harvard Business Review" (management)        │
│     ✅ "TechCrunch" (tech)                           │
│     ✅ "Stack Overflow" (developers)                 │
│     ✅ "IEEE" (engineers)                            │
│     ✅ "PEC" / "PMDC" / "ICAP" (Pakistan local)     │
│     ✅ "Cannes Lions" (advertising)                  │
│                                                       │
│  PILLAR 3 — THE TITANS                               │
│  "Who do they LOOK UP TO?"                            │
│     ✅ "McKinsey & Company" (consulting)             │
│     ✅ "Ogilvy" (advertising)                        │
│     ✅ "Y Combinator" (startups)                     │
│     ✅ "Goldman Sachs" (finance)                     │
│     ✅ "Google" (tech)                               │
│     ✅ "Mayo Clinic" (healthcare)                    │
│                                                       │
│  3. Best 5 blended terms → stored in targeting_spec  │
│                                                       │
│  4. At execution: ad_executor strips age/gender       │
│     and injects special_ad_categories                 │
│                                                       │
└──────────────────────────────────────────────────────┘

Why 3 pillars instead of just "Tools of the Trade"?
- Tools alone works for technical roles (devs, designers)
- But fails for management/soft-skill roles (HR Manager, COO)
- Watercooler + Titans fill the gap — an HR Manager may not
  use a specific tool, but they read HBR and follow McKinsey
```
```

### Interest Validation

The LLM-suggested interests go through the same **Geo-Cultural Validation Loop** as normal ads:
1. AI suggests interests like "Job hunting", "Career development"
2. Each keyword is searched against Meta's Interest API via MCP `search_meta_interests`
3. Only interests that exist in Meta's taxonomy are kept (with real interest IDs)
4. Validated interests are stored in `targeting_spec` JSONB on the draft

---

## Ad Execution Flow (What Happens at Publish)

When a hiring draft is approved and scheduled:

### ad_executor.py
1. Reads `is_employment_ad = True` from the draft
2. **Strips age/gender** from the targeting dict:
   ```python
   targeting.pop("age_min", None)
   targeting.pop("age_max", None)
   targeting.pop("genders", None)
   ```
3. Injects `special_ad_categories`:
   ```python
   params["special_ad_categories"] = json.dumps(["EMPLOYMENT"])
   ```
4. Passes everything to MCP `stage_advanced_campaign`

### MCP Server (stage_advanced_campaign)
1. Parses `special_ad_categories: ["EMPLOYMENT"]`
2. Creates campaign with:
   ```python
   campaign_payload = {
       "objective": "OUTCOME_...",
       "special_ad_categories": ["EMPLOYMENT"],  # ← HEC flag
       ...
   }
   ```
3. **Double-strips** age/gender/demographics from adset targeting (safety net):
   ```python
   if _special_cats:
       targeting_obj.pop("age_min", None)
       targeting_obj.pop("age_max", None)
       targeting_obj.pop("genders", None)
       targeting_obj.pop("relationship_statuses", None)
       targeting_obj.pop("education_statuses", None)
   ```
4. Creates adset → creative → ad as normal

### Result
The published campaign on Meta will:
- Have `special_ad_categories: ["EMPLOYMENT"]` (Meta compliance)
- Have NO age, gender, or zip code targeting (HEC rules)
- Use only broad interests + geo targeting
- Use the creative-filtered hook as the primary targeting mechanism

---

## File Map

| Component | Path |
|-----------|------|
| Frontend — Hiring page | `frontend/src/app/dashboard/hiring/page.tsx` |
| Frontend — Sidebar entry | `frontend/src/components/layout/Sidebar.tsx` |
| Frontend — API client | `frontend/src/lib/api.ts` (listJobs, createJob, etc.) |
| Backend — Hiring CRUD | `backend/app/api/routes/hiring.py` |
| Backend — Generate endpoint | `backend/app/api/routes/generate.py` |
| Backend — Content generator | `backend/app/services/content_generator.py` |
| Backend — Ad executor | `backend/app/services/ad_executor.py` |
| Backend — Main router | `backend/app/main.py` |
| MCP — Campaign staging | `mcp-server/server.py` (stage_advanced_campaign) |
| DB Schema | `supabase/docker/init/01-app-schema.sql` |

---

## Key Design Decisions

1. **Creative Filtering > Demographic Targeting**: Meta bans age/gender for jobs. Instead of fighting the platform, we make the ad copy itself act as the filter. The `target_candidate_profile` field becomes the ad's first sentence — a hook that naturally attracts qualified candidates and repels others.

2. **Skip Hybrid Targeting for Hiring**: The normal targeting pipeline analyzes the business profile to find customer interests. For hiring, this produces wrong results (employer interests vs. job-seeker interests). We skip it entirely and let the LLM suggest job-seeker-focused interests directly.

3. **Job Record as Source of Truth**: The frontend sends partial hiring data, but the backend always loads the full job record from the DB. This ensures target_country, skills, and all fields are consistent.

4. **3 Angles, Always**: Every hiring generation produces exactly 3 drafts — Culture & Perks, Direct & Transparent, Career Growth — giving the recruiter creative variety without decision paralysis.

5. **Double-Strip Safety**: Age/gender targeting is removed both in `ad_executor.py` AND in the MCP server's `stage_advanced_campaign`. Even if one layer is bypassed, the other catches it.
