from unittest.mock import patch

import httpx
import pytest

from backend.services import agro_search

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    request = httpx.Request(
        "GET",
        f"https://api.scraperapi.com/structured/google/search"
        f"?api_key={_CHAVE_FALSA}&query=soja",
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


@pytest.mark.unit
def test_agro_search_nao_vaza_chave_em_erro(monkeypatch):
    """Irmão de test_web_search: `agro_search` tem o MESMO desenho (chave no
    query string) e devolvia `str(e)` cru. O dict de erro vira tool_result do
    Claude e é gravado no conversation_history — a chave saía por WhatsApp."""
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.services.agro_search.httpx.get",
               side_effect=_erro_com_chave_na_url()):
        result = agro_search.search("preço da soja")
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]


@pytest.mark.unit
def test_agro_search_sem_chave_nao_faz_requisicao(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    result = agro_search.search("preço da soja")
    assert result == {"erro": "SCRAPER_API_KEY não configurada"}
