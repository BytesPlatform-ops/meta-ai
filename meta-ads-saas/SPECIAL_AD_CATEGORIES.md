# Special Ad Categories — System Plan

**Status:** Research + implementation plan
**Last updated:** 2026-04-28
**Sources:** Meta Transparency Center, Meta Business Help Center, Jon Loomer Digital, Data Axle, Wolf Financial, AuditSocials Mar 2026 update

---

## 1. The categories that exist (2026)

Meta operates **6 Special Ad Categories** as of April 2026. Each has its own restriction profile:

| Category | What triggers it | Strict bucket? |
|---|---|---|
| **Housing** | Real estate ads, rentals, property listings, mortgage products targeting home purchases | sct) |
| **Employment** | Job listings, recruitment, hiring ads (any role) | HEC (strict) |
| **Credit** | Credit cards, loans, mortgages, BNPL (Buy Now Pay Later), crypto lending | HEC (strict) |
| **Financial Products and Services** | Trading platforms, brokerages, insurance, investment advisors, robo-advisors, crypto exchanges/wallets | Soft (less strict than HEC) |
| **Social Issues, Elections or Politics** | Political ads, advocacy, social commentary | Strict (auth required) |
| **Online Gambling and Gaming** | Sports betting, casinos, lottery (regional) | Strict (license required) |

**HEC = Housing/Employment/Credit** — the original three with strictest restrictions. Financial Products & Services (added 2025) sits one tier below HEC — more permissive but still substantially restricted.

### 2026 changes worth flagging
- **Jan 2026:** Meta consolidated dozens of detailed-interest categories. Many granular interests merged into broader pools — affects all advertisers but hits SAC campaigns harder because they already have fewer interests available.
- **Mar 2026:** Detailed targeting *exclusions* removed from existing SAC campaigns entirely. Cannot exclude interest groups anymore.
- **2026:** BNPL + crypto lending moved into the **Credit** bucket (was previously ambiguous). Klarna/Afterpay/Affirm-style ads now require Credit SAC.
- **2026:** Crypto authorization split into 3 tiers (licensed exchanges → licensed tools → unregistered/educational).
- **2026:** Financial advertiser verification mandatory in **38 countries** (up from 12 in 2024) — FCA UK, BaFin DE, SEC/FINRA US, etc.

---

## 2. What geegory

### HEC (Housing / Employment / Credit) — strictest

| Field | Behavior |
|---|---|
| `age_min` / `age_max` | **Stripped.** Forced to 18–65+. |
| `genders` | **Stripped.** All genders.ts restricted, by cat |
| `geo_locations.cities` | **Allowed**, but with **15-mile / 25-km minimum radius**. ZIP-level targeting **stripped**. |
| `geo_locations.zips` | **Stripped entirely.** |
| City-level **exclusions** | **Stripped.** Cannot exclude neighborhoods. |
| `flexible_spec.interests` (specific instruments/brands) | **Heavily stripped.** Brand interests (Robinhood, Schwab) and instrument interests (Options, Margin) removed. |
| `flexible_spec.behaviors` | Demographic + financial behaviors **stripped**. |
| `flexible_spec.demographics` | Income, net worth, education-for-finance **stripped**. |
| Detailed Targeting Exclusions | **Removed entirely** (Mar 2026). |
| Lookalike Audiences | **Disabled.** Use Special Ad Audiences only. |
| Custom Audiences | **Allowed** (CRM uploads, website pixel, engagement). |
| Detailed Targeting Expansion | **Forced ON** (cannot disable). |

### Financial Products and Services — soft tier (where Quantiva sits)

Same as HEC EXCEPT:
- Age narrowing **partially allowed** (must be 18+, but can set 25–55 for example)
- Gender narrowing **partially allowed** in some regions
- Slightly more interests survive (broad lifestyle terms like "Day trading", "Investing")

**What's still stripped under Financial SAC:**
- Brand-name interests: Interactive Brokers, TD Ameritrade, Robinhood, Coinbase, Binance, MetaTrader, TradingView
- Instrument-specific: Options strategies, Margin trading, Derivatives, Algorithmic trading
- Crypto-related interests under most regions: Cryptocurrency, Bitcoin, Blockchain (varies)
- Income / net worth demographics
- Lookalike Audiences (replaced with Special Ad Audience)

**What survives under Financial SAC (validated for 2026):**
- ✓ Day trading
- ✓ Investing / Investment (business and finance)
- ✓ Stock market
- ✓ Personal finance
- ✓ Foreign exchange market
- ✓ Online trading
- ✓ Mutual funds
- ✓ Wall Street (lifestyle/cultural)
- ✓ Stocks and bonds

### Social Issues, Elections, Politics
Different beast — requires **advertiser authorization** + **disclaimers** + **Ad Library appearance**. Out of scope for typical SaaS use.

### Online Gambling
Region-specific licensing required. Out of scope unless we're explicitly building for gambling clients.

---

## 3. Audience strategy under SAC

### What works (in priority order)

**1. Custom Audiences from first-party data** ← becomes the primary moat
- CRM email/phone uploads (match rate 30–60%)
- Website pixel visitors (PageView, ViewContent)
- App users (if applicable)
- Engagement audiences (video views, page engagement)

**2. Special Ad Audiences (restricted Lookalikes)**
- Created from Custom Audiences only
- Behavioral similarity, less precise than standard Lookalikes
- Source list of **1,000+ matched users** produces materially better SAA than smaller lists
- Use 1% for tightest match, 5–10% for scale

**3. Broad SAC-allowed interests** (the Day trading / Investing tier)
- Acts as a seed for Meta's algorithm
- Low precision on its own — relies on pixel signal to converge
- Combine with Advantage+ Audience expansion

**4. Geographic layering**
- 15-mile / 25-km minimum radius (HEC)
- Run **separate campaigns per metro** to reach specific geographies despite the radius limit
- Country-level targeting fully allowed

### What does NOT work

- ❌ Standard Lookalike Audiences (1–10%)
- ❌ Interest-only campaigns at any meaningful volume (too restricted)
- ❌ ZIP-level targeting (HEC) / Detailed targeting exclusions
- ❌ Brand competitor interests (Interactive Brokers, etc.)
- ❌ Income / wealth demographic narrowing

---

## 4. Creative compliance under Financial / Credit SAC

### Required in 2026 (per Mar 2026 Meta update)

- **Risk warnings inside the ad creative itself** — not just on the landing page
- **Standardized disclaimer templates** Meta provides per product category — use these verbatim, not custom wording
- **Educational framing** preferred over performance claims

### Prohibited (auto-rejection triggers)

- Specific return promises ("earn 12% annually", "X% APY")
- Guaranteed profits / "make money fast"
- Misleading wealth-lifestyle imagery (Lambo + beach for trading)
- Urgency around financial decisions
- Direct-message CTAs for US investment ads

### Allowed creative formats

- Static image with single CTA
- Carousel (3–5 educational cards)
- Video ads, 30–60s, featuring product screens or analyst commentary
- Lead form ads offering whitepapers/webinars

---

## 5. The economic reality

| Vertical | CPL benchmark (US) | Pixel warm-up time |
|---|---|---|
| Financial Products | $50–$300 CPL | 14–21 days minimum |
| Credit | $20–$80 CPL | Similar |
| Housing | $15–$50 CPL | Similar |
| Employment | $5–$30 CPL | Faster (more events) |

CPC: $2–$6 typical. Don't expect search-campaign efficiency.

**Budget floor:** SAC campaigns under $30/day in financial/credit usually never exit Meta's Learning Phase.

---

## 6. System plan — what we need to build

### Phase 1 — Detection (quickest win)

Auto-detect the appropriate SAC for a draft based on product/business signals so it gets set before publish, not after rejection.

**File:** `backend/app/services/special_ad_category_detector.py` *(new)*

**Logic:**

```python
def detect_special_ad_category(
    product: dict | None,
    workspace: dict,
    body_text: str,
    headline: str,
    business_description: str | None,
) -> str | None:
    """
    Returns one of:
      - "EMPLOYMENT"       — hiring ads
      - "HOUSING"          — real estate
      - "CREDIT"           — credit cards, loans, BNPL, crypto lending
      - "FINANCIAL_PRODUCTS_AND_SERVICES" — trading, brokerages, investment, insurance
      - "ISSUES_ELECTIONS_POLITICS" — out of scope, but flag for review
      - None — no SAC required
    """
```

Detection signals (in order):

1. **Hiring flag** on draft → `EMPLOYMENT`
2. **Product type / industry niche** keyword match:
   - `real_estate`, `realtor`, `mortgage`, `property` → `HOUSING`
   - `loan`, `credit_card`, `bnpl`, `installment`, `klarna`, `afterpay`, `affirm` → `CREDIT`
   - `trading`, `brokerage`, `investment`, `insurance`, `crypto`, `forex`, `algotrading`, `robo_advisor` → `FINANCIAL_PRODUCTS_AND_SERVICES`
3. **Body text + headline** keyword scan (LLM-assisted): trading platform language, financial advice, lending offers
4. **Workspace business_description** scan as fallback

LLM verification step: pass the draft + product context to a small classifier prompt and return `{category, confidence, reasoning}`. Below confidence threshold → mark as **manual review needed**, don't auto-classify.

### Phase 2 — Targeting Engine adapts to category

**File:** `backend/app/services/targeting_engine.py` *(modify)*

Add `special_ad_category` to `client_profile`. In `generate_campaign_strategy`:

- **If SAC = HEC**: skip age/gender/income demographics, query only broad allowed interests, force `geo_locations` minimum radius to 25 km when cities are involved.
- **If SAC = Financial Products**: use the validated allowlist (Day trading, Investing, Stock market, Personal finance, Foreign exchange market, Online trading, Mutual funds, Wall Street, Stocks and bonds). Reject brand/instrument interests with a known blocklist.
- **If SAC = None**: existing behavior unchanged.

Add a category-specific blocklist file:
```
backend/app/services/sac_blocklists.py
  HEC_BLOCKED_INTERESTS = ["Interactive Brokers", "Robinhood", "Coinbase", ...]
  FINANCIAL_BLOCKED_INTERESTS = ["Interactive Brokers", "Options strategies", "Margin trading", ...]
  HEC_ALLOWED_BROAD_INTERESTS = ["Investing", "Stock market", ...]
```

### Phase 3 — MCP server enforces SAC at publish

**File:** `mcp-server/server.py` *(modify `stage_advanced_campaign`)*

When `special_ad_categories` is set:

1. **Strip stripped fields automatically** before POST:
   - Always remove `age_min`, `age_max` for HEC; clamp to 18–65 for Financial
   - Remove `genders`
   - Remove `geo_locations.zips`, `geo_locations.regions` (if too narrow)
   - Force minimum radius on cities to 25 km
2. **Force Advantage+ Audience expansion ON** (`targeting_automation.advantage_audience = 1`) — Meta forces this anyway, we just match.
3. **Reject Lookalike Audience IDs** if found in `flexible_spec.custom_audiences` — log warning, replace with Special Ad Audience equivalent if available, else strip.

This pre-flight stripping prevents Meta's silent post-creation strip (which destroys our targeting without telling us) and keeps the system's stored targeting in sync with what Meta actually applied.

### Phase 4 — Audience builder for first-party data

**Already partial in codebase** — `mcp_client.create_custom_audience_from_data` exists. Needs:

- UI flow on the **Audiences** page that prompts: *"Upload CRM list to enable Special Ad Audience"*
- After upload + match, automatically build a **Special Ad Audience** off it (instead of standard Lookalike) when the workspace's drafts are flagged SAC
- New MCP tool: `create_special_ad_audience(seed_audience_id, ratio)` — calls Meta's `subtype: LOOKALIKE` with `lookalike_spec.starting_ratio: 0.0` and the **Special Ad Audience** product flag

### Phase 5 — Creative compliance gate

Before approving any draft flagged SAC:

1. Run a quick rule-based + LLM scan over the body/headline for:
   - Specific percentages ("earn 12%", "$5K/week")
   - Guaranteed-return language
   - Urgency phrases ("limited time", "act now", "make money fast")
   - Forbidden product types per category (binary options, payday loans, ICOs)
2. Auto-prepend **risk disclaimer text** for Financial/Credit:
   - `"Trading involves risk of loss. Past performance does not guarantee future results."` for Financial Products
   - Localize per region (FCA UK, SEC US, etc.)
3. Block approval until violations are fixed (with clear UI feedback explaining what tripped the rule)

### Phase 6 — Surface SAC status in UI

**File:** `frontend/src/app/dashboard/drafts/page.tsx` *(modify)*

On the draft card + modal:

- Detected SAC badge: **"Financial Products"** with info tooltip explaining what targeting will be stripped
- Pre-publish summary panel: *"Under Financial SAC, your targeting will be: ..."* — show what we'll actually send to Meta after stripping
- Compliance preview: shows the disclaimer that will be auto-appended to creative

### Phase 7 — Track which campaigns ran under SAC

Add `special_ad_category` column to `content_drafts` table (and to `campaign_logs`):

```sql
ALTER TABLE content_drafts ADD COLUMN special_ad_category text NULL;
ALTER TABLE campaign_logs ADD COLUMN special_ad_category text NULL;
```

Useful for analytics, audits, and Meta's Ad Library cross-reference (Issues/Politics ads must show up there).

---

## 7. Implementation priority

| Order | Phase | Effort | Impact |
|---|---|---|---|
| 1 | **Phase 1** — auto-detect category | Small | High — prevents auto-rejection, sets correct flag at create time |
| 2 | **Phase 3** — MCP pre-flight strip | Small | High — keeps our state in sync with Meta's, prevents silent strip surprises |
| 3 | **Phase 2** — targeting engine adapts | Medium | High — gives the AI a category-aware allowlist instead of hallucinating brand interests that get stripped |
| 4 | **Phase 5** — creative compliance gate | Medium | Medium — prevents auto-rejections from disclaimer/return-claim issues |
| 5 | **Phase 6** — surface SAC in UI | Small | Medium — user awareness, reduces "why did Meta change my targeting?" support load |
| 6 | **Phase 4** — first-party audience pipeline | Large | Medium-Long-term — required for serious scaling under SAC, but not blocking for first launches |
| 7 | **Phase 7** — DB tracking column | Trivial | Low — analytics/audit, do alongside Phase 2 |

---

## 8. Edge cases to handle

- **Mixed-content drafts** — a single draft mentions both a "trading product" and a "hiring offer". Detection must pick the *strictest* category (HEC > Financial > None).
- **Multi-country campaigns** — SAC requirements vary per country (e.g., FCA verification for UK financial ads). Treat the strictest country's rules as the floor.
- **Worldwide targeting** — for SAC-flagged drafts, force a country list instead of `WORLDWIDE`. Meta rejects worldwide SAC ads.
- **Draft regeneration** — if user changes a product from "honey" to "crypto signals" mid-funnel, re-run detection on update. Don't trust cached `special_ad_category`.
- **Test ads / personal-business mismatch** — workspace business is "Pixie AI" but draft body is about hiring guards → detection should still trigger Employment SAC on the draft.

---

## 9. Open questions / decisions needed

1. **Country-specific verification** — do we want to gate publishing for 38-country financial verification ourselves, or let Meta auto-reject? *(Likely: don't gate, surface a warning; verification is a per-account business setup, not per-campaign.)*
2. **Disclaimer source** — do we maintain our own disclaimer templates (per region, per category) or pull Meta's official ones via API? *(API may not exist — maintain our own with periodic review.)*
3. **Special Ad Audience auto-build** — silent or opt-in? *(Recommend: prompt user with one-click "Build SAA from your customer list" CTA on first SAC campaign.)*
4. **Detection confidence threshold** — what confidence level auto-classifies vs prompts user to confirm? *(Start at ≥0.85 auto, 0.6–0.85 prompt, <0.6 default to None.)*

---

## 10. Sources

- [Meta Transparency Center — Financial and Insurance Products and Services Policy](https://transparency.meta.com/policies/ad-standards/restricted-goods-services/financial-services/)
- [Meta Business Help — How to Choose a Special Ad Category](https://www.facebook.com/business/help/298000447747885)
- [Meta Business Help — Expansion of Special Ad Categories](https://www.facebook.com/business/help/510724041294968)
- [AuditSocials — Meta Ad Policy Updates March 2026](https://www.auditsocials.com/blog/meta-ad-policy-updates-2026-guide)
- [Data Axle — 2025 Meta Special Ad Categories Rules](https://www.data-axle.com/resources/blog/meta-special-ad-categories-rules/)
- [Wolf Financial — Meta Ads Financial Services Restrictions and Workarounds](https://wolf.financial/blog/meta-ads-financial-services-restrictions-targeting-workarounds)
- [Lone Beacon — Navigating Meta's Financial Special Ad Category](https://lonebeacon.com/blog/2025/06/11/how-to-navigate-metas-new-special-ad-category-as-a-financial-advisor/)
- [Conversios — Advantage+ Audience vs Detailed Targeting 2026](https://www.conversios.io/blog/meta-advantage-audience-vs-detailed-targeting-2026-guide/)
- [Jon Loomer — 83 Changes to Meta Advertising in 2025](https://www.jonloomer.com/meta-advertising-changes-2025/)
