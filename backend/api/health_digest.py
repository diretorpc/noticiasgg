import logging

from fastapi import APIRouter, Request

from backend.api.cron_auth import check_cron_secret
from backend.services import health, alert_checker

logger = logging.getLogger("noticiasgg")
router = APIRouter()


@router.get("/api/health-digest")
async def health_digest(request: Request):
    check_cron_secret(request)
    try:
        return health.send_daily_digest()
    except Exception as e:
        logger.exception("health digest failed")
        try:
            alert_checker.notify_admin([f"health-digest fatal: {e}"])
        except Exception:
            logger.exception("admin notify failed")
        return {"status": "error", "detail": str(e)}
