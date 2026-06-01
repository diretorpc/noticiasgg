import os
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

NEWSAPI_EVERYTHING = "https://newsapi.org/v2/everything"
NEWSAPI_HEADLINES = "https://newsapi.org/v2/top-headlines"

SOURCES_EN = ",".join([
    "reuters",
    "bloomberg",
    "the-wall-street-journal",
    "financial-times",
    "the-economist",
    "cnbc",
    "forbes",
])

_FINANCE_QUERY = (
    "economy OR market OR inflation OR stocks OR bonds OR commodities "
    "OR GDP OR Fed OR interest rate OR trade OR dollar OR oil"
)

_MAX_AGE = timedelta(hours=48)


def _is_fresh(published_at: str | None) -> bool:
    """Retorna False se o artigo tiver mais de 48h."""
    if not published_at:
        return True
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - dt <= _MAX_AGE
    except Exception:
        return True


def collect() -> list[dict]:
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        raise ValueError("NEWS_API_KEY não configurada")

    artigos = []
    vistos = set()

    with httpx.Client(timeout=15) as client:
        # EN: /everything filtrado por fontes financeiras + keywords
        resp_en = client.get(NEWSAPI_EVERYTHING, params={
            "apiKey": api_key,
            "sources": SOURCES_EN,
            "q": _FINANCE_QUERY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 15,
        })
        if resp_en.status_code == 200:
            for a in resp_en.json().get("articles", []):
                url = a.get("url", "")
                published_at = a.get("publishedAt")
                if url in vistos or not _is_fresh(published_at):
                    continue
                vistos.add(url)
                artigos.append({
                    "titulo": a.get("title"),
                    "fonte": (a.get("source") or {}).get("name"),
                    "url": url,
                    "publicado_em": published_at,
                    "resumo": a.get("description"),
                })

        # BR: top-headlines categoria business
        resp_br = client.get(NEWSAPI_HEADLINES, params={
            "apiKey": api_key,
            "country": "br",
            "category": "business",
            "pageSize": 10,
        })
        if resp_br.status_code == 200:
            for a in resp_br.json().get("articles", []):
                url = a.get("url", "")
                published_at = a.get("publishedAt")
                if url in vistos or not _is_fresh(published_at):
                    continue
                vistos.add(url)
                artigos.append({
                    "titulo": a.get("title"),
                    "fonte": (a.get("source") or {}).get("name"),
                    "url": url,
                    "publicado_em": published_at,
                    "resumo": a.get("description"),
                })

    return artigos[:20]


@router.get("/api/collectors/news")
async def get_news():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
