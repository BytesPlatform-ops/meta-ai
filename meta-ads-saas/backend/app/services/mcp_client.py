"""
MCP Client — communicates with the Meta Marketing API MCP server.

The MCP server exposes tools (functions) that the SaaS platform calls to:
  - list / pause / update campaigns, ad sets, ads
  - read performance metrics (ROAS, spend, impressions, etc.)
  - get account-level overviews
  - fetch page posts and engagement data

Each user's requests are scoped using their ad account's access token,
which is injected as a tool argument per-request.

Protocol: JSON-RPC 2.0 over HTTP.
"""
import json
import hashlib
import httpx
import time
import uuid
from typing import Any
from ..core.config import get_settings

settings = get_settings()


# ── In-memory TTL cache for read-only MCP tool responses ──────────────────────
# Prevents hammering Meta's API on every page navigation.
# Write operations bypass the cache entirely.

_cache: dict[str, tuple[float, dict]] = {}  # key → (expires_at, result)
_CACHE_MAX = 200  # evict oldest when exceeded

# Read-only tools that are safe to cache (no side effects)
_CACHEABLE_TOOLS = {
    "saas_account_overview",
    "saas_list_campaigns",
    "saas_campaign_insights",
    "saas_campaign_detail",
    "saas_list_ads",
    "saas_page_posts",
    "saas_time_series_insights",
    "get_deep_ad_insights",
    "get_ad_creatives_with_performance",
    "fetch_ad_account_pixels",
    "fetch_pixel_performance",
    "fetch_social_identities",
}

# TTL per tool (seconds) — heavier/slower tools get longer cache
_TOOL_TTL = {
    "saas_account_overview": 30,
    "saas_list_campaigns": 30,
    "saas_campaign_detail": 30,
    "saas_time_series_insights": 30,
    "saas_page_posts": 60,
    "get_deep_ad_insights": 30,
    "fetch_social_identities": 300,
}
_DEFAULT_TTL = 30


def _cache_key(tool_name: str, arguments: dict) -> str:
    """Stable cache key: tool_name + sorted arguments (excludes access_token)."""
    args_for_key = {k: v for k, v in sorted(arguments.items()) if k != "access_token"}
    raw = f"{tool_name}:{json.dumps(args_for_key, sort_keys=True)}"
    # Prefix with tool name so we can invalidate by tool
    return f"{tool_name}::{hashlib.md5(raw.encode()).hexdigest()}"


def _evict_expired():
    """Remove expired entries and trim to max size."""
    now = time.monotonic()
    expired = [k for k, (exp, _) in _cache.items() if exp <= now]
    for k in expired:
        del _cache[k]
    if len(_cache) > _CACHE_MAX:
        oldest = sorted(_cache.items(), key=lambda x: x[1][0])
        for k, _ in oldest[: len(_cache) - _CACHE_MAX]:
            del _cache[k]


def invalidate_cache(tool_names: list[str] | None = None):
    """
    Clear cache entries. If tool_names is None, clear everything.
    Otherwise clear only entries whose key starts with any of the given tool names.
    """
    if tool_names is None:
        _cache.clear()
        return
    to_del = [k for k in _cache if any(k.startswith(f"{t}::") for t in tool_names)]
    for k in to_del:
        del _cache[k]


# Write tools that should trigger cache invalidation when they succeed.
# Maps write tool → list of cacheable tools to invalidate.
_WRITE_INVALIDATES: dict[str, list[str]] = {
    "pause_entity": [
        "saas_account_overview", "saas_list_campaigns", "saas_campaign_insights",
        "saas_campaign_detail", "saas_list_ads", "saas_time_series_insights",
        "get_deep_ad_insights",
    ],
    "update_entity_status": [
        "saas_account_overview", "saas_list_campaigns", "saas_campaign_insights",
        "saas_campaign_detail", "saas_list_ads", "saas_time_series_insights",
    ],
    "update_daily_budget": [
        "saas_account_overview", "saas_list_campaigns", "saas_campaign_detail",
    ],
    "update_adset_budget": [
        "saas_account_overview", "saas_list_campaigns", "saas_campaign_detail",
    ],
    "update_adset_targeting": [
        "saas_campaign_detail", "saas_list_ads",
    ],
    "stage_advanced_campaign": [
        "saas_account_overview", "saas_list_campaigns", "saas_time_series_insights",
    ],
    "duplicate_ad_with_mutations": [
        "saas_list_ads", "saas_campaign_detail",
    ],
    "shift_budget_between_entities": [
        "saas_account_overview", "saas_list_campaigns", "saas_campaign_detail",
    ],
    "create_meta_ad_campaign": [
        "saas_account_overview", "saas_list_campaigns",
    ],
}


class MCPClient:
    """Thin async wrapper around the Meta Marketing MCP JSON-RPC endpoint."""

    def __init__(self, server_url: str | None = None, api_key: str | None = None):
        self.server_url = (server_url or settings.MCP_SERVER_URL).rstrip("/")
        self.api_key = api_key or settings.MCP_SERVER_API_KEY

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        user_access_token: str,
    ) -> dict:
        """
        Call an MCP tool by name with the given arguments.
        The user's access token is automatically injected into arguments.
        Read-only tools are cached with a short TTL.
        Returns the tool's result payload.
        """
        # Check cache for read-only tools
        is_cacheable = tool_name in _CACHEABLE_TOOLS
        if is_cacheable:
            key = _cache_key(tool_name, arguments)
            cached = _cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]

        # Inject the access_token into arguments so the MCP tool can
        # authenticate against the Meta Graph API.
        arguments_with_token = {"access_token": user_access_token, **arguments}

        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments_with_token,
            },
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.server_url}/mcp",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        if "error" in data:
            raise MCPError(data["error"].get("message", "MCP error"), data["error"])

        result = data.get("result", {})

        # Store in cache for read-only tools
        if is_cacheable:
            ttl = _TOOL_TTL.get(tool_name, _DEFAULT_TTL)
            _cache[key] = (time.monotonic() + ttl, result)
            _evict_expired()

        # Invalidate stale cache entries after successful write operations
        if tool_name in _WRITE_INVALIDATES:
            invalidate_cache(_WRITE_INVALIDATES[tool_name])

        return result

    async def list_tools(self) -> list[dict]:
        """Returns the list of tools available on the MCP server."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/list",
            "params": {},
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.server_url}/mcp",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
        return resp.json().get("result", {}).get("tools", [])

    # ------------------------------------------------------------------
    # Convenience wrappers for read operations
    # ------------------------------------------------------------------

    async def get_account_overview(
        self, ad_account_id: str, user_access_token: str,
        since: str | None = None, until: str | None = None,
    ) -> dict:
        """High-level health snapshot: name, status, active campaigns, 30d spend/ROAS."""
        args: dict = {"ad_account_id": ad_account_id}
        if since and until:
            args["since"] = since
            args["until"] = until
        return await self.call_tool("saas_account_overview", args, user_access_token)

    async def list_campaigns(
        self,
        ad_account_id: str,
        user_access_token: str,
        status_filter: str = "all",
        limit: int = 25,
        since: str | None = None, until: str | None = None,
    ) -> dict:
        """List campaigns with status, budget, and 7d performance metrics."""
        args: dict = {"ad_account_id": ad_account_id, "status_filter": status_filter, "limit": limit}
        if since and until:
            args["since"] = since
            args["until"] = until
        return await self.call_tool("saas_list_campaigns", args, user_access_token)

    async def get_campaign_insights(
        self,
        campaign_id: str,
        user_access_token: str,
        date_preset: str = "last_7d",
        since: str | None = None, until: str | None = None,
    ) -> dict:
        """Detailed performance insights for a specific campaign."""
        args: dict = {"campaign_id": campaign_id, "date_preset": date_preset}
        if since and until:
            args["since"] = since
            args["until"] = until
        return await self.call_tool("saas_campaign_insights", args, user_access_token)

    async def list_ads(
        self,
        campaign_id: str,
        user_access_token: str,
        date_preset: str = "last_7d",
        status_filter: str = "all",
        since: str | None = None, until: str | None = None,
    ) -> dict:
        """List all ads in a campaign with individual performance and verdicts."""
        args: dict = {"campaign_id": campaign_id, "date_preset": date_preset, "status_filter": status_filter}
        if since and until:
            args["since"] = since
            args["until"] = until
        return await self.call_tool("saas_list_ads", args, user_access_token)

    # ------------------------------------------------------------------
    # Convenience wrappers for write operations
    # ------------------------------------------------------------------

    async def create_campaign(
        self, ad_account_id: str, params: dict, user_access_token: str
    ) -> dict:
        return await self.call_tool(
            "create_meta_ad_campaign",
            {"ad_account_id": ad_account_id, **params},
            user_access_token,
        )

    async def pause_campaign(
        self, campaign_id: str, user_access_token: str
    ) -> dict:
        return await self.call_tool(
            "pause_entity",
            {"entity_id": campaign_id, "entity_type": "campaign"},
            user_access_token,
        )

    async def get_page_posts(
        self, page_id: str, page_access_token: str,
    ) -> dict:
        """Fetch recent page posts with reach & engagement."""
        # saas_page_posts uses page_access_token as the key (not access_token)
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": "saas_page_posts",
                "arguments": {
                    "page_access_token": page_access_token,
                    "page_id": page_id,
                },
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.server_url}/mcp",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise MCPError(data["error"].get("message", "MCP error"), data["error"])
        return data.get("result", {})

    async def update_ad_budget(
        self, ad_account_id: str, adset_id: str, daily_budget_cents: int, user_access_token: str
    ) -> dict:
        return await self.call_tool(
            "update_daily_budget",
            {
                "entity_id": adset_id,
                "entity_type": "adset",
                "new_budget_dollars": daily_budget_cents / 100,
            },
            user_access_token,
        )


    # ------------------------------------------------------------------
    # Pixel wrappers
    # ------------------------------------------------------------------

    async def fetch_pixels(
        self, ad_account_id: str, user_access_token: str
    ) -> dict:
        """List Meta Pixels available on an ad account via MCP."""
        return await self.call_tool(
            "fetch_ad_account_pixels",
            {"ad_account_id": ad_account_id},
            user_access_token,
        )

    async def fetch_pixel_performance(
        self, pixel_id: str, ad_account_id: str, user_access_token: str
    ) -> dict:
        """Get Pixel conversion performance data via MCP."""
        return await self.call_tool(
            "fetch_pixel_performance",
            {"pixel_id": pixel_id, "ad_account_id": ad_account_id},
            user_access_token,
        )

    # ------------------------------------------------------------------
    # Analytics wrappers
    # ------------------------------------------------------------------

    async def get_time_series_insights(
        self, ad_account_id: str, user_access_token: str, date_preset: str = "last_30d",
        since: str | None = None, until: str | None = None,
    ) -> dict:
        """Get daily time-series data and campaign breakdown for charts."""
        args: dict = {"ad_account_id": ad_account_id, "date_preset": date_preset}
        if since and until:
            args["since"] = since
            args["until"] = until
        return await self.call_tool("saas_time_series_insights", args, user_access_token)

    # ------------------------------------------------------------------
    # Targeting & research wrappers
    # ------------------------------------------------------------------

    async def validate_interests(
        self, keywords: list[str], user_access_token: str
    ) -> dict:
        """Validate keywords against Meta's ad interest taxonomy via MCP."""
        return await self.call_tool(
            "validate_meta_interests",
            {"keywords_json": json.dumps(keywords)},
            user_access_token,
        )

    async def search_interests(
        self, keywords: list[str], target_country: str, user_access_token: str
    ) -> list[dict]:
        """Search culturally relevant Meta interests for a target country via MCP."""
        result = await self.call_tool(
            "search_meta_interests",
            {"keywords_json": json.dumps(keywords), "target_country": target_country},
            user_access_token,
        )
        # search_meta_interests returns a plain list (JSON tool), not wrapped in content
        if isinstance(result, list):
            return result
        # Handle content-wrapped response
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "[]")
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    async def resolve_geo(
        self, cities: list[str], country_code: str, user_access_token: str
    ) -> dict:
        """Resolve city names to Meta geo-location keys via MCP."""
        return await self.call_tool(
            "resolve_geo_locations",
            {"cities_json": json.dumps(cities), "country_code": country_code},
            user_access_token,
        )

    async def fetch_competitor_ads(
        self, keywords: list[str], country_code: str, user_access_token: str
    ) -> dict:
        """Fetch active competitor ads from Meta Ad Library via MCP."""
        return await self.call_tool(
            "fetch_competitor_ads",
            {"keywords_json": json.dumps(keywords), "country_code": country_code},
            user_access_token,
        )

    async def scrape_website(self, url: str) -> dict:
        """Scrape a website URL via MCP (Tavily Extract)."""
        return await self.call_tool(
            "scrape_website",
            {"url": url},
            user_access_token="",
        )

    async def fetch_social_identities(
        self, ad_account_id: str, user_access_token: str
    ) -> dict:
        """Fetch Facebook Pages + linked Instagram accounts via MCP."""
        return await self.call_tool(
            "fetch_social_identities",
            {"ad_account_id": ad_account_id},
            user_access_token,
        )

    async def get_campaign_detail(
        self, campaign_id: str, user_access_token: str, date_preset: str = "last_7d",
        since: str | None = None, until: str | None = None,
    ) -> dict:
        """Full campaign detail: summary, daily time-series, ads, breakdowns."""
        args: dict = {"campaign_id": campaign_id, "date_preset": date_preset}
        if since and until:
            args["since"] = since
            args["until"] = until
        return await self.call_tool("saas_campaign_detail", args, user_access_token)

    async def stage_campaign(
        self, ad_account_id: str, params: dict, user_access_token: str
    ) -> dict:
        """Create an Advantage+ OUTCOME_SALES campaign funnel via MCP."""
        return await self.call_tool(
            "stage_advanced_campaign",
            {"ad_account_id": ad_account_id, **params},
            user_access_token,
        )

    # ------------------------------------------------------------------
    # Audience wrappers
    # ------------------------------------------------------------------

    async def create_custom_audience(
        self, ad_account_id: str, audience_name: str, customer_data: list[dict], user_access_token: str
    ) -> dict:
        """Create a Custom Audience and upload hashed customer data via MCP."""
        import json
        return await self.call_tool(
            "create_custom_audience_from_data",
            {"ad_account_id": ad_account_id, "audience_name": audience_name, "customer_data_json": json.dumps(customer_data)},
            user_access_token,
        )

    async def create_lookalike_audience(
        self, ad_account_id: str, origin_audience_id: str, country_code: str, ratio: float, user_access_token: str
    ) -> dict:
        """Create a Lookalike Audience from a source Custom Audience via MCP."""
        return await self.call_tool(
            "create_lookalike_audience",
            {"ad_account_id": ad_account_id, "origin_audience_id": origin_audience_id, "country_code": country_code, "ratio": ratio},
            user_access_token,
        )


    # ------------------------------------------------------------------
    # Optimization Co-Pilot wrappers
    # ------------------------------------------------------------------

    async def get_deep_ad_insights(
        self, ad_account_id: str, user_access_token: str,
        date_preset: str = "last_7d", entity_level: str = "campaign"
    ) -> dict:
        """Get performance breakdowns by age, gender, and placement."""
        return await self.call_tool(
            "get_deep_ad_insights",
            {"ad_account_id": ad_account_id, "date_preset": date_preset, "entity_level": entity_level},
            user_access_token,
        )

    async def get_ad_creatives_with_performance(
        self, ad_account_id: str, user_access_token: str,
        date_preset: str = "last_7d",
    ) -> dict:
        """Fetch all ads with creative text + performance for research-backed copy."""
        return await self.call_tool(
            "get_ad_creatives_with_performance",
            {"ad_account_id": ad_account_id, "date_preset": date_preset},
            user_access_token,
        )

    async def update_adset_budget(
        self, adset_id: str, user_access_token: str,
        daily_budget: int | None = None, lifetime_budget: int | None = None
    ) -> dict:
        """Update an adset's daily or lifetime budget (amounts in cents)."""
        args: dict[str, Any] = {"adset_id": adset_id}
        if daily_budget is not None:
            args["daily_budget"] = daily_budget
        if lifetime_budget is not None:
            args["lifetime_budget"] = lifetime_budget
        return await self.call_tool("update_adset_budget", args, user_access_token)

    async def update_entity_status(
        self, entity_id: str, status: str, user_access_token: str
    ) -> dict:
        """Update status of a campaign/adset/ad to ACTIVE or PAUSED."""
        return await self.call_tool(
            "update_entity_status",
            {"entity_id": entity_id, "status": status},
            user_access_token,
        )

    async def update_adset_targeting(
        self, adset_id: str, user_access_token: str,
        exclude_publisher_platforms: list[str] | None = None,
        bid_strategy: str | None = None,
        bid_amount: int | None = None,
    ) -> dict:
        """Update adset targeting (exclude placements) or bid strategy."""
        args: dict[str, Any] = {"adset_id": adset_id}
        if exclude_publisher_platforms:
            args["exclude_publisher_platforms"] = exclude_publisher_platforms
        if bid_strategy:
            args["bid_strategy"] = bid_strategy
        if bid_amount is not None:
            args["bid_amount"] = bid_amount
        return await self.call_tool("update_adset_targeting", args, user_access_token)

    # ------------------------------------------------------------------
    # Agentic Co-Pilot V3 wrappers
    # ------------------------------------------------------------------

    async def duplicate_ad_with_mutations(
        self, ad_account_id: str, source_ad_id: str, user_access_token: str,
        new_body_text: str = "", new_cta: str = "", new_name_suffix: str = "B",
    ) -> dict:
        """Duplicate a winning ad with new copy/CTA for A/B testing."""
        args: dict[str, Any] = {"ad_account_id": ad_account_id, "source_ad_id": source_ad_id}
        if new_body_text:
            args["new_body_text"] = new_body_text
        if new_cta:
            args["new_cta"] = new_cta
        if new_name_suffix != "B":
            args["new_name_suffix"] = new_name_suffix
        return await self.call_tool("duplicate_ad_with_mutations", args, user_access_token)

    async def shift_budget_between_entities(
        self, source_entity_id: str, target_entity_id: str,
        amount_cents: int, user_access_token: str,
    ) -> dict:
        """Robin Hood: move budget from losing entity to winning entity."""
        return await self.call_tool("shift_budget_between_entities", {
            "source_entity_id": source_entity_id,
            "target_entity_id": target_entity_id,
            "amount_cents": amount_cents,
        }, user_access_token)

    async def create_lookalike_from_campaign(
        self, ad_account_id: str, campaign_id: str, user_access_token: str,
        country_code: str = "PK", ratio: float = 0.01,
    ) -> dict:
        """Auto-create a LAL from a campaign's engaged audience."""
        return await self.call_tool("create_lookalike_from_campaign", {
            "ad_account_id": ad_account_id,
            "campaign_id": campaign_id,
            "country_code": country_code,
            "ratio": ratio,
        }, user_access_token)


class MCPError(Exception):
    def __init__(self, message: str, raw: dict | None = None):
        super().__init__(message)
        self.raw = raw or {}


# Module-level default client instance
mcp_client = MCPClient()
