import os
import re
import httpx
from bs4 import BeautifulSoup

SCRAPER_API_URL = "https://api.scraperapi.com/structured/google/search"
SCRAPER_FETCH_URL = "https://api.scraperapi.com/"

_MAX_ARTICLE_CHARS = 4000


def read_article(url: str) -> dict:
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return {"erro": "SCRAPER_API_KEY não configurada"}
    try:
        resp = httpx.get(
            SCRAPER_FETCH_URL,
            params={"api_key": api_key, "url": url},
            timeout=30,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()
        return {"url": url, "conteudo": text[:_MAX_ARTICLE_CHARS]}
    except httpx.TimeoutException:
        return {"erro": "timeout ao buscar artigo", "url": url}
    except Exception as e:
        return {"erro": str(e), "url": url}


def search(query: str) -> dict:
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return {"erro": "SCRAPER_API_KEY não configurada"}
    try:
        params = {
            "api_key": api_key,
            "query": query,
            "country": "br",
            "num_results": 5,
        }
        resp = httpx.get(SCRAPER_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        organic = data.get("organic_results", [])
        resultados = [
            {"titulo": r.get("title", ""), "snippet": r.get("snippet", ""), "link": r.get("link", "")}
            for r in organic
        ]
        return {"resultados": resultados, "query": query}
    except httpx.TimeoutException:
        return {"erro": "timeout na busca", "resultados": []}
    except Exception as e:
        return {"erro": str(e), "resultados": []}
