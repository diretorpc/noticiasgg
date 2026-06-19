import os

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.services import reporter, auth, supabase
from backend.services import media as media_service
from backend.collectors import news

router = APIRouter()


@router.get("/api/admin/agent-config")
def get_agent_config(user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Snapshot read-only da config do agente. Exige auth. Sem secrets."""
    return {
        "agent": reporter.describe_config(),
        "audio": media_service.describe_config(),
        "news": news.describe_config(),
    }


@router.get("/api/admin/newsapi-sources")
def get_newsapi_sources(user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Lista as fontes disponíveis na NewsAPI (id/name/category) para o painel.
    Busca server-side para não expor a NEWS_API_KEY no browser."""
    api_key = os.environ.get("NEWS_API_KEY", "")
    if not api_key:
        return {"sources": []}
    # Degrada para lista vazia se a NewsAPI falhar (429/timeout) — o painel
    # continua editável (RSS, queries) mesmo sem o picker de fontes.
    try:
        resp = httpx.get(
            "https://newsapi.org/v2/top-headlines/sources",
            params={"apiKey": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json().get("sources", [])
    except Exception:
        return {"sources": []}
    sources = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "category": s.get("category"),
            "language": s.get("language"),
            "country": s.get("country"),
        }
        for s in raw
    ]
    return {"sources": sources}


class RssValidateBody(BaseModel):
    url: str


@router.post("/api/admin/validate-rss")
def validate_rss(body: RssValidateBody, user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Valida na hora uma URL de RSS/Atom para o painel (parse + nº de itens)."""
    return news.validate_feed(body.url)


@router.get("/api/admin/users")
def list_users(user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Lista usuários autorizados com suas preferências (para o painel)."""
    out = []
    for u in supabase.list_authorized():
        prefs = supabase.get_preferences(u["phone"])
        out.append({
            "phone": u["phone"],
            "name": u.get("name"),
            "preferences": {
                "sections": prefs.get("sections"),
                "report_time": prefs.get("report_time"),
                "audio_for_text": prefs.get("audio_for_text"),
                "audio_for_media": prefs.get("audio_for_media"),
                "tts_voice": prefs.get("tts_voice"),
                "tts_speed": prefs.get("tts_speed"),
            } if prefs else None,
        })
    return {"users": out}


class UserPrefsBody(BaseModel):
    phone: str
    sections: dict | None = None
    report_time: str | None = None
    audio_for_text: bool | None = None
    audio_for_media: bool | None = None
    tts_voice: str | None = None
    tts_speed: float | None = None


@router.post("/api/admin/user-prefs")
def save_user_prefs(body: UserPrefsBody, user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Salva as preferências de um usuário (edição pelo painel)."""
    supabase.save_preferences(
        body.phone,
        sections=body.sections,
        report_time=body.report_time,
        audio_for_text=body.audio_for_text,
        audio_for_media=body.audio_for_media,
        tts_voice=body.tts_voice,
        tts_speed=body.tts_speed,
    )
    return {"ok": True}


@router.delete("/api/admin/user-prefs/{phone}")
def reset_user_prefs(phone: str, user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Reseta as preferências de um usuário (volta aos defaults)."""
    supabase.delete_preferences(phone)
    return {"ok": True}
