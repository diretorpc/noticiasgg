import logging

from fastapi import APIRouter, Request

from backend.api.cron_auth import check_cron_secret
from backend.services import investing_digest, alert_checker

logger = logging.getLogger("noticiasgg")
router = APIRouter()


@router.get("/api/cron/investing")
async def cron_investing(request: Request, test: bool = False):
    check_cron_secret(request)
    try:
        return investing_digest.run(test_mode=test)
    except Exception as e:
        logger.exception("cron_investing failed")
        try:
            alert_checker.notify_admin([f"fatal: {e}"], title="cron investing com falha")
        except Exception:
            logger.exception("admin notify failed")
        return {"status": "error", "detail": str(e)}
