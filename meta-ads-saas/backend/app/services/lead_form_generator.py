"""
AI Lead Form Generator — Uses OpenAI to draft optimal Meta Instant Form fields
based on the ad's product context and copy.

The LLM analyzes the product/ad text and returns a structured JSON schema
that maps directly to Meta's leadgen_forms API question types.
"""
import json
import logging

from openai import AsyncOpenAI

from ..core.config import get_settings
from ..db.supabase_client import get_supabase

logger = logging.getLogger(__name__)
settings = get_settings()

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# Meta Graph API supported question types for Instant Forms
VALID_QUESTION_TYPES = {
    "FULL_NAME", "EMAIL", "PHONE_NUMBER", "CITY",
    "COMPANY_NAME", "JOB_TITLE", "STATE", "ZIP",
    "STREET_ADDRESS", "DATE_OF_BIRTH", "CUSTOM",
}

SYSTEM_PROMPT = """\
You are a lead form conversion expert for Meta Instant Forms (Facebook/Instagram lead ads).

Your job: given a product description and ad copy, design the PERFECT lead form that
maximises completion rate while capturing the data the advertiser needs.

Rules:
- Return 3-5 fields MAXIMUM. Every extra field drops conversion rate ~10%.
- ALWAYS include FULL_NAME as the first field (Meta pre-fills it → zero friction).
- Include PHONE_NUMBER or EMAIL (pick the one most relevant to the business model).
- Add 1-2 strategic CUSTOM questions that qualify leads WITHOUT creating friction.
  Good custom questions: single-select ("Which product interests you?"), short text ("When do you need this?").
  Bad custom questions: essay-type, sensitive financial data, anything requiring thought.
- For WhatsApp/COD businesses: prefer PHONE_NUMBER over EMAIL.
- For e-commerce/SaaS: prefer EMAIL over PHONE_NUMBER.
- Form name should be professional and include the product/brand name.

Valid question types: FULL_NAME, EMAIL, PHONE_NUMBER, CITY, COMPANY_NAME, JOB_TITLE, CUSTOM

Return ONLY valid JSON (no markdown, no code fences) in this exact format:
{
  "form_name": "Product Inquiry — Brand Name",
  "questions": [
    {"type": "FULL_NAME", "key": "full_name"},
    {"type": "PHONE_NUMBER", "key": "phone_number"},
    {"type": "CUSTOM", "key": "product_interest", "label": "Which flavor are you interested in?"}
  ],
  "reasoning": "Brief explanation of why these fields were chosen"
}"""


async def generate_lead_form_draft(
    product_name: str = "",
    product_description: str = "",
    ad_text: str = "",
    target_country: str = "",
    business_description: str = "",
) -> dict:
    """
    Use LLM to generate an optimal lead form schema for a Meta Instant Form.

    Returns:
        {
            "form_name": str,
            "questions": [{"type": str, "key": str, "label"?: str}, ...],
            "reasoning": str,
        }
    """
    # Build context for the LLM
    context_parts = []
    if product_name:
        context_parts.append(f"Product: {product_name}")
    if product_description:
        context_parts.append(f"Product Description: {product_description}")
    if ad_text:
        context_parts.append(f"Ad Copy: {ad_text}")
    if target_country:
        context_parts.append(f"Target Country: {target_country}")
    if business_description:
        context_parts.append(f"Business: {business_description}")

    if not context_parts:
        # Fallback: return a sensible default form
        return _default_form()

    user_prompt = (
        "Design an optimised lead form for this ad:\n\n"
        + "\n".join(context_parts)
    )

    try:
        response = await client.chat.completions.create(
            model=settings.ELITE_REASONING_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=1000,
            response_format={"type": "json_object"},
        )

        content = (response.choices[0].message.content or "").strip()
        # Strip markdown fences if model adds them despite json_object mode
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            content = content.rsplit("```", 1)[0]

        data = json.loads(content)

        # Validate & normalise
        questions = data.get("questions", [])
        validated = []
        for q in questions:
            qtype = (q.get("type") or "").upper()
            if qtype not in VALID_QUESTION_TYPES:
                continue
            entry = {"type": qtype, "key": q.get("key", qtype.lower())}
            if qtype == "CUSTOM" and q.get("label"):
                entry["label"] = q["label"]
            validated.append(entry)

        if not validated:
            return _default_form()

        return {
            "form_name": data.get("form_name", "Lead Form"),
            "questions": validated,
            "reasoning": data.get("reasoning", ""),
        }

    except json.JSONDecodeError as e:
        logger.error("AI lead form returned invalid JSON: %s", e)
        return _default_form()
    except Exception as e:
        logger.error("AI lead form generation failed: %s", e)
        return _default_form()


async def generate_lead_form_from_draft(draft_id: str, user_id: str) -> dict:
    """
    Generate a lead form schema using context from an existing content_draft.
    Pulls product info + ad copy from the draft and its linked product.
    """
    supabase = get_supabase()

    # Fetch draft
    draft_res = (
        supabase.table("content_drafts")
        .select("body_text, headline, product_id, target_country")
        .eq("id", draft_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    draft = draft_res.data
    if not draft:
        return _default_form()

    ad_text = f"{draft.get('headline') or ''}\n{draft.get('body_text') or ''}".strip()
    target_country = draft.get("target_country") or ""

    # Fetch linked product if available
    product_name = ""
    product_desc = ""
    if draft.get("product_id"):
        prod_res = (
            supabase.table("products")
            .select("name, description")
            .eq("id", draft["product_id"])
            .single()
            .execute()
        )
        if prod_res.data:
            product_name = prod_res.data.get("name", "")
            product_desc = prod_res.data.get("description", "")

    # Fetch business description from preferences
    biz_desc = ""
    pref_res = (
        supabase.table("user_preferences")
        .select("business_description")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if pref_res.data:
        biz_desc = pref_res.data[0].get("business_description", "")

    return await generate_lead_form_draft(
        product_name=product_name,
        product_description=product_desc,
        ad_text=ad_text,
        target_country=target_country,
        business_description=biz_desc,
    )


def _default_form() -> dict:
    """Sensible fallback when AI generation fails."""
    return {
        "form_name": "Lead Form",
        "questions": [
            {"type": "FULL_NAME", "key": "full_name"},
            {"type": "PHONE_NUMBER", "key": "phone_number"},
            {"type": "EMAIL", "key": "email"},
        ],
        "reasoning": "Default form — AI generation was not available.",
    }
