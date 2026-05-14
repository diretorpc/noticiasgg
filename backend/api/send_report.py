from fastapi import APIRouter
from pydantic import BaseModel

from backend.services import reporter, whatsapp, supabase

router = APIRouter()


class TextMessage(BaseModel):
    text: str


class SendReportPayload(BaseModel):
    number: str
    textMessage: TextMessage


@router.post("/api/send-report")
async def send_report(payload: SendReportPayload):
    number = payload.number
    n8n_text = payload.textMessage.text

    prefs = supabase.get_preferences(number)

    if prefs and prefs.get("report_time"):
        return {"status": "skipped", "reason": "custom_time"}

    user = supabase.get_authorized_by_phone(number)
    user_name = user.get("name") if user else None

    if prefs and prefs.get("sections"):
        text = reporter.generate_report(
            "Gere o relatório diário.",
            sections=prefs["sections"],
            user_name=user_name,
        )
    else:
        if user_name:
            primeiro_nome = user_name.split()[0]
            text = f"Bom dia, *{primeiro_nome}!* 👋\n\n{n8n_text}"
        else:
            text = n8n_text

    whatsapp.send_message(number, text)
    return {"status": "ok"}
