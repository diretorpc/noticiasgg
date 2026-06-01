import logging
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from backend.services import reporter, whatsapp, supabase

logger = logging.getLogger("noticiasgg")
router = APIRouter()

# Captura "Bom dia, Matheus!" e também "Bom dia, *Matheus*!" (nome em negrito WhatsApp)
_GREETING_RE = re.compile(r'((?:Bom dia|Boa tarde|Boa noite),\s+\*?)([\w.()]+)(\*?[!,]?)')

_BRT = timezone(timedelta(hours=-3))


def _current_greeting() -> str:
    h = datetime.now(_BRT).hour
    if 5 <= h < 12:
        return "Bom dia"
    if h < 18:
        return "Boa tarde"
    return "Boa noite"


def _personalize(text: str, user_name: str) -> str:
    """Substitui o nome nas saudações do texto gerado pelo n8n.

    Se o texto não contiver saudação no formato esperado (ex: análise sem
    instrução de greeting), prefixa uma saudação personalizada.
    """
    if not user_name:
        return text
    primeiro_nome = user_name.split()[0]
    result, count = _GREETING_RE.subn(
        lambda m: m.group(1) + primeiro_nome + m.group(3), text
    )
    if count == 0 and not re.match(r'^[📰📊🌎💵🌾🗳️🏛️]', result):
        result = f"{_current_greeting()}, *{primeiro_nome}!*\n\n{result}"
    return result


def _lookup_user(number: str) -> dict | None:
    """Busca usuário pelo telefone, tentando formatos brasileiros com e sem o 9 extra."""
    user = supabase.get_authorized_by_phone(number)
    if user:
        return user
    # Números brasileiros (55 + DDD + número): tenta adicionar ou remover o 9 extra
    if number.startswith("55"):
        if len(number) == 12:  # sem o 9 extra → tenta com
            user = supabase.get_authorized_by_phone(number[:4] + "9" + number[4:])
        elif len(number) == 13:  # com o 9 extra → tenta sem
            user = supabase.get_authorized_by_phone(number[:4] + number[5:])
    return user


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
        user = _lookup_user(number)
        if not user:
            logger.warning("send_report: número não autorizado %s — ignorado", number)
            return {"status": "skipped", "reason": "unauthorized"}

        prefs = supabase.get_preferences(number)

        if prefs and prefs.get("report_time"):
            return {"status": "skipped", "reason": "custom_time"}

        user_name = (user.get("name") or "").strip()
        logger.info("send_report: number=%s user_name=%r", number, user_name)

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
        supabase.save_message(number, "assistant", text)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("send_report error for %s", number)
        return {"status": "error", "detail": str(e)}
