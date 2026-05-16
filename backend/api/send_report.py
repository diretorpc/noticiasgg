import logging
import re

from fastapi import APIRouter
from pydantic import BaseModel

from backend.services import reporter, whatsapp, supabase

logger = logging.getLogger("noticiasgg")
router = APIRouter()

_GREETING_RE = re.compile(r'((?:Bom dia|Boa tarde|Boa noite),\s+)([\w.()]+)([!,]?)')


def _personalize(text: str, user_name: str) -> str:
    """Substitui o nome nas saudações do texto gerado pelo n8n."""
    if not user_name:
        return text
    primeiro_nome = user_name.split()[0]
    return _GREETING_RE.sub(lambda m: m.group(1) + primeiro_nome + m.group(3), text)


class TextMessage(BaseModel):
    text: str


class SendReportPayload(BaseModel):
    number: str
    textMessage: TextMessage
    isFirst: bool = False


@router.post("/api/send-report")
async def send_report(payload: SendReportPayload):
    number = payload.number
    n8n_text = payload.textMessage.text

    try:
        prefs = supabase.get_preferences(number)

        if prefs and prefs.get("report_time"):
            return {"status": "skipped", "reason": "custom_time"}

        user = supabase.get_authorized_by_phone(number)
        user_name = (user.get("name") or "").strip() if user else ""

        if prefs and prefs.get("sections"):
            try:
                text = reporter.generate_report(
                    "Gere o relatório diário.",
                    sections=prefs["sections"],
                    user_name=user_name or None,
                )
            except Exception:
                logger.warning("generate_report failed for %s, falling back to n8n text", number)
                text = _personalize(n8n_text, user_name)
        else:
            text = _personalize(n8n_text, user_name)

        whatsapp.send_message(number, text)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("send_report error for %s", number)
        return {"status": "error", "detail": str(e)}
