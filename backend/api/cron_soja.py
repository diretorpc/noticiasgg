import logging

from fastapi import APIRouter, Request

from backend.api.cron_auth import check_cron_secret
from backend.services import soja_digest
from backend.services.secrets_mask import sanitize_error

logger = logging.getLogger("noticiasgg")
router = APIRouter()


@router.get("/api/cron/soja")
async def cron_soja(request: Request, test: bool = False):
    check_cron_secret(request)
    try:
        return soja_digest.run(test_mode=test)
    except Exception as e:
        logger.exception("cron_soja failed")
        detail = sanitize_error(e)
        try:
            # Direto por whatsapp.send_message, fora do cooldown de 2h de
            # notify_admin — ver soja_digest.py, docstring do módulo.
            soja_digest._avisar_admin_direto(
                soja_digest._build_fail_message("cron soja com falha", [f"fatal: {detail}"]))
        except Exception:
            logger.exception("admin notify failed")
        return {"status": "error", "detail": detail}
