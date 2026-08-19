import os
import re
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from backend.services.secrets_mask import sanitize_error

SCRAPER_API_URL = "https://api.scraperapi.com/structured/google/search"
SCRAPER_FETCH_URL = "https://api.scraperapi.com/"

_MAX_ARTICLE_CHARS = 4000

# Piso de timeout quando render=true está ligado (ver read_article). Medido
# 18/08/2026 (revisão do Apolo, achado 2): 4 chamadas reais com render deram
# 37,4 / 38,5 / 52,3 / 56,6s — as 4 acima de 30s, o default do chamador. Sem
# piso, o caminho de chat (timeout default 30s) paga os créditos do render e
# ainda assim volta com {"erro": "timeout ao buscar artigo"} — pior dos dois
# mundos. 75.0 é o mesmo valor de `alert_checker._CONTEUDO_TIMEOUT`.
_RENDER_TIMEOUT_FLOOR = 75.0


def _is_google_news_link(url: str) -> bool:
    """Compara o HOST da URL, não substring (achado 3, revisão do Apolo,
    18/08/2026: `"news.google.com" in url` casava `https://evil.com/?x=news.google.com`,
    ligando render=true — 35 créditos e ~50s desperdiçados — para um link que
    não é do Google Notícias)."""
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return host == "news.google.com" or host.endswith(".news.google.com")


def read_article(url: str, timeout: float = 30.0) -> dict:
    """Lê o texto de um artigo via ScraperAPI.

    Google Notícias entrega uma página de redirecionamento em JS: o fetch
    simples do ScraperAPI devolve 404 para ela SEMPRE (medido 18/08/2026, 6
    de 6 links reais dos feeds "GN *"). `render=true` executa o JS e chega no
    artigo do publicador real — medição refeita na revisão do Apolo (achado
    5, mesma data): 5 chamadas reais lendo o header `sa-credit-cost` deram
    **35 créditos por chamada** (não 10) e **37,4-56,6s** (não 18-49s); 1 das
    4 chamadas com render devolveu HTTP 500. Por isso só liga automaticamente
    para link do Google — nunca para o tráfego geral desta ferramenta, que o
    agente de chat também usa livremente via a tool `read_article`. `timeout`
    é parâmetro do chamador de propósito: o caminho de captura do alerta
    (`alert_checker.py`) precisa de um teto bem maior que os 30s default para
    dar tempo ao render — e quando render está ligado, esta função IMPÕE um
    piso de `_RENDER_TIMEOUT_FLOOR` (75s) mesmo que o chamador passe menos,
    porque o caminho de chat (timeout default 30s) também pode receber uma
    URL do Google Notícias colada pelo usuário.
    """
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return {"erro": "SCRAPER_API_KEY não configurada"}
    params = {"api_key": api_key, "url": url}
    if _is_google_news_link(url):
        params["render"] = "true"
        timeout = max(timeout, _RENDER_TIMEOUT_FLOOR)
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
