import hmac
import logging
import os
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
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    provided = request.headers.get("x-cron-secret", "")
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")

    hour = _current_hour_brt()
    users = supabase.get_users_for_hour(hour)
    sent = 0

    for user in users:
        try:
            text = reporter.generate_report(
                "Gere o relatório diário.",
                sections=user.get("sections"),
                user_name=user.get("name"),
            )
            whatsapp.send_message(user["phone"], text)
            sent += 1
        except Exception:
            logger.exception("cron_report failed for %s", user["phone"])

    return {"status": "ok", "hour": hour, "sent": sent}
