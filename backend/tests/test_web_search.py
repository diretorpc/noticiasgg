from unittest.mock import patch, MagicMock

import httpx
import pytest

from backend.services import web_search
from backend.services.secrets_mask import sanitize_error

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    """Simula o formato real de httpx.HTTPStatusError: `raise_for_status()`
    monta a mensagem incluindo a URL completa da requisição — e a chave de
    API vai no query string dela."""
    request = httpx.Request(
        "GET", f"https://api.scraperapi.com/?api_key={_CHAVE_FALSA}&url=https://exemplo.com"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


@pytest.mark.unit
def test_sanitize_error_mascara_api_key():
    """A definição mora em backend.services.secrets_mask — achado 6, revisão
    18/08/2026 (4ª rodada): web_search.py mantinha um alias `_sanitize_error`
    só para este teste não precisar mudar. Duas grafias da mesma coisa no
    mesmo módulo; o teste agora aponta pra origem real."""
    erro = _erro_com_chave_na_url()
    saida = sanitize_error(erro)
    assert _CHAVE_FALSA not in saida
    assert "api_key=***" in saida


@pytest.mark.unit
def test_read_article_nao_vaza_chave_em_erro(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.services.web_search.httpx.get", side_effect=_erro_com_chave_na_url()):
        result = web_search.read_article("https://exemplo.com")
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]


@pytest.mark.unit
def test_search_nao_vaza_chave_em_erro(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.services.web_search.httpx.get", side_effect=_erro_com_chave_na_url()):
        result = web_search.search("soja")
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]


@pytest.mark.unit
def test_read_article_sem_chave_nao_faz_requisicao(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    result = web_search.read_article("https://exemplo.com")
    assert result == {"erro": "SCRAPER_API_KEY não configurada"}


@pytest.mark.unit
def test_search_sem_chave_nao_faz_requisicao(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    result = web_search.search("soja")
    assert result == {"erro": "SCRAPER_API_KEY não configurada"}


def _resp_html(html: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = html
    return resp


@pytest.mark.unit
def test_read_article_usa_render_para_link_do_google_noticias(monkeypatch):
    """Medido 18/08/2026: o fetch simples do ScraperAPI devolve 404 para link
    do Google Notícias em 6 de 6 casos reais — render=true resolve. Só pode
    ligar para esse domínio: custa 10x (header sa-credit-cost) e o tráfego
    geral desta tool (usada livremente pelo agente de chat) não pode pagar
    isso sempre."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://news.google.com/rss/articles/abc")
    assert mock_get.call_args.kwargs["params"]["render"] == "true"


@pytest.mark.unit
def test_read_article_nao_usa_render_para_link_normal(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://www.farmprogress.com/artigo")
    assert "render" not in mock_get.call_args.kwargs["params"]


@pytest.mark.unit
def test_read_article_timeout_customizavel(monkeypatch):
    """`alert_checker` precisa de um teto bem maior que os 30s default para
    dar tempo ao render=true (medido: até 49s por link real de GN)."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://www.farmprogress.com/artigo", timeout=75.0)
    assert mock_get.call_args.kwargs["timeout"] == 75.0


@pytest.mark.unit
def test_read_article_timeout_default_preservado(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://www.farmprogress.com/artigo")
    assert mock_get.call_args.kwargs["timeout"] == 30.0
