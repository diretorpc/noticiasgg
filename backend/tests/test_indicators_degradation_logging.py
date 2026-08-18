import logging
from unittest.mock import patch

import httpx
import pytest

from backend.collectors import indicators_us, eia

pytestmark = pytest.mark.unit

_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave(url: str) -> Exception:
    request = httpx.Request("GET", url)
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_indicators_us_loga_aviso_por_serie_falha(monkeypatch, caplog):
    """Achado 5, revisão 18/08/2026 (4ª rodada): o `except` de indicators_us.collect()
    não logava nada — FRED caído 4/4 não deixava uma linha no log. Sem log, o
    boletim de saúde não tinha como saber que a degradação aconteceu."""
    monkeypatch.setenv("FRED_API_KEY", _CHAVE_FALSA)
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={_CHAVE_FALSA}"
    with patch("backend.collectors.indicators_us.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.side_effect = _erro_com_chave(url)
        with caplog.at_level(logging.WARNING, logger="noticiasgg"):
            indicators_us.collect()
    assert caplog.text, "esperava pelo menos uma linha de log por série falha"
    assert _CHAVE_FALSA not in caplog.text
    assert "api_key=***" in caplog.text


def test_eia_loga_aviso_por_serie_falha(monkeypatch, caplog):
    """Mesmo buraco em eia.py:80 — 3 séries falhando não deixavam rastro."""
    monkeypatch.setenv("EIA_API_KEY", _CHAVE_FALSA)
    url = f"https://api.eia.gov/v2/seriesid/PET.WCESTUS1.W?api_key={_CHAVE_FALSA}"
    with patch("backend.collectors.eia.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.side_effect = _erro_com_chave(url)
        with caplog.at_level(logging.WARNING, logger="noticiasgg"):
            eia.collect()
    assert caplog.text, "esperava pelo menos uma linha de log por série falha"
    assert _CHAVE_FALSA not in caplog.text
    assert "api_key=***" in caplog.text
