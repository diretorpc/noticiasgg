import pytest

from backend.tests.conftest import coleta_unica

# Uma chamada real ao Banco Central por rodada, reaproveitada pelos 4 testes.
# Antes eram 4 chamadas (2 conexões cada = 8 por rodada).
resposta_indicadores_br = coleta_unica("/api/collectors/indicators-br")


def test_indicators_br_status_200(resposta_indicadores_br):
    assert resposta_indicadores_br.status_code == 200


def test_indicators_br_schema(resposta_indicadores_br):
    body = resposta_indicadores_br.json()
    assert "data" in body
    assert "collected_at" in body


def test_indicators_br_contem_selic(resposta_indicadores_br):
    chaves = list(resposta_indicadores_br.json()["data"].keys())
    assert any("SELIC" in k for k in chaves)


def test_indicators_br_campos_por_indicador(resposta_indicadores_br):
    for indicador in resposta_indicadores_br.json()["data"].values():
        assert "valor" in indicador
        assert "data" in indicador
