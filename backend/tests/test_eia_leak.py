from unittest.mock import patch

import httpx
import pytest

from backend.collectors import eia

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    request = httpx.Request(
        "GET", f"https://api.eia.gov/v2/seriesid/PET.WCESTUS1.W?api_key={_CHAVE_FALSA}"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_collect_nao_vaza_chave_em_erro(monkeypatch):
    """collect() nunca levanta para erro de rede (degrada por série via
    ThreadPoolExecutor) — o vazamento estava em `resultado[nome] = {"erro": str(e)}`,
    que compõe o retorno de /api/collectors/eia."""
    monkeypatch.setenv("EIA_API_KEY", _CHAVE_FALSA)
    with patch("backend.collectors.eia.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.side_effect = _erro_com_chave_na_url()
        result = eia.collect()
    assert result, "esperava um resultado por série, mesmo com erro"
    for entry in result.values():
        assert "erro" in entry
        assert _CHAVE_FALSA not in entry["erro"]
        assert "api_key=***" in entry["erro"]
