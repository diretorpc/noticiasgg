import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

from backend.services import config

load_dotenv()

router = APIRouter()

NEWSAPI_EVERYTHING = "https://newsapi.org/v2/everything"
NEWSAPI_HEADLINES = "https://newsapi.org/v2/top-headlines"

SOURCES_FINANCE = ",".join([
    "reuters",
    "the-wall-street-journal",
    "financial-times",
    "the-economist",
    "cnbc",
    "forbes",
    "bbc-news",
    "the-guardian-uk",
    "cnn",
    "associated-press",
    "the-washington-post",
    "business-insider",
    "politico",
])

SOURCES_TECH = ",".join([
    "techcrunch",
    "wired",
    "the-verge",
    "ars-technica",
])

_FINANCE_QUERY = (
    "economy OR market OR inflation OR stocks OR bonds OR commodities "
    "OR GDP OR Fed OR interest rate OR trade OR dollar OR oil "
    "OR OPEC OR USDA OR crop OR harvest OR drought OR \"La Nina\" OR \"El Nino\" "
    "OR PMI OR China OR sanctions OR tariff OR freight OR fertilizer"
)

_AI_QUERY = (
    '"artificial intelligence" OR "machine learning" OR "LLM" OR '
    '"OpenAI" OR "Anthropic" OR "Google AI" OR "generative AI" OR '
    '"AI model" OR "large language model"'
)

_MAX_AGE = timedelta(hours=48)

# RSS feeds internacionais sem paywall
_RSS_FEEDS = [
    ("World Economic Forum", "https://www.weforum.org/agenda/feed/rss2"),
    ("DW News", "https://rss.dw.com/rdf/rss-en-all"),
    ("Corriere della Sera", "https://www.corriere.it/rss/homepage.xml"),
    ("Le Monde", "https://www.lemonde.fr/rss/une.xml"),
    ("Japan Times", "https://www.japantimes.co.jp/feed/topstories/"),
    ("Global Times", "https://www.globaltimes.cn/rss/outbrain.xml"),
]

# RSS feeds especializados em IA
_RSS_FEEDS_AI = [
    ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
]


def _sources_param(key: str, default_csv: str) -> str:
    """Lista de fontes do config (list[str]) → CSV; senão o default CSV."""
    val = config.get("news." + key, None)
    if isinstance(val, list) and val:
        return ",".join(str(s) for s in val)
    return default_csv


def _feeds(key: str, default_tuples: list[tuple]) -> list[tuple]:
    """Feeds do config (list[{nome,url}]) → list[(nome,url)]; senão o default."""
    val = config.get("news." + key, None)
    if isinstance(val, list) and val:
        out = [
            (str(f.get("nome", "")), f["url"])
            for f in val
            if isinstance(f, dict) and isinstance(f.get("url"), str) and f.get("url")
        ]
        if out:
            return out
    # cópia: devolver a lista-constante do módulo deixaria um caller mutá-la
    # (ex.: `feeds += ...`) e corromper o default para todo o processo — a função
    # da Vercel reaproveita a instância entre requisições.
    return list(default_tuples)


def _parse_feed(content: bytes) -> dict:
    """Parseia bytes de um feed RSS/Atom. Retorna validade, nº de itens e
    o título do primeiro item. Puro (sem rede) para facilitar teste."""
    try:
        root = ET.fromstring(content)
    except Exception:
        return {"valid": False, "item_count": 0, "sample_title": None,
                "error": "conteúdo não é XML"}
    items = root.findall(".//item")
    if not items:
        items = [e for e in root.iter() if e.tag.endswith("entry")]  # Atom
    if not items:
        return {"valid": False, "item_count": 0, "sample_title": None,
                "error": "feed sem itens (<item>/<entry>)"}
    sample = None
    for child in items[0].iter():
        if child.tag.endswith("title") and child.text and child.text.strip():
            sample = child.text.strip()
            break
    return {"valid": True, "item_count": len(items), "sample_title": sample, "error": None}


def validate_feed(url: str) -> dict:
    """Busca uma URL de RSS/Atom e valida o conteúdo. Nunca levanta exceção."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=10)
    except Exception:
        return {"valid": False, "item_count": 0, "sample_title": None,
                "error": "falha ao buscar a URL"}
    if resp.status_code != 200:
        return {"valid": False, "item_count": 0, "sample_title": None,
                "error": f"HTTP {resp.status_code}"}
    return _parse_feed(resp.content)


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


def _fetch_newsapi(client: httpx.Client, url: str, params: dict, vistos: set,
                   errors: list[str] | None, label: str) -> list[dict]:
    resp = client.get(url, params=params)
    if resp.status_code != 200:
        # 429 = limite diário do free tier estourado — reportar para o auto-alerta
        if errors is not None:
            errors.append(f"newsapi {label}: HTTP {resp.status_code}")
        return []
    artigos = []
    for a in resp.json().get("articles", []):
        article_url = a.get("url", "")
        published_at = a.get("publishedAt")
        if article_url in vistos or not _is_fresh(published_at):
            continue
        vistos.add(article_url)
        artigos.append({
            "titulo": a.get("title"),
            "fonte": (a.get("source") or {}).get("name"),
            "url": article_url,
            "publicado_em": published_at,
            "resumo": a.get("description"),
        })
    return artigos


def collect(include_ai: bool = True, include_newsapi: bool = True,
            errors: list[str] | None = None) -> list[dict]:
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        raise ValueError("NEWS_API_KEY não configurada")

    artigos = []
    vistos: set = set()

    with httpx.Client(timeout=15) as client:
        if include_newsapi:
            # Finanças: /everything filtrado por fontes financeiras + keywords
            artigos.extend(_fetch_newsapi(client, NEWSAPI_EVERYTHING, {
                "apiKey": api_key,
                "sources": _sources_param("sources_finance", SOURCES_FINANCE),
                "q": config.get_str("news.finance_query", _FINANCE_QUERY),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 15,
            }, vistos, errors, "finance"))

            # BR: top-headlines categoria business
            artigos.extend(_fetch_newsapi(client, NEWSAPI_HEADLINES, {
                "apiKey": api_key,
                "country": "br",
                "category": "business",
                "pageSize": 10,
            }, vistos, errors, "br"))

            # IA/Tech: /everything com fontes tech + query de IA
            if include_ai:
                artigos.extend(_fetch_newsapi(client, NEWSAPI_EVERYTHING, {
                    "apiKey": api_key,
                    "sources": _sources_param("sources_tech", SOURCES_TECH),
                    "q": config.get_str("news.ai_query", _AI_QUERY),
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                }, vistos, errors, "ai"))

        # RSS internacionais são grátis e sempre coletados; os de IA seguem o
        # include_ai, igual ao bloco de IA do NewsAPI acima. Sem isso o alert_checker
        # pedia include_ai=False e mesmo assim recebia MIT Tech Review/VentureBeat,
        # que ocupavam as 5 vagas de classificação com artigos de nota 1 e deixavam
        # a notícia de mundo/economia na fila (visto em produção 21/07/2026).
        feeds = _feeds("rss_feeds", _RSS_FEEDS)
        if include_ai:
            feeds = feeds + _feeds("rss_feeds_ai", _RSS_FEEDS_AI)  # sem += : não muta a lista de origem
        artigos.extend(_collect_rss(client, feeds, vistos))

    return artigos[:40]


def describe_config() -> dict:
    """Snapshot read-only da config efetiva (override do banco ou default)."""
    return {
        "sources_finance": _sources_param("sources_finance", SOURCES_FINANCE).split(","),
        "sources_tech": _sources_param("sources_tech", SOURCES_TECH).split(","),
        "finance_query": config.get_str("news.finance_query", _FINANCE_QUERY),
        "ai_query": config.get_str("news.ai_query", _AI_QUERY),
        "rss_feeds": [{"nome": n, "url": u} for n, u in _feeds("rss_feeds", _RSS_FEEDS)],
        "rss_feeds_ai": [{"nome": n, "url": u} for n, u in _feeds("rss_feeds_ai", _RSS_FEEDS_AI)],
    }


@router.get("/api/collectors/news")
async def get_news():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
