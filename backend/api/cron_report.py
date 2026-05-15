import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, HTTPException

from backend.services import reporter, whatsapp, supabase

logger = logging.getLogger("noticiasgg")
router = APIRouter()


def _current_hour_brt() -> str:
    brt = timezone(timedelta(hours=-3))
    return f"{datetime.now(brt).hour:02d}:00"


@router.get("/api/cron/report")
async def cron_report(request: Request):
    if not request.headers.get("x-vercel-cron"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    hour = _current_hour_brt()
    users = supabase.get_users_for_hour(hour)
    sent = 0

    for user in users:
        try:
            feedback = supabase.get_news_feedback(user["phone"])
            text = reporter.generate_report(
                "Gere o relatório diário.",
                sections=user.get("sections"),
                user_name=user.get("name"),
                news_feedback=feedback,
            )
            whatsapp.send_message(user["phone"], text)
            sent += 1
        except Exception:
            logger.exception("cron_report failed for %s", user["phone"])

    return {"status": "ok", "hour": hour, "sent": sent}
