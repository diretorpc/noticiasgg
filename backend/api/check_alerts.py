import logging

from fastapi import APIRouter, Request

from backend.api.cron_auth import check_cron_secret
from backend.services import alert_checker

logger = logging.getLogger("noticiasgg")
router = APIRouter()


@router.get("/api/check-alerts")
async def check_alerts(request: Request, test: bool = False):
    check_cron_secret(request)
    try:
        result = alert_checker.run_checks(test_mode=test)
        return result
    except Exception as e:
        logger.exception("check_alerts failed")
        try:
            alert_checker.notify_admin([f"fatal: {e}"])
        except Exception:
            logger.exception("admin notify failed")
        return {"status": "error", "detail": str(e)}
