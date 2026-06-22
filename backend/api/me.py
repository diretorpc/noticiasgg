from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.services import selflink, supabase, schedules

router = APIRouter()


@router.get("/api/me")
def get_me(phone: str = Depends(selflink.selflink_phone)) -> dict:
    user = supabase.get_authorized_by_phone(phone) or {"phone": phone, "name": ""}
    prefs = supabase.get_preferences(phone) or {}
    grid = schedules.rows_to_grid(schedules.get_for_phone(phone))
    return {
        "name": user.get("name") or "",
        "schedule": grid,
        "sections": prefs.get("sections"),
        "audio": {
            "audio_for_text": prefs.get("audio_for_text"),
            "audio_for_media": prefs.get("audio_for_media"),
            "tts_voice": prefs.get("tts_voice"),
            "tts_speed": prefs.get("tts_speed"),
        },
    }


class MePrefsBody(BaseModel):
    sections: dict | None = None
    audio_for_text: bool | None = None
    audio_for_media: bool | None = None
    tts_voice: str | None = None
    tts_speed: float | None = None


@router.put("/api/me")
def put_me(body: MePrefsBody, phone: str = Depends(selflink.selflink_phone)) -> dict:
    current = supabase.get_preferences(phone) or {}
    supabase.save_preferences(
        phone,
        sections=body.sections,
        report_time=current.get("report_time"),
        audio_for_text=body.audio_for_text,
        audio_for_media=body.audio_for_media,
        tts_voice=body.tts_voice,
        tts_speed=body.tts_speed,
    )
    return {"ok": True}


class MeScheduleBody(BaseModel):
    schedule: dict = {}


@router.put("/api/me/schedule")
def put_me_schedule(body: MeScheduleBody, phone: str = Depends(selflink.selflink_phone)) -> dict:
    rows = schedules.grid_to_rows(phone, body.schedule)
    schedules.replace_for_phone(phone, rows)
    return {"ok": True}
