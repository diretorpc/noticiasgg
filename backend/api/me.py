from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.services import audio_prefs, selflink, supabase, schedules

router = APIRouter()


@router.get("/api/me")
def get_me(phone: str = Depends(selflink.selflink_phone)) -> dict:
    user = supabase.get_authorized_by_phone(phone) or {"phone": phone, "name": ""}
    prefs = supabase.get_preferences(phone) or {}
    grid = schedules.rows_to_grid(schedules.get_for_phone(phone))
    # Sem `sections`: campo morto (ver `test_campo_morto.py`). Seções e horário
    # do relatório vivem só na grade.
    return {
        "name": user.get("name") or "",
        "schedule": grid,
        "audio": {
            "audio_for_text": prefs.get("audio_for_text"),
            "audio_for_media": prefs.get("audio_for_media"),
            "tts_voice": prefs.get("tts_voice"),
            "tts_speed": prefs.get("tts_speed"),
        },
    }


class MePrefsBody(BaseModel):
    # `sections` saiu: aba aberta com o /me antigo ainda o manda, e o Pydantic ignora.
    audio_for_text: bool | None = None
    audio_for_media: bool | None = None
    tts_voice: str | None = None
    tts_speed: float | None = None


@router.put("/api/me")
def put_me(body: MePrefsBody, phone: str = Depends(selflink.selflink_phone)) -> dict:
    valores = body.model_dump()
    ruins = audio_prefs.invalid_fields(valores)
    if ruins:
        raise HTTPException(status_code=422, detail=f"valor inválido: {', '.join(ruins)}")
    supabase.save_preferences(phone, **valores)
    return {"ok": True}


class MeScheduleBody(BaseModel):
    schedule: dict = {}


@router.put("/api/me/schedule")
def put_me_schedule(body: MeScheduleBody, phone: str = Depends(selflink.selflink_phone)) -> dict:
    try:
        rows = schedules.grid_to_rows(phone, body.schedule)
    except (ValueError, TypeError, AttributeError) as e:
        raise HTTPException(status_code=422, detail=f"grade inválida: {e}")
    schedules.replace_for_phone(phone, rows)
    return {"ok": True}
