from unittest.mock import patch

import httpx
import pytest

from backend.collectors import esalq

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    request = httpx.Request(
        "GET", f"https://api.scraperapi.com/?api_key={_CHAVE_FALSA}&url=https://www.cepea.esalq.usp.br/"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_collect_nao_vaza_chave_em_erro(monkeypatch):
    """collect() nunca levanta (sempre devolve {"erro": ...}) — o vazamento
    real estava em `last_err = str(e)`, que compõe esse dict de retorno."""
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.collectors.esalq.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.side_effect = _erro_com_chave_na_url()
        result = esalq.collect()
    assert "erro" in result
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]
