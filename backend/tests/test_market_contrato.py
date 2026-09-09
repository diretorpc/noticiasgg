from unittest.mock import patch

import httpx
import pytest

from backend.collectors import market
from backend.services import report_prompts

pytestmark = pytest.mark.unit


@pytest.mark.unit
def test_sp500_usa_o_indice_e_nao_a_cota_do_etf():
    """SPY é cota de ETF (~760); o índice (^GSPC) está em ~7.600. Rotular a
    cota como 'S&P 500' entregava um número 10x menor."""
    assert "SPY" not in market.SYMBOLS
    assert market.SYMBOLS["^GSPC"] == ("bolsas", "S&P 500")


@pytest.mark.unit
def test_exemplo_do_prompt_de_bolsas_nao_ensina_escala_de_cota():
    assert "746,74" not in report_prompts._BOLSAS


@pytest.mark.unit
def test_fallback_scraperapi_usa_https(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-falsa")
    urls = []

    def get_falso(url, **kw):
        urls.append(url)
        return httpx.Response(200, json={"chart": {"result": []}},
                              request=httpx.Request("GET", url))

    with patch("backend.collectors.market.httpx.get", side_effect=get_falso):
        market._fetch_via_scraperapi("^BVSP")
    assert urls and urls[0].startswith("https://api.scraperapi.com/?api_key=")
