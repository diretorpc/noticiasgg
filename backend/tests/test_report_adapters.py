import pytest
from backend.services import report_engine as re


@pytest.mark.unit
def test_adapt_bolsas_extracts_bolsas_slice():
    market = {"bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1}},
              "cambio": {"USD/BRL": {"preco": 5.17, "variacao_pct": 0.18}}}
    out = re.adapt_bolsas(market)
    assert out == {"data": {"bolsas": {"IBOVESPA": {"preco": 168277.55, "variacao_pct": -0.1}}}}


@pytest.mark.unit
def test_adapt_bolsas_handles_collector_error():
    out = re.adapt_bolsas({"erro": "boom"})
    assert out == {"data": {"bolsas": {}}}


@pytest.mark.unit
def test_adapt_cambio_cripto_merges_cambio_and_crypto():
    market = {"bolsas": {}, "cambio": {"USD/BRL": {"preco": 5.17, "variacao_pct": 0.18}}}
    crypto = [{"simbolo": "BTC", "preco_usd": 64000, "variacao_24h_pct": -1.2}]
    out = re.adapt_cambio_cripto(market, crypto)
    assert out["data"]["cambio"]["USD/BRL"]["preco"] == 5.17
    assert out["data"]["cripto"] == crypto


@pytest.mark.unit
def test_adapt_commodities_wraps_output():
    comm = {"Boi Gordo SP": {"preco": 353.4, "variacao_pct": -0.11}}
    assert re.adapt_commodities(comm) == {"data": {"commodities": comm}}


@pytest.mark.unit
def test_adapt_noticias_wraps_list():
    news = [{"titulo": "X", "fonte": "Y"}]
    assert re.adapt_noticias(news) == {"data": {"noticias": news}}


@pytest.mark.unit
def test_adapt_analise_includes_all_sources():
    out = re.adapt_analise({"bolsas": {"IBOVESPA": {}}, "cambio": {"USD/BRL": {}}},
                           [{"simbolo": "BTC"}], {"selic": 13.75}, {"cpi": 3.1},
                           [{"titulo": "X"}])
    d = out["data"]
    assert set(d) == {"bolsas", "cambio", "cripto", "indicadores_br", "indicadores_us", "noticias"}


@pytest.mark.unit
def test_adapt_politica_wraps_both_lists():
    out = re.adapt_politica([{"titulo": "P"}], [{"instituto": "Datafolha"}])
    assert out == {"data": {"politica": [{"titulo": "P"}], "pesquisas": [{"instituto": "Datafolha"}]}}
