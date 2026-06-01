import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

NEWSAPI_URL = "https://newsapi.org/v2/everything"
_MAX_AGE = timedelta(hours=72)

QUERIES = [
    "política Brasil eleições 2026",
    "Lula governo economia reforma",
    "congresso senado câmara votação",
    "banco central selic fiscal déficit",
    "candidatos eleições 2026 pesquisa",
]


def collect() -> list[dict]:
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        raise ValueError("NEWS_API_KEY não configurada")

    artigos = []
    vistos = set()

    with httpx.Client(timeout=15) as client:
        for q in QUERIES:
            params = {
                "apiKey": api_key,
                "q": q,
                "language": "pt",
                "sortBy": "publishedAt",
                "pageSize": 5,
            }
            resp = client.get(NEWSAPI_URL, params=params)
            if resp.status_code != 200:
                continue

            for a in resp.json().get("articles", []):
                url = a.get("url", "")
                published_at = a.get("publishedAt")
                if url in vistos:
                    continue
                if published_at:
                    try:
                        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                        if datetime.now(timezone.utc) - dt > _MAX_AGE:
                            continue
                    except Exception:
                        pass
                vistos.add(url)
                artigos.append({
                    "titulo": a.get("title"),
                    "fonte": (a.get("source") or {}).get("name"),
                    "url": url,
                    "publicado_em": a.get("publishedAt"),
                    "resumo": a.get("description"),
                })

    return artigos[:20]


@router.get("/api/collectors/politics-br")
async def get_politics_br():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
