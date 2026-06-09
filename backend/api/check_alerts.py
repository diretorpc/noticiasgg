import hmac
import logging
import os

from fastapi import APIRouter, HTTPException, Request

from backend.services import alert_checker

logger = logging.getLogger("noticiasgg")
router = APIRouter()


@router.get("/api/check-alerts")
async def check_alerts(request: Request, test: bool = False):
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    provided = request.headers.get("x-cron-secret", "")
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
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
