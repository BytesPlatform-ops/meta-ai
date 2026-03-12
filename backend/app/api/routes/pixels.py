"""
Meta Pixel management routes.

GET   /api/v1/meta/pixels             → list available Pixels via MCP
POST  /api/v1/meta/save-pixel         → save selected pixel_id to ad_accounts
POST  /api/v1/meta/email-developer    → email pixel install instructions to developer
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from ...api.deps import get_current_user_id
from ...core.config import get_settings
from ...db.supabase_client import get_supabase
from ...services.mcp_client import mcp_client, MCPError
from ...services.targeting_engine import _parse_mcp_json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/meta", tags=["Meta Pixel"])


@router.get("/pixels")
async def list_pixels(user_id: str = Depends(get_current_user_id)):
    """
    List all Meta Pixels available across all of the user's active ad accounts.
    Calls the MCP server's fetch_ad_account_pixels tool for each account.
    """
    supabase = get_supabase()
    account_result = (
        supabase.table("ad_accounts")
        .select("meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .neq("access_token", "")
        .execute()
    )
    if not account_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ad account found. Connect a Meta account first.",
        )

    all_pixels: list[dict] = []
    seen_ids: set[str] = set()

    for account in account_result.data:
        token = account.get("access_token")
        if not token:
            continue
        meta_id = account["meta_account_id"].replace("act_", "")
        try:
            result = await mcp_client.call_tool(
                "fetch_ad_account_pixels",
                {"ad_account_id": meta_id},
                token,
            )
            parsed = _parse_mcp_json(result)
            if isinstance(parsed, dict) and "error" in parsed:
                continue
            pixels = parsed
            if isinstance(parsed, dict) and "pixels" in parsed:
                pixels = parsed["pixels"]
            if isinstance(pixels, list):
                for px in pixels:
                    pid = px.get("id", "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        all_pixels.append(px)
        except MCPError:
            continue

    return {"pixels": all_pixels}


@router.get("/pixels/{pixel_id}/events")
async def get_pixel_events(pixel_id: str, user_id: str = Depends(get_current_user_id)):
    """
    Fetch active conversion events recorded by a specific Meta Pixel.
    Returns events with recent activity (last 7 days).
    """
    supabase = get_supabase()
    account_result = (
        supabase.table("ad_accounts")
        .select("access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .neq("access_token", "")
        .limit(5)
        .execute()
    )
    if not account_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ad account found.",
        )

    # Try each account's token until one works (pixel may belong to any account)
    for account in account_result.data:
        token = account.get("access_token")
        if not token:
            continue
        try:
            result = await mcp_client.call_tool(
                "get_pixel_events",
                {"pixel_id": pixel_id},
                token,
            )
            parsed = _parse_mcp_json(result)
            if isinstance(parsed, dict) and "error" in parsed:
                continue
            events = parsed.get("events", []) if isinstance(parsed, dict) else []
            return {"pixel_id": pixel_id, "events": events}
        except MCPError:
            continue

    return {"pixel_id": pixel_id, "events": []}


@router.get("/identities")
async def fetch_social_identities(user_id: str = Depends(get_current_user_id)):
    """
    Fetch Facebook Pages + linked Instagram Business Accounts via MCP.
    Saves facebook_page_id and instagram_actor_id to the ad_accounts row.
    """
    supabase = get_supabase()
    account_result = (
        supabase.table("ad_accounts")
        .select("id, meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not account_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ad account found. Connect a Meta account first.",
        )

    account = account_result.data[0]
    meta_id = account["meta_account_id"].replace("act_", "")

    try:
        result = await mcp_client.fetch_social_identities(
            meta_id, account["access_token"]
        )
        parsed = _parse_mcp_json(result)
        if isinstance(parsed, dict) and "error" in parsed:
            raise HTTPException(status_code=502, detail=parsed["error"])

        pages = parsed.get("pages", []) if isinstance(parsed, dict) else []

        # Auto-save the first page's IDs to ad_accounts
        if pages:
            first = pages[0]
            update_data = {}
            if first.get("page_id"):
                update_data["facebook_page_id"] = first["page_id"]
            if first.get("instagram_actor_id"):
                update_data["instagram_actor_id"] = first["instagram_actor_id"]
            if update_data:
                try:
                    supabase.table("ad_accounts").update(update_data).eq(
                        "id", account["id"]
                    ).execute()
                except Exception as e:
                    logger.warning("Failed to save social identities: %s", e)

        return {"pages": pages}
    except MCPError as e:
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")
    except Exception as e:
        logger.error("Social identities fetch failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to fetch social profiles: {e}")


class CreatePixelRequest(BaseModel):
    pixel_name: str = "AI Pixel"


@router.post("/pixels/create")
async def create_pixel(
    body: CreatePixelRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Create a new Meta Pixel and auto-save it to the ad account."""
    supabase = get_supabase()
    account_result = (
        supabase.table("ad_accounts")
        .select("id, meta_account_id, access_token")
        .eq("user_id", user_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not account_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active ad account found. Connect a Meta account first.",
        )

    account = account_result.data[0]
    meta_id = account["meta_account_id"].replace("act_", "")

    try:
        result = await mcp_client.call_tool(
            "create_pixel",
            {"ad_account_id": meta_id, "pixel_name": body.pixel_name},
            account["access_token"],
        )
        parsed = _parse_mcp_json(result)
        if isinstance(parsed, dict) and "error" in parsed:
            raise HTTPException(status_code=502, detail=parsed["error"])

        pixel_id = parsed.get("pixel_id") or parsed.get("id")
        if not pixel_id:
            raise HTTPException(status_code=502, detail="Pixel creation failed — no ID returned")

        # Auto-save to ad_accounts
        try:
            supabase.table("ad_accounts").update({"pixel_id": pixel_id}).eq("id", account["id"]).execute()
        except Exception as e:
            logger.warning("Auto-save pixel_id failed: %s", e)

        # Update tracking mode
        try:
            prefs_result = supabase.table("user_preferences").select("id").eq("user_id", user_id).limit(1).execute()
            if prefs_result.data:
                supabase.table("user_preferences").update({"tracking_mode": "website_pixel"}).eq("user_id", user_id).execute()
            else:
                supabase.table("user_preferences").insert({"user_id": user_id, "tracking_mode": "website_pixel"}).execute()
        except Exception as e:
            logger.warning("tracking_mode update skipped: %s", e)

        return parsed
    except MCPError as e:
        raise HTTPException(status_code=502, detail=f"MCP error: {e}")


class SavePixelRequest(BaseModel):
    pixel_id: str | None = None  # None to clear/unset the pixel


@router.post("/save-pixel")
async def save_pixel(
    body: SavePixelRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Save (or clear) the selected Meta Pixel ID.
    Updates ad_accounts if one exists, and always saves tracking_mode to user_preferences.
    When pixel_id is None, the system uses WhatsApp/COD fallback strategy.
    """
    supabase = get_supabase()
    strategy = "website_pixel" if body.pixel_id else "whatsapp_cod"
    ad_account_updated = False

    # Try to update ad_accounts.pixel_id if column exists and account is connected
    try:
        account_result = (
            supabase.table("ad_accounts")
            .update({"pixel_id": body.pixel_id})
            .eq("user_id", user_id)
            .eq("is_active", True)
            .execute()
        )
        ad_account_updated = bool(account_result.data)
    except Exception as e:
        logger.warning("ad_accounts pixel_id update skipped: %s", e)

    # Save tracking preference to user_preferences
    try:
        prefs_result = (
            supabase.table("user_preferences")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if prefs_result.data:
            supabase.table("user_preferences").update(
                {"tracking_mode": strategy}
            ).eq("user_id", user_id).execute()
        else:
            supabase.table("user_preferences").insert(
                {"user_id": user_id, "tracking_mode": strategy}
            ).execute()
    except Exception as e:
        # tracking_mode column may not exist yet — that's OK
        logger.warning("user_preferences tracking_mode update skipped: %s", e)

    return {
        "success": True,
        "pixel_id": body.pixel_id,
        "strategy": strategy,
        "ad_account_updated": ad_account_updated,
        "message": (
            f"Pixel {body.pixel_id} saved. Campaigns will optimize for website conversions."
            if body.pixel_id
            else "Saved! Campaigns will use WhatsApp/COD strategy."
        ),
    }


# ── Email developer instructions ─────────────────────────────────────────────

class EmailDeveloperRequest(BaseModel):
    developer_email: EmailStr
    pixel_id: str
    platform: str = "custom"  # shopify | woocommerce | custom


def _build_pixel_email_html(pixel_id: str, platform: str, business_name: str) -> str:
    """Build the HTML email body with pixel installation instructions."""

    shopify_instructions = """
        <h3>Shopify Installation</h3>
        <ol>
            <li>Go to your Shopify Admin → <strong>Online Store → Preferences</strong></li>
            <li>Scroll to the <strong>Facebook Pixel</strong> section</li>
            <li>Paste this Pixel ID: <code style="background:#f4f4f4;padding:2px 8px;border-radius:4px;font-size:16px;color:#e74c3c;">{pixel_id}</code></li>
            <li>Click <strong>Save</strong></li>
        </ol>"""

    woocommerce_instructions = """
        <h3>WooCommerce Installation</h3>
        <ol>
            <li>Install the <strong>Facebook for WooCommerce</strong> plugin</li>
            <li>Go to <strong>WooCommerce → Settings → Integration → Facebook</strong></li>
            <li>Enter this Pixel ID: <code style="background:#f4f4f4;padding:2px 8px;border-radius:4px;font-size:16px;color:#e74c3c;">{pixel_id}</code></li>
            <li>Click <strong>Save Changes</strong></li>
        </ol>"""

    custom_instructions = f"""
        <h3>Manual Installation</h3>
        <p>Add this code to the <code>&lt;head&gt;</code> section of <strong>every page</strong> on your website:</p>
        <pre style="background:#1a1a2e;color:#e0e0e0;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.5;">
&lt;!-- Meta Pixel Code --&gt;
&lt;script&gt;
!function(f,b,e,v,n,t,s)
{{f.fbq||(n=f.fbq=function(){{n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)}},
f._fbq||(f._fbq=n),n.push=n,n.loaded=!0,n.version='2.0',
n.queue=[],t=b.createElement(e),t.async=!0,
t.src=v,s=b.getElementsByTagName(e)[0],
s.parentNode.insertBefore(t,s)}}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '{pixel_id}');
fbq('track', 'PageView');
&lt;/script&gt;
&lt;noscript&gt;&lt;img height="1" width="1" style="display:none"
src="https://www.facebook.com/tr?id={pixel_id}&amp;ev=PageView&amp;noscript=1"
/&gt;&lt;/noscript&gt;
&lt;!-- End Meta Pixel Code --&gt;</pre>

        <h3>Purchase Event Tracking</h3>
        <p>Add this on your <strong>order confirmation / thank-you page</strong>:</p>
        <pre style="background:#1a1a2e;color:#e0e0e0;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.5;">
&lt;script&gt;
fbq('track', 'Purchase', {{
  value: ORDER_TOTAL,
  currency: 'PKR'
}});
&lt;/script&gt;</pre>"""

    platform_sections = {
        "shopify": shopify_instructions.format(pixel_id=pixel_id),
        "woocommerce": woocommerce_instructions.format(pixel_id=pixel_id),
        "custom": custom_instructions,
    }
    instructions = platform_sections.get(platform, custom_instructions)

    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:640px;margin:0 auto;color:#333;">
        <div style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:32px;border-radius:12px 12px 0 0;">
            <h1 style="color:white;margin:0;font-size:22px;">Meta Pixel Installation Guide</h1>
            <p style="color:rgba(255,255,255,0.85);margin:8px 0 0;font-size:14px;">
                From {business_name} — via Meta Ads AI
            </p>
        </div>
        <div style="background:white;padding:32px;border:1px solid #e0e0e0;border-top:none;border-radius:0 0 12px 12px;">
            <p>Hi! You've been sent the Meta Pixel installation instructions for <strong>{business_name}</strong>.</p>

            <div style="background:#f8f9fa;border:1px solid #e9ecef;border-radius:8px;padding:16px;margin:20px 0;">
                <p style="margin:0 0 4px;font-size:13px;color:#666;">Pixel ID</p>
                <p style="margin:0;font-size:20px;font-weight:700;color:#1877F2;font-family:monospace;">{pixel_id}</p>
            </div>

            {instructions}

            <hr style="border:none;border-top:1px solid #eee;margin:24px 0;" />
            <p style="font-size:12px;color:#999;">
                This email was sent by Meta Ads AI on behalf of {business_name}.
                If you didn't expect this, please ignore it.
            </p>
        </div>
    </div>"""


@router.post("/email-developer")
async def email_developer(
    body: EmailDeveloperRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Send pixel installation instructions to a developer via email.
    Includes the pixel script tag and platform-specific guidance.
    """
    settings = get_settings()
    supabase = get_supabase()

    # Get business name from preferences
    prefs_result = (
        supabase.table("user_preferences")
        .select("business_name")
        .eq("user_id", user_id)
        .execute()
    )
    business_name = "Your Business"
    if prefs_result.data and prefs_result.data[0].get("business_name"):
        business_name = prefs_result.data[0]["business_name"]

    html = _build_pixel_email_html(body.pixel_id, body.platform, business_name)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Meta Pixel Installation Instructions — {business_name}"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = body.developer_email
    msg.attach(MIMEText(html, "html"))

    # Send via SMTP (or log if not configured)
    if settings.SMTP_USER and settings.SMTP_PASSWORD:
        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        except Exception as e:
            logger.error("SMTP send failed: %s", e)
            raise HTTPException(status_code=502, detail=f"Failed to send email: {e}")
    else:
        # Mock mode — log the email instead of sending
        logger.info(
            "MOCK EMAIL → to=%s subject='%s' pixel_id=%s platform=%s",
            body.developer_email, msg["Subject"], body.pixel_id, body.platform,
        )

    return {
        "success": True,
        "message": f"Installation instructions sent to {body.developer_email}",
        "pixel_id": body.pixel_id,
        "platform": body.platform,
    }
