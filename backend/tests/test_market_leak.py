from unittest.mock import patch

import httpx
import pytest

from backend.collectors import market

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    """market.py monta a URL do ScraperAPI manualmente com a chave embutida
    (`f"http://api.scraperapi.com?api_key={key}&..."`) — o mesmo desenho de
    web_search/agro_search, só que sem passar por `params=`."""
    request = httpx.Request(
        "GET", f"http://api.scraperapi.com/?api_key={_CHAVE_FALSA}&premium=true&url=https://query1.finance.yahoo.com"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_fetch_via_scraperapi_nao_vaza_chave_em_erro(monkeypatch):
    """collect() injeta a saída inteira no prompt de toda conversa do agente
    (reporter.py::_collect_all) — não é um caminho de exceção raro, é o
    caminho normal sempre que uma cotação falha via ScraperAPI."""
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.collectors.market.httpx.get", side_effect=_erro_com_chave_na_url()):
        result = market._fetch_via_scraperapi("^BVSP")
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]


def test_fetch_all_scraperapi_nao_vaza_chave_em_erro(monkeypatch):
    """Mesmo achado, no branch paralelo (ThreadPoolExecutor) usado quando o
    Yahoo Finance direto falha para múltiplos símbolos ao mesmo tempo."""
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.collectors.market.httpx.get", side_effect=_erro_com_chave_na_url()):
        result = market._fetch_all_scraperapi({"^BVSP": ("bolsas", "IBOVESPA")})
    erro = result[("bolsas", "IBOVESPA")]["erro"]
    assert _CHAVE_FALSA not in erro
    assert "api_key=***" in erro
