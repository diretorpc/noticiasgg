import pytest

from backend.tests.conftest import coleta_unica

# Uma chamada real ao Yahoo Finance por rodada, reaproveitada pelos 4 testes.
# Antes eram 4 chamadas (10 conexões cada = 40 por rodada).
resposta_market = coleta_unica("/api/collectors/market")


def test_market_status_200(resposta_market):
    assert resposta_market.status_code == 200


def test_market_schema(resposta_market):
    body = resposta_market.json()
    assert "data" in body
    assert "collected_at" in body


def test_market_categorias(resposta_market):
    data = resposta_market.json()["data"]
    assert "bolsas" in data
    assert "cambio" in data


def test_market_bolsas_campos(resposta_market):
    bolsas = resposta_market.json()["data"]["bolsas"]
    for ativo in bolsas.values():
        assert "preco" in ativo
        assert "variacao_pct" in ativo
