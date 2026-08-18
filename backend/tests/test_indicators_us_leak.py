from unittest.mock import patch

import httpx
import pytest

from backend.collectors import indicators_us

pytestmark = pytest.mark.unit

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    request = httpx.Request(
        "GET", f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={_CHAVE_FALSA}"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_collect_nao_vaza_chave_em_erro_e_nao_derruba_as_outras_series(monkeypatch):
    """Antes deste fix, `collect()` não tinha NENHUM try/except em volta de
    `_fetch_series`: uma série com erro HTTP derrubava o loop inteiro e subia
    até `_safe_collect` (reporter.py) com a FRED_API_KEY na mensagem — indo
    pro contexto do agente em toda conversa. Achado extra, não estava na
    lista original do levantamento."""
    monkeypatch.setenv("FRED_API_KEY", _CHAVE_FALSA)
    with patch("backend.collectors.indicators_us.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.side_effect = _erro_com_chave_na_url()
        result = indicators_us.collect()

    assert set(result.keys()) == set(indicators_us.SERIES.values())
    for entry in result.values():
        assert "erro" in entry
        assert _CHAVE_FALSA not in entry["erro"]
        assert "api_key=***" in entry["erro"]
