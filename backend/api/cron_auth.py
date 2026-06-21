import hmac
import os

from fastapi import HTTPException, Request


def check_cron_secret(request: Request) -> None:
    """Valida o segredo de cron. Aceita `Authorization: Bearer <CRON_SECRET>`
    (cron nativo da Vercel) ou o header `x-cron-secret` (n8n)."""
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    auth = request.headers.get("authorization", "")
    bearer = auth[7:] if auth[:7].lower() == "bearer " else ""
    provided = request.headers.get("x-cron-secret", "") or bearer
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
