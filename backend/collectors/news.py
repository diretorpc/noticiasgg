import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

NEWSAPI_EVERYTHING = "https://newsapi.org/v2/everything"
NEWSAPI_HEADLINES = "https://newsapi.org/v2/top-headlines"

SOURCES_EN = ",".join([
    "reuters",
    "the-wall-street-journal",
    "financial-times",
    "the-economist",
    "cnbc",
    "forbes",
    "bbc-news",
    "the-guardian-uk",
    "cnn",
])

_FINANCE_QUERY = (
    "economy OR market OR inflation OR stocks OR bonds OR commodities "
    "OR GDP OR Fed OR interest rate OR trade OR dollar OR oil"
)

_MAX_AGE = timedelta(hours=48)

# RSS feeds públicos sem paywall
_RSS_FEEDS = [
    ("World Economic Forum", "https://www.weforum.org/agenda/feed/rss2"),
    ("DW News", "https://rss.dw.com/rdf/rss-en-all"),
    ("Corriere della Sera", "https://www.corriere.it/rss/homepage.xml"),
    ("Le Monde", "https://www.lemonde.fr/rss/une.xml"),
    ("Japan Times", "https://www.japantimes.co.jp/feed/topstories/"),
    ("Global Times", "https://www.globaltimes.cn/rss/outbrain.xml"),
]


def _is_fresh(published_at: str | None) -> bool:
    if not published_at:
        return True
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - dt <= _MAX_AGE
    except Exception:
        return True


def _parse_rss_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.isoformat()
        except Exception:
            return None


def _collect_rss(client: httpx.Client, feeds: list[tuple[str, str]], vistos: set) -> list[dict]:
    artigos = []
    for source_name, url in feeds:
        try:
            resp = client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            # suporte a RSS 2.0 e RDF
            ns = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}
            items = root.findall(".//item")
            for item in items[:5]:
                link = (item.findtext("link") or "").strip()
                if not link or link in vistos:
                    continue
                title = item.findtext("title") or ""
                pub_date = _parse_rss_date(item.findtext("pubDate") or item.findtext("dc:date"))
                if not _is_fresh(pub_date):
                    continue
                description = item.findtext("description") or ""
                vistos.add(link)
                artigos.append({
                    "titulo": title.strip(),
                    "fonte": source_name,
                    "url": link,
                    "publicado_em": pub_date,
                    "resumo": description[:300].strip() if description else None,
                })
        except Exception:
            continue
    return artigos


def collect() -> list[dict]:
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        raise ValueError("NEWS_API_KEY não configurada")

    artigos = []
    vistos: set = set()

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

        # RSS feeds internacionais
        rss_artigos = _collect_rss(client, _RSS_FEEDS, vistos)
        artigos.extend(rss_artigos)

    return artigos[:30]


@router.get("/api/collectors/news")
async def get_news():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
