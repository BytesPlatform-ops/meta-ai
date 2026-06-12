# SAC Implementation — Session Handoff

**Last session:** 2026-04-28
**Status:** Phases 1+2 shipped, draft-gen retry coded but unverified
**Next session entrypoint:** verify draft-gen retry, then Phase 3

---

## ✅ What's done

### Phase 1 — SAC Detector (LLM-driven, generic)

**File:** `backend/app/services/special_ad_category_detector.py`

- Single classifier function `detect_special_ad_category(DraftContext)` — no hardcoded keyword lists
- Catalog of all 6 Meta categories with official definitions fed to LLM at prompt time
- Returns `SACDecision(category, confidence, should_auto_apply, reasoning, region_notes, raw)`
- Confidence thresholds: `_CONFIDENCE_AUTO_APPLY = 0.70`, `_CONFIDENCE_SUGGEST = 0.50` (tuned down from 0.85 — was too strict)
- Strictness ranking: HEC > Financial > None
- Region-aware (FCA/UK, BaFin/DE, SEC/FINRA/US notes)
- B2B exception in prompt (CRM-for-realtors ≠ Housing)
- Helper `detect_for_draft(draft, workspace, product, preferences)` for backend use

### Phase 2 — SAC at draft creation + UI

**File:** `backend/app/services/content_generator.py`
- Detection runs BEFORE search-terms LLM, result cached in `_sac_decision`
- Search-terms system prompt gets `_sac_prompt_suffix` appended when SAC ≥ 0.5 confidence
- The suffix tells the LLM: "Meta strips brand-name and instrument-specific interests. Suggest only broad lifestyle/behavior categories (Day trading, Investing, Personal finance, Stock market). NO Robinhood/TradingView/Bloomberg/CNBC."
- Each draft `record` gets `special_ad_category`, `_confidence`, `_reasoning` saved at insert time

**File:** `backend/app/services/ad_executor.py`
- Reads cached `draft.special_ad_category` first → no LLM call at publish if already detected
- Falls back to fresh detection for legacy drafts → persists result back to DB
- Both pipelines wired (multi-draft anchor at `~line 970` + legacy single-draft at `~line 1545`)
- `_build_base_stage_params` made async for the SAC await call

**File:** `frontend/src/app/dashboard/drafts/page.tsx`
- New `SAC_DISPLAY` map: code → `{label, color}`
- Badge between TypeBadge and StatusBadge
- Hover tooltip with reasoning + confidence %

**File:** `backend/app/api/routes/drafts.py`
- `target_country`, `destination_url` added to `UpdateDraftPayload` schema + whitelist loop
- Failed drafts can be updated (status `pending`/`failed`)
- Status transitions validated: only `failed → pending` allowed via update endpoint

**DB columns added:**
```sql
ALTER TABLE content_drafts ADD COLUMN special_ad_category text;
ALTER TABLE content_drafts ADD COLUMN special_ad_category_confidence numeric(3,2);
ALTER TABLE content_drafts ADD COLUMN special_ad_category_reasoning text;
```

### Other fixes shipped this session
1. **API enum fix:** `FINANCIAL_PRODUCTS_AND_SERVICES` → `FINANCIAL_PRODUCTS_SERVICES` (no AND, per Meta docs)
2. **Multi-country support:** `draft.target_country` column read with highest priority in `_build_client_profile`
3. **City normalizer:** handles `"[]"` JSONB string vs `[]` array (was triggering bad cities path)
4. **Workspace isolation:** `user_preferences` queried with `workspace_id` filter, not just `user_id`
5. **Multi-country chip UI** in draft modal with add/remove
6. **Pixels page** at `/dashboard/pixels` with create / set-active / events / install-snippet (incl. event-specific combo snippets)
7. **CTWA native:** auto-promotes `MESSAGING + only WhatsApp` to native CTWA, with try-native-then-rollback
8. **CTWA detection helper** `_detect_page_whatsapp` with per-field probing (Page-token, multiple fields)
9. **Hiring/SAC enum API client + auto-strip retry** for invalid interest IDs (max 5 retries)

---

## ⏳ What's pending

### 🔴 PRIORITY 1 — Verify draft-gen retry actually fires

**The bug:** User reports "draft generation took time but no drafts created." Backend returned `200 OK` with empty list.

**The fix (coded but unverified):** `backend/app/services/content_generator.py` around line 1330. Replaced the single LLM call with 3-attempt logic:
1. Primary model + json_object response_format
2. Retry with forceful instruction: "Empty arrays are not acceptable"
3. Fallback to `gpt-4o-mini` if primary keeps returning empty
4. If all fail → raise `ValueError` with diagnostic (HTTP 400)

**Logs to check next session:**
```bash
docker compose logs backend --since 10m | grep -E "DRAFT-GEN|generate_drafts|HTTP/1.1\" (200|400)"
```

Expected outputs:
- ✓ `[DRAFT-GEN] primary: gpt-X returned N drafts` — fix worked
- ⚠ `[DRAFT-GEN] primary: empty content from gpt-X` followed by `retry-forceful` and/or `fallback-gpt-4o-mini`
- ❌ NO `[DRAFT-GEN]` logs at all → my code didn't reach that block. Check earlier in the function for an exception.

**If still 0 drafts after all retries:**
- Check that `settings.CREATIVE_WRITING_MODEL` is correct
- Run direct test:
  ```bash
  docker compose exec backend python -c "
  import asyncio, sys
  sys.path.insert(0, '/app')
  from openai import AsyncOpenAI
  from app.core.config import get_settings
  s = get_settings()
  c = AsyncOpenAI(api_key=s.OPENAI_API_KEY)
  async def go():
      r = await c.chat.completions.create(
          model=s.CREATIVE_WRITING_MODEL,
          messages=[{'role':'user','content':'Return JSON: {\"drafts\":[{\"headline\":\"hi\"}]}'}],
          response_format={'type':'json_object'},
          max_completion_tokens=200,
      )
      print('content:', repr(r.choices[0].message.content))
      print('reasoning:', getattr(r.choices[0].message, 'reasoning_content', None))
  asyncio.run(go())
  "
  ```

### 🟡 PRIORITY 2 — Score-0 fuzzy match bug

**The bug:** `mcp-server/server.py` `search_meta_interests` returns garbage when LLM keyword has no Meta match. E.g., `"market news"` → `"Restaurants (dining)"` (score=0, audience=859M).

**The fix:** In `_match_score`, **reject score-0 candidates entirely**. Only return score ≥1 matches. Cleaner to return fewer interests than to pollute targeting.

**Where:** `mcp-server/server.py` around line 2200, the candidates ranking logic.

### 🟡 PRIORITY 3 — Phase 3: MCP-side strict targeting strip

**The work:** Strip stripped-by-Meta fields from `targeting` BEFORE the POST in `stage_advanced_campaign`, when `special_ad_categories` is set:

- For HEC (`HOUSING/EMPLOYMENT/CREDIT`):
  - Always strip `age_min`, `age_max`, `genders`
  - Force `geo_locations.cities[*].radius >= 25` (km) — Meta enforces 15-mile/25-km min
  - Strip `geo_locations.zips`
- For `FINANCIAL_PRODUCTS_SERVICES`:
  - Clamp age to `>= 18`
  - Strip income/wealth demographics
- For all SAC categories:
  - Force `targeting_automation.advantage_audience = 1`
  - Reject Lookalike Audience IDs in `flexible_spec.custom_audiences`

**Where:** `mcp-server/server.py` `stage_advanced_campaign`, just before the `=== ADSET PAYLOAD (final) ===` log line.

### 🟢 PRIORITY 4 — Phase 4: Custom Audience → Special Ad Audience pipeline

UI flow on `/dashboard/audiences` to:
1. Upload CRM list (already exists — `mcp_client.create_custom_audience_from_data`)
2. Auto-build a Special Ad Audience from it when workspace has SAC drafts
3. New MCP tool: `create_special_ad_audience(seed_audience_id, ratio)` → Meta `subtype: LOOKALIKE` with the SAA flag

### 🟢 PRIORITY 5 — Phase 5: Creative compliance gate

LLM scan of body/headline at approve time:
- Block: specific return % ("earn 12%"), guaranteed profits, urgency phrases, prohibited products (binary options, ICOs, payday loans)
- Auto-prepend disclaimers per region (FCA UK, SEC US…)

---

## 🗂️ Key files modified this session

```
backend/app/services/special_ad_category_detector.py    [NEW]
backend/app/services/content_generator.py                [SAC bias + draft-gen retry]
backend/app/services/ad_executor.py                      [cached SAC, multi-country, workspace isolation]
backend/app/api/routes/drafts.py                         [target_country/destination_url whitelist]
backend/app/api/routes/pixels.py                         [GET /whatsapp-status]
backend/app/services/mcp_client.py                       [check_page_whatsapp wrapper]

frontend/src/app/dashboard/drafts/page.tsx               [SAC badge, multi-country chip UI, Convert-to-Draft]
frontend/src/app/dashboard/pixels/page.tsx               [NEW page]
frontend/src/app/dashboard/settings/page.tsx             [WhatsApp connection badge + raw debug]
frontend/src/components/layout/Sidebar.tsx               [Pixels nav entry]
frontend/src/lib/api.ts                                  [checkWhatsAppStatus, updateDraft typings]

mcp-server/server.py                                     [_detect_page_whatsapp, native CTWA promotion,
                                                          auto-strip retry, MESSAGING→native promotion]
```

---

## 🔑 SAC Catalog (canonical)

API enum codes Meta accepts:

```python
HOUSING                          # HEC strict
EMPLOYMENT                       # HEC strict
CREDIT                           # HEC strict — covers BNPL + crypto lending (2026)
FINANCIAL_PRODUCTS_SERVICES      # Soft tier (no AND in API!)
ISSUES_ELECTIONS_POLITICS        # Auth required
ONLINE_GAMBLING_AND_GAMING       # Region-licensed
NONE                             # No SAC
```

The detector already maps these correctly. Don't re-introduce `FINANCIAL_PRODUCTS_AND_SERVICES` — Meta will reject it.

---

## 🧪 Quick verification commands

```bash
# Detector smoke test
docker compose exec backend python -c "
import asyncio, sys; sys.path.insert(0, '/app')
from app.services.special_ad_category_detector import detect_special_ad_category, DraftContext
async def go():
    d = await detect_special_ad_category(DraftContext(
        business_name='Quantivahq',
        business_description='Unlock your trading potential',
        industry_niche='Financial consultant',
        target_country='US,GB',
    ))
    print(d.category, d.confidence, d.should_auto_apply)
asyncio.run(go())
"
# Expected: FINANCIAL_PRODUCTS_SERVICES 0.81 True (auto_apply now True with 0.70 threshold)

# Verify backend has latest code
docker compose exec backend grep -n "FINANCIAL_PRODUCTS_SERVICES" /app/app/services/special_ad_category_detector.py
docker compose exec backend grep -n "DRAFT-GEN" /app/app/services/content_generator.py

# DB inspection
docker compose exec supabase-db psql -U postgres -d postgres -c "
  SELECT id, status, special_ad_category, special_ad_category_confidence
  FROM content_drafts WHERE workspace_id='3bb519d2-a095-42e8-becb-2a1bc1635a20'
  ORDER BY created_at DESC LIMIT 3;"
```

---

## 📋 Resume checklist for next session

1. [ ] Read this file
2. [ ] Read `SPECIAL_AD_CATEGORIES.md` (the master plan)
3. [ ] Verify backend container has latest code: `docker compose exec backend grep DRAFT-GEN /app/app/services/content_generator.py`
4. [ ] Trigger a fresh draft generation in the UI for Quantiva workspace
5. [ ] Tail backend logs: `docker compose logs backend -f | grep -E "DRAFT-GEN|SAC|TARGETING"`
6. [ ] Confirm drafts hit DB: query `content_drafts` for the workspace
7. [ ] If gen still failing: dive into the smoke-test command above to isolate model issue
8. [ ] Once gen works → move to Phase 3 (MCP-side strict targeting strip)

---

## 💡 Context for next session

- **Workspace under test:** Quantiva (`3bb519d2-a095-42e8-becb-2a1bc1635a20`), user `bytes2@gmail.com`
- **Pixel:** Quantiva Pixel `2043942056468227` (active, on quantivahq.com signup page)
- **The user's working draft:** `596cd01d-6ae4-44da-88aa-be73a37fe645` ("Stop Guessing Your Trades") — SAC backfilled to `FINANCIAL_PRODUCTS_SERVICES` confidence 0.95
- **The user wants drafts to be generated FOR Quantiva** — not the random `Alex Clothing` PK fashion drafts that showed up in the DB (those are a different user)
- **Phase 2 SAC bias is CONFIRMED working** in user's last log: search terms came back as `investing, day trading, personal finance, stock market, fintech` — no Robinhood/Bloomberg garbage anymore
