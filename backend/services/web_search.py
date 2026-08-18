import os
import re
import httpx
from bs4 import BeautifulSoup

from backend.services.secrets_mask import sanitize_error

SCRAPER_API_URL = "https://api.scraperapi.com/structured/google/search"
SCRAPER_FETCH_URL = "https://api.scraperapi.com/"

_MAX_ARTICLE_CHARS = 4000


def _is_google_news_link(url: str) -> bool:
    return "news.google.com" in (url or "")


def read_article(url: str, timeout: float = 30.0) -> dict:
    """Lê o texto de um artigo via ScraperAPI.

    Google Notícias entrega uma página de redirecionamento em JS: o fetch
    simples do ScraperAPI devolve 404 para ela SEMPRE (medido 18/08/2026, 6
    de 6 links reais dos feeds "GN *"). `render=true` executa o JS e chega no
    artigo do publicador real — mesma medição: 6 de 6 passaram a devolver
    texto legível, mas em 18-49s (contra poucos segundos do fetch simples) e
    a 10 créditos por chamada em vez de 1 (header `sa-credit-cost` do
    ScraperAPI). Por isso só liga automaticamente para link do Google — nunca
    para o tráfego geral desta ferramenta, que o agente de chat também usa
    livremente via a tool `read_article`. `timeout` é parâmetro do chamador
    de propósito: o caminho de captura do alerta (`alert_checker.py`) precisa
    de um teto bem maior que os 30s default para dar tempo ao render.
    """
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return {"erro": "SCRAPER_API_KEY não configurada"}
    params = {"api_key": api_key, "url": url}
    if _is_google_news_link(url):
        params["render"] = "true"
    try:
        resp = httpx.get(
            SCRAPER_FETCH_URL,
            params=params,
            timeout=timeout,
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
        return {"erro": sanitize_error(e), "url": url}


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
        return {"erro": sanitize_error(e), "resultados": []}
