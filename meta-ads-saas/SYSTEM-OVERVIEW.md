# BytesAd — AI-Powered Meta Ads Management Platform

## What Is This?

BytesAd is a full-stack SaaS platform that uses AI to autonomously create, manage, and optimize Meta (Facebook + Instagram) advertising campaigns. It replaces the need for a media buyer by handling the entire ad lifecycle — from generating ad copy and targeting audiences to monitoring performance and auto-optimizing spend.

**Stack:** Next.js frontend, FastAPI backend, PostgreSQL (Supabase), MCP server wrapping the Meta Marketing API, OpenAI for all AI reasoning.

**Architecture:** Docker Compose with 6 services — `frontend` (port 3000), `backend` (port 8000), `mcp-server` (port 8080), `supabase-db`, `supabase-rest`, `supabase-gateway` (port 54321).

---

## Core Workflow

```
Product → AI generates ad copy → User approves draft → AI builds targeting →
Campaign goes live on Meta → AI monitors performance → AI proposes optimizations →
User approves → AI executes changes → Loop
```

Every action that touches Meta (publishing, budget changes, pausing) requires user approval. The AI never acts autonomously on live campaigns without consent.

---

## Feature Breakdown

### 1. Multi-Workspace Architecture

The platform supports an agency model where one user can manage multiple businesses.

- **Workspaces** — Each workspace represents a separate business with its own Meta credentials, products, drafts, and campaigns
- **Workspace Switcher** — UI dropdown to switch between businesses instantly
- **Credential Isolation** — Each workspace stores its own `meta_access_token`, `meta_ad_account_id`, `meta_page_id`, and `meta_ig_actor_id`
- **Scoped Data** — Every database query is filtered by `workspace_id` so data never bleeds between businesses
- **RLS (Row Level Security)** — PostgreSQL enforces that users can only access their own workspaces at the database level

### 2. Product Catalog

Products are the foundation — every ad campaign is built around a product.

- **Full product CRUD** — Name, description, image, landing URL, price, currency, profit margin, tags, target audience
- **Product Types** — Physical, Digital, SaaS, Service (affects CTA and campaign objective selection)
- **Geo-Targeting per Product** — Target country + target cities (resolved against Meta's geo database)
- **Pixel Assignment** — Each product can have its own tracking pixel for conversion attribution
- **Profit Margin → Cost Cap** — When profit margin is set (e.g., PKR 400), the system calculates a cost cap bid (`margin × 0.7`) and sends it to Meta as `COST_CAP` bid strategy, protecting profitability
- **Variation Groups** — Shopify-style variant matrix (e.g., Size × Flavor) with individual pricing per combination
- **Product Variants** — Pricing tiers with SKU, sort order, and active/inactive toggle
- **Image Upload** — Supports both URL paste and file upload (local filesystem fallback since no Supabase Storage service)

### 3. AI Content Generation

The content generator creates ad copy tailored to each product and business context.

**How it works:**
1. User clicks "Generate Campaign" on a product (optionally provides creative direction and A/B toggle)
2. System fetches: product details, user preferences (tone, budget level), business description, website intelligence, and market research
3. OpenAI generates 1-3 ad drafts as structured JSON — headline, body text, CTA, budget, destination
4. Targeting engine runs in parallel — generates interest keywords, age ranges, geo-targeting
5. Drafts are saved with status `pending` for user review

**AI capabilities:**
- **Creative Direction Injection** — User guidance is injected as high-priority context ("Focus on health benefits, use urgency")
- **A/B Variants** — When toggled, generates semantically diverse variants with different angles/hooks
- **Smart CTA Selection** — Maps product type to optimal CTA (e.g., SaaS → `SIGN_UP`, physical product → `SHOP_NOW`, WhatsApp → `WHATSAPP_MESSAGE`)
- **Dynamic Budget Calculation** — Budget scales with ticket price: `daily_budget = max(floor, ticket_price × multiplier)` where multiplier varies by budget level (conservative/moderate/aggressive)
- **Tone Enforcement** — Respects user preference: professional, humorous, educational, or promotional
- **Anti-Buzzword Filter** — Post-processes copy to remove generic marketing filler
- **Multi-Destination Support** — Generates copy appropriate for: website landing pages, WhatsApp conversations, Instagram DMs, Instant Forms (lead gen), phone calls
- **Geo-Cultural Awareness** — When targeting specific countries, the AI adapts language, cultural references, and avoids prohibited content (e.g., Islamic market filtering for Pakistan/UAE)

**Models used:**
- `gpt-5.3-chat-latest` (Creative Writing Model) — Ad copy and marketing content
- `gpt-5.4` (Elite Reasoning Model) — Complex analysis, structured JSON outputs
- `gpt-5-mini` (Cheap Fast Model) — Keyword extraction, simple classifications

### 4. Draft Approval Workflow

Every piece of content goes through a human-in-the-loop approval process.

- **Draft States:** `pending` → `approved` → `publishing` → `active` (or `rejected` / `failed`)
- **Draft Card UI** — Shows headline, body text, image preview, CTA, proposed budget, targeting spec, AI reasoning
- **Edit Before Approve** — User can modify any field (copy, budget, targeting) before approving
- **A/B Variant View** — Side-by-side comparison of generated variants
- **Destination Preview** — Shows where the ad will send users (website URL, WhatsApp number, lead form)
- **Targeting Visualization** — Displays interest keywords, age range, locations, placement preferences
- **Real-Time Status Polling** — When drafts are in `approved`/`publishing` state, the page auto-polls every 5 seconds with pulsing animated badges, auto-stops when settled
- **Type Toggle** — Click the type badge to switch between organic and paid on pending drafts

### 5. Ad Execution Pipeline

When a draft is approved, the ad executor publishes it to Meta.

**Paid ad flow:**
1. Resolve workspace credentials (access token, ad account ID, page ID)
2. Generate campaign strategy via targeting engine (interests, geo, demographics)
3. Stage Advantage+ campaign via MCP server:
   - Create campaign with correct objective (SALES, LEADS, ENGAGEMENT, TRAFFIC)
   - Create ad set with targeting, budget, and bid strategy
   - Create ad with creative (image/video + copy)
4. Update draft with `meta_campaign_id`, `meta_adset_id`, `meta_ad_id`
5. Set draft status to `active`

**Organic post flow:**
1. Upload image to Facebook page
2. Publish as page photo post with caption
3. Track engagement

**Destination routing:**
- Website → `OUTCOME_SALES` objective, `SHOP_NOW` CTA
- WhatsApp → `OUTCOME_ENGAGEMENT` objective, `WHATSAPP_MESSAGE` CTA
- Instagram DM → `OUTCOME_ENGAGEMENT` objective, `MESSAGE_PAGE` CTA
- Instant Form → `OUTCOME_LEADS` objective, `SUBSCRIBE` CTA, `lead_gen_form_id` in creative
- Phone Call → `OUTCOME_LEADS` objective, `CALL_NOW` CTA

**Cost cap injection:** When product has `profit_margin`, the executor calculates `bid_amount = margin × 0.7` and sets `bid_strategy: COST_CAP` on the ad set.

**Pixel injection:** Executor resolves pixel from product (not ad account) and injects `tracking_specs` + `promoted_object.pixel_id` + `custom_event_type` into the ad set.

### 6. Campaign Performance Dashboard

Real-time visibility into all running campaigns.

- **Account Overview** — Total spend (30d), active campaigns count, average ROAS
- **Campaign List** — Each campaign shows: name, status, objective, budget type, daily spend, results, ROAS, verdict
- **Filter Tabs** — All / Active / Paused
- **Dynamic Result Labels** — Columns adapt based on campaign objective:
  - Sales campaigns → "Purchases", "ROAS", "Revenue"
  - Lead campaigns → "Leads", "CPL"
  - Engagement campaigns → "Conversations", "Cost/Conv"
  - Traffic campaigns → "Clicks", "CPC"
- **Verdict System** — AI assigns each campaign a verdict based on account baselines:
  - `scale` — 20% better than account average
  - `hold` — Within baseline ±20%
  - `underperforming` — 30% worse than baseline
  - `kill` — High spend with zero results
  - `no_data` — Insufficient data
- **Page Posts Section** — Recent organic Facebook page posts with engagement metrics

### 7. Campaign Detail View

Deep drill-down into individual campaign performance.

- **Campaign Metadata** — Name, status, objective, budget, bid strategy, created date
- **Time-Series Charts** — Daily spend, results, and ROAS plotted with Recharts
- **Date Preset Toggle** — Today, Last 7d, Last 30d, Last 90d, Maximum
- **"Today" Data Merge** — Meta excludes today from `last_Xd` presets, so the system fetches `today` separately and merges it in
- **Ad-Level Breakdown** — Table showing each ad's spend, results, ROAS, and status
- **Demographic Breakdowns** — Age, gender, and placement performance splits
- **Conversion Funnel** — Visual funnel from impressions → clicks → conversions

### 8. Analytics Page

Historical performance trends across all campaigns.

- **Daily Time-Series** — Aggregated spend, results, ROAS across the account
- **Campaign Breakdown** — Per-campaign contribution to totals
- **Dominant Type Detection** — Picks the most frequent result type across campaigns (not just binary leads/purchases)
- **Date Range Selection** — Custom date ranges for historical analysis
- **Dynamic Labels** — Same objective-aware labeling as campaigns page

### 9. AI Optimization Co-Pilot

The co-pilot analyzes campaign performance and generates optimization proposals.

**Analysis pipeline:**
1. Fetch deep ad insights from Meta (30d lifetime data, per-ad metrics)
2. Calculate account baselines (average ROAS, CPL, CPA)
3. Detect ad maturity (learning phase vs. mature — based on 50+ conversions threshold)
4. Send insights to OpenAI with baseline context
5. Generate 5-10 structured optimization proposals with impact scores

**Proposal types:**
- `increase_budget` — Scale winning campaigns
- `decrease_budget` — Reduce spend on underperformers
- `pause_entity` — Kill campaigns/ads with zero results
- `refresh_creative` — Generate new ad copy for fatigued creatives (AI writes the new copy inline)
- `expand_audience` — Create lookalike audiences from converters
- `add_retargeting` — Create retargeting audiences from pixel/engagement data
- `prune_placements` — Remove underperforming placements
- `apply_cost_cap` — Add cost cap bidding for profitability protection
- `duplicate_winner` — A/B test winning ads with mutations
- `consolidate` — Merge overlapping campaigns to improve signal

**Each proposal includes:**
- `entity_id` / `entity_type` — What campaign/adset/ad to modify
- `current_value` — What it is now (e.g., budget: $30/day)
- `proposed_value` — What the AI suggests (e.g., budget: $50/day)
- `ai_reasoning` — Why (e.g., "ROAS is 3.2x, 40% above account average. Scale to capture more conversions.")
- `impact_score` — 1-10 scale of expected impact
- `status` — pending → approved → applied (or rejected/failed)

**Execution:** When user clicks "Approve", the system executes the change via MCP (budget update, status change, creative swap, audience creation).

### 10. Account Audit & AI Strategy Report

Comprehensive AI analysis of the entire ad account.

**Audit pipeline:**
1. Fetch 30-day ad performance data with demographic breakdowns
2. Identify winning ads (high ROAS) and losing ads (high spend, no results)
3. Analyze audience demographics (age, gender, placement performance)
4. Send everything to OpenAI for strategic analysis
5. Generate comprehensive markdown strategy report

**Report includes:**
- Account health score (0-100, rendered as SVG ring)
- Quick wins (immediate actions for improvement)
- Winning patterns (what's working and why)
- Losing patterns (what to stop doing)
- Audience insights (best-performing demographics)
- Budget allocation recommendations
- Creative direction suggestions
- Competitive positioning assessment

**Actionable proposals:** "Generate Action Plan" button converts report recommendations into structured co-pilot proposals (pause, scale, shift budget, A/B test) that can be approved and executed individually.

### 11. Targeting Engine

AI-powered audience targeting generation.

**Pipeline:**
1. Extract keywords from product description and business context
2. Use OpenAI to identify buyer persona and generate 5 high-intent interest keywords
3. Validate interests against Meta's catalog via MCP (`search_meta_interests`)
4. Meta sorts by `audience_size_upper_bound`, system picks broadest match per keyword
5. Determine age range and gender based on product type
6. Resolve geographic locations (country → cities) via MCP (`resolve_geo_locations`)
7. Check audience data readiness: if 100+ customers exist for this niche → use Lookalike Audience, otherwise → interest-based cold targeting

**Smart routing:**
- **Cold Start** (no customer data) → Interest-based targeting with 3-5 broad keywords
- **Data Rich** (100+ customers) → Custom Audience + 1% Lookalike + interest expansion
- **Retargeting** → Pixel visitors + post/video engagers + lead form openers

**Cultural awareness:**
- Islamic market blocklist (alcohol, gambling, adult content keywords blocked for PK, UAE, SA, etc.)
- Geo-cultural keyword adaptation (country-specific slang, references, seasonal events)
- Language-appropriate copy suggestions

### 12. Audience Management

Build and manage custom audiences for precision targeting.

- **CSV Customer Import** — Upload email/phone lists with niche tagging
- **Niche-Scoped Segmentation** — Customers tagged by product/niche to prevent cross-contamination (e.g., "honey buyers" vs "chatbot leads")
- **Custom Audience Creation** — Hash PII (SHA-256) and upload to Meta for matching
- **Lookalike Audiences** — Create 1% LAL from custom audiences (requires 100+ customers)
- **Retargeting Audiences** — Pixel visitors, video viewers, post engagers, lead form openers
- **Exclusion Audiences** — Exclude previous converters to avoid wasted spend
- **LAL Readiness Indicator** — Dashboard shows customer count per niche and whether it meets the 100+ threshold
- **Pixel Event Visualization** — See which conversion events are firing and their attribution

### 13. Lead Generation

Full lead gen pipeline from form creation to lead download.

- **AI Lead Form Builder** — 3-tab modal: AI Build (auto-generates optimal fields), Saved (reuse templates), Manual (build from scratch)
- **AI Form Generation** — Analyzes product, ad copy, and target audience to suggest optimal form fields (name, email, phone, custom questions)
- **Meta Form Creation** — Creates Instant Form on Meta via API, returns form ID for ad linking
- **Lead Download** — Fetch all collected leads as JSON or CSV export
- **Lead Preview Table** — Expandable table showing submitted responses with dynamic columns based on form fields
- **Campaign Context** — Each form shows which campaign it belongs to and that campaign's status (active/paused)
- **Normalized Column Mapping** — Handles Meta's inconsistent field ordering by building a canonical column list across all leads

### 14. Automated Rules

Set-and-forget rules that protect budget and scale winners.

- **Kill Rules** — Automatically pause a campaign when spend exceeds threshold without achieving minimum results
  - Example: "Pause if spend > $50 and purchases < 1"
- **Scale Rules** — Automatically increase budget when ROAS exceeds threshold
  - Example: "Increase budget by 20% if ROAS > 3.0"
- **Rule Toggle** — Enable/disable rules without deleting them
- **Rule Management** — Create, list, toggle, and delete rules per ad account

### 15. Content Strategy Engine

AI-powered market research and campaign planning.

- **Market Research** — Analyzes niche trends, competitor positioning, and content gaps
- **Strategy Generation** — Produces structured content calendar recommendations
- **Angle Analysis** — Identifies underexploited angles and messaging opportunities
- **Competitor Research** — Fetches competitor ad creatives from Meta's Ad Library via MCP
- **Strategy History** — View and compare multiple strategies over time
- **Approval Workflow** — Strategies can be approved to guide future content generation

### 16. Website Intelligence

Automatic business context extraction from websites.

- **Website Scraping** — Uses Tavily Extract (via MCP) to scrape business website
- **Multi-Page Support** — Scrapes main URL plus additional pages configured in settings
- **Intelligence Storage** — `website_intel` JSONB stored per workspace/preferences
- **Context Injection** — Scraped data is fed into content generator and strategy engine LLM prompts for more relevant ad copy
- **Auto-Scrape** — Triggers automatically when user saves website URL in preferences

### 17. Pixel & Conversion Tracking

Full pixel lifecycle management.

- **Pixel Creation** — Create new Meta pixel directly from the platform
- **Base Code** — Copy-paste pixel base code snippet with install guidance
- **Product-Level Assignment** — Pixels are assigned per product (not per account), enabling multi-product tracking
- **Event Tracking** — ViewContent, AddToCart, InitiateCheckout, Purchase, Lead, CompleteRegistration
- **Tracking Specs Injection** — `tracking_specs` automatically injected into ad sets during campaign creation
- **Conversion Event Mapping** — `conversion_event` field on drafts maps to `promoted_object.custom_event_type` on Meta
- **SmartTrackingCard** — UI component showing pixel events, conversion attribution, and install status

### 18. Settings & Onboarding

Configuration and first-time setup.

**Setup Wizard (4 steps):**
1. **Business Info** — Name, description, target audience
2. **Posting Frequency** — Daily, 3x/week, Weekends only, Manual only
3. **Content Tone** — Professional, Humorous, Educational, Promotional
4. **Ad Budget Level** — Conservative ($10/day), Moderate ($30/day), Aggressive ($50/day), Custom

**Settings Page:**
- Meta connection management (OAuth or manual API token)
- Business info editing
- Website URL with auto-scrape
- Target country and city selection
- Ad placement preferences
- WhatsApp number for messaging campaigns
- Content tone and budget preferences
- Additional website pages for deeper scraping

### 19. Meta Account Connection

Two methods to connect Meta ad accounts.

- **OAuth Flow** — Standard Meta OAuth2 with token exchange, account discovery, and automatic ad account registration
- **Manual Connect** — Paste access token directly, system validates via Graph API, fetches ad accounts, and upserts credentials
- **Account Picker** — When multiple ad accounts exist, modal lets user select which one to use
- **Page Picker** — Select which Facebook Page to use for publishing
- **Social Identity Resolution** — Fetches Instagram actor ID for Instagram placement support
- **Token Management** — Stores token with expiration tracking

### 20. Campaign Execution Details

What happens under the hood when the system creates a campaign on Meta.

**Campaign structure:** Campaign → Ad Set → Ad (Meta's 3-tier hierarchy)

**Objectives supported:**
| Objective | When Used | Optimization Goal |
|---|---|---|
| OUTCOME_SALES | Website conversions (purchase, add to cart) | Conversions |
| OUTCOME_LEADS | Lead forms, messaging conversations | Lead generation |
| OUTCOME_ENGAGEMENT | Post engagement, Instagram DM, WhatsApp | Messaging conversations |
| OUTCOME_TRAFFIC | Link clicks, landing page views | Link clicks |
| OUTCOME_AWARENESS | Brand awareness, reach | Reach |

**Bidding strategies:**
- `LOWEST_COST_WITHOUT_CAP` — Default, Meta optimizes for most results
- `COST_CAP` — When profit margin is set, caps cost per result at `margin × 0.7`

**Creative formats:**
- Image ads (link_data with image_hash)
- Video ads (video_data with video_id + thumbnail)
- Page post boost (existing organic post)
- Lead form ads (with inline Instant Form)

**Targeting layers:**
- Interests (5 validated Meta interests)
- Demographics (age, gender)
- Geographic (country, cities)
- Placements (Facebook Feed, Instagram Feed, Stories, Reels, Audience Network)
- Custom/Lookalike audiences (when data is available)
- Advantage Audience toggle (Meta's auto-expansion)

---

## MCP Server — Meta API Abstraction Layer

The MCP (Model Context Protocol) server wraps the entire Meta Marketing API behind a tool-based interface. The backend never calls Meta directly — all Meta operations go through MCP.

**21+ tools including:**

| Tool | Purpose |
|---|---|
| `saas_account_overview` | Account health snapshot (30d metrics) |
| `saas_list_campaigns` | List campaigns with 7d performance |
| `saas_campaign_detail` | Full campaign metadata + daily time-series |
| `saas_time_series_insights` | Daily performance trends |
| `stage_advanced_campaign` | Create complete Advantage+ campaign |
| `update_adset_budget` | Change ad set budget |
| `update_adset_targeting` | Modify audience targeting |
| `update_entity_status` | Pause/resume campaigns, ad sets, or ads |
| `shift_budget_between_entities` | Reallocate budget between campaigns |
| `get_account_audit_data` | Deep audit data for AI analysis |
| `get_deep_ad_insights` | Lifetime per-ad metrics |
| `validate_meta_interests` | Check interests against Meta's catalog |
| `search_meta_interests` | Search Meta's interest library |
| `resolve_geo_locations` | Resolve city names to Meta geo IDs |
| `search_geo_cities` | Search cities in a country |
| `create_custom_audience_from_data` | Upload hashed PII for custom audience |
| `create_lookalike_audience` | Create 1% LAL from seed audience |
| `create_lead_form` | Create Meta Instant Form |
| `list_leadgen_forms` | List forms from page/account |
| `get_leadgen_leads` | Download submitted leads |
| `upload_ad_image` | Upload image to ad account library |
| `upload_ad_video` | Upload video to ad account library |
| `publish_page_photo` | Publish organic photo post to page |
| `fetch_competitor_ads` | Research competitor creatives |
| `scrape_website` | Extract business intelligence from URL |
| `fetch_social_identities` | Get Instagram actor ID for placements |
| `fetch_ad_account_pixels` | List pixels in account |
| `get_pixel_events` | Pixel event data |
| `create_pixel` | Create new Meta pixel |
| `duplicate_ad_with_mutations` | A/B test winning ads |

---

## Database Schema

**17 tables** across user management, content, campaigns, audiences, and optimization:

| Table | Purpose |
|---|---|
| `users` | Auth mirror with profile and plan |
| `workspaces` | Multi-business workspace with Meta credentials |
| `ad_accounts` | Connected Meta ad accounts |
| `user_preferences` | Setup wizard results + configuration |
| `products` | Product catalog with pricing and targeting |
| `product_variants` | Pricing tiers per product |
| `content_drafts` | AI-generated ad content awaiting approval |
| `content_strategies` | AI market research and campaign plans |
| `customers` | Customer database for custom audiences |
| `meta_audiences` | Registry of Meta audiences per product |
| `lead_forms` | Saved lead form templates |
| `campaign_logs` | Audit trail of all campaign actions |
| `campaign_suggestions` | HITL optimization suggestions |
| `optimization_proposals` | AI-generated optimization proposals |
| `account_audits` | AI account health reports |

All tables enforce Row Level Security — users can only access data within their own workspaces.

---

## Key Design Decisions

1. **Human-in-the-loop everywhere** — AI generates, human approves. No autonomous execution on live ad spend.
2. **Product-centric** — Everything flows from products. Targeting, copy, budget, and pixel tracking are all derived from product context.
3. **Workspace isolation** — Agency-ready from day one. Every query is workspace-scoped.
4. **MCP abstraction** — Backend never calls Meta directly. All Meta operations are MCP tool calls, making the Meta API swappable.
5. **Baseline-aware verdicts** — Performance judgments are relative to the account's own history, not arbitrary thresholds.
6. **Data-rich vs cold-start routing** — System automatically chooses targeting strategy based on available customer data.
7. **Cost cap from profit margin** — Profitability protection is built into the bidding strategy, not just a reporting metric.
