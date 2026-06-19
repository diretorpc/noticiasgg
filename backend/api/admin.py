import os

import httpx
from fastapi import APIRouter, Depends

from backend.services import reporter, auth
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
    resp = httpx.get(
        "https://newsapi.org/v2/top-headlines/sources",
        params={"apiKey": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    raw = resp.json().get("sources", [])
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
