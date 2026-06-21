import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request

from backend.api.cron_auth import check_cron_secret
from backend.services import report_engine, whatsapp, supabase, schedules

logger = logging.getLogger("noticiasgg")
router = APIRouter()

_BRT = timezone(timedelta(hours=-3))


@router.get("/api/cron/report")
async def cron_report(request: Request):
    check_cron_secret(request)

    now = datetime.now(_BRT)
    weekday, hour = now.weekday(), now.hour

    rows = schedules.due_now(weekday, hour)
    enabled = schedules.phones_with_engine_enabled()

    by_phone: dict[str, list[str]] = {}
    for r in rows:
        if r["phone"] in enabled:
            by_phone.setdefault(r["phone"], []).append(r["section"])

    sent = failed = 0
    for phone, sections in by_phone.items():
        try:
            user = supabase.get_authorized_by_phone(phone) or {"phone": phone, "name": ""}
            messages = report_engine.generate_sections({s: True for s in sections}, user)
            for msg in messages:
                whatsapp.send_message(phone, msg)
            sent += 1
        except Exception:
            logger.exception("cron_report falhou para %s", phone)
            failed += 1

    return {"status": "ok", "weekday": weekday, "hour": hour,
            "users": len(by_phone), "sent": sent, "failed": failed}
