import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"

# Fontes confiáveis suportadas pela NewsAPI (plano free exige sources ou country)
SOURCES_EN = "reuters,bloomberg,the-wall-street-journal,financial-times,the-economist"
SOURCES_BR = "google-news-br"


def collect() -> list[dict]:
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        raise ValueError("NEWS_API_KEY não configurada")

    artigos = []
    vistos = set()

    queries = [
        {"sources": SOURCES_EN, "pageSize": 10},
        {"country": "br", "category": "business", "pageSize": 10},
    ]

    with httpx.Client(timeout=15) as client:
        for params in queries:
            resp = client.get(NEWSAPI_URL, params={"apiKey": api_key, **params})
            if resp.status_code != 200:
                continue

            for a in resp.json().get("articles", []):
                url = a.get("url", "")
                if url in vistos:
                    continue
                vistos.add(url)
                artigos.append({
                    "titulo": a.get("title"),
                    "fonte": (a.get("source") or {}).get("name"),
                    "url": url,
                    "publicado_em": a.get("publishedAt"),
                    "resumo": a.get("description"),
                })

    return artigos[:15]


@router.get("/api/collectors/news")
async def get_news():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
