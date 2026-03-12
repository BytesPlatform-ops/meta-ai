"""
Content Scheduler — Auto-generates drafts based on each user's posting_frequency.

Runs every hour, checks which users are due for new content, and calls
the existing generate_drafts() pipeline. Drafts land as status="pending"
for user approval.
"""
import logging
from datetime import datetime, timezone

from ..db.supabase_client import get_supabase
from .content_generator import generate_drafts

logger = logging.getLogger(__name__)

# Frequency → minimum hours between generations
FREQUENCY_INTERVALS: dict[str, float] = {
    "daily": 24,
    "3x_weekly": 56,       # ~2.3 days → Mon/Wed/Fri cadence
    "weekends_only": 0,    # special: only Sat/Sun, checked separately
}

WEEKEND_DAYS = {5, 6}  # Saturday=5, Sunday=6


async def run_scheduled_generation() -> dict:
    """
    Check all users with a non-manual posting frequency and generate
    drafts for those who are due.

    Returns summary dict with counts.
    """
    supabase = get_supabase()

    # Fetch all users with automatic posting frequencies
    result = (
        supabase.table("user_preferences")
        .select("user_id, posting_frequency")
        .neq("posting_frequency", "manual_only")
        .execute()
    )
    users = result.data or []

    if not users:
        logger.debug("Content scheduler: no users with automatic frequency")
        return {"checked": 0, "generated": 0, "skipped": 0, "errors": 0}

    generated = 0
    skipped = 0
    errors = 0
    now = datetime.now(timezone.utc)

    for user in users:
        user_id = user["user_id"]
        freq = user["posting_frequency"]

        try:
            if not _is_due(supabase, user_id, freq, now):
                skipped += 1
                continue

            logger.info("Content scheduler: generating drafts for user %s (freq=%s)", user_id, freq)
            drafts = await generate_drafts(user_id=user_id, count=3)
            logger.info("Content scheduler: created %d drafts for user %s", len(drafts), user_id)
            generated += 1

        except Exception:
            logger.exception("Content scheduler: failed for user %s", user_id)
            errors += 1

    return {
        "checked": len(users),
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
    }


def _is_due(supabase, user_id: str, freq: str, now: datetime) -> bool:
    """Determine if a user is due for new draft generation."""

    # Weekends-only: skip weekdays entirely
    if freq == "weekends_only":
        if now.weekday() not in WEEKEND_DAYS:
            return False
        # On weekend days, check if we already generated today
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        result = (
            supabase.table("content_drafts")
            .select("id")
            .eq("user_id", user_id)
            .gte("created_at", today_start.isoformat())
            .limit(1)
            .execute()
        )
        return len(result.data or []) == 0

    # daily / 3x_weekly: check hours since last draft
    interval_hours = FREQUENCY_INTERVALS.get(freq)
    if interval_hours is None:
        return False

    result = (
        supabase.table("content_drafts")
        .select("created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    if not result.data:
        # No drafts ever — definitely due
        return True

    last_created = datetime.fromisoformat(result.data[0]["created_at"].replace("Z", "+00:00"))
    hours_since = (now - last_created).total_seconds() / 3600
    return hours_since >= interval_hours
