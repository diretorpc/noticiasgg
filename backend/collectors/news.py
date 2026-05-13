import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"

ALLOWED_SOURCES = {
    "reuters", "bloomberg", "the-wall-street-journal", "financial-times",
    "g1", "valor-economico", "infomoney", "exame",
}

QUERIES = [
    {"q": "mercado financeiro OR bolsa OR economia", "language": "pt"},
    {"q": "stock market OR economy OR finance", "language": "en"},
]


def collect() -> list[dict]:
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        raise ValueError("NEWS_API_KEY não configurada")

    artigos = []
    vistos = set()

    with httpx.Client(timeout=15) as client:
        for query_params in QUERIES:
            params = {
                "apiKey": api_key,
                "pageSize": 10,
                **query_params,
            }
            resp = client.get(NEWSAPI_URL, params=params)
            resp.raise_for_status()

            for a in resp.json().get("articles", []):
                url = a.get("url", "")
                source_id = (a.get("source") or {}).get("id") or ""

                if url in vistos:
                    continue
                if source_id and source_id not in ALLOWED_SOURCES:
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
