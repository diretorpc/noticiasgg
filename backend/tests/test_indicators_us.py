import os

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from backend.api.main import app

from backend.tests.conftest import coleta_unica

client = TestClient(app)

# Uma chamada real à FRED por rodada, reaproveitada pelos testes de contrato.
# Antes eram 2 chamadas (4 conexões cada = 8 por rodada).
resposta_indicadores_us = coleta_unica("/api/collectors/indicators-us", "FRED_API_KEY")


def test_indicators_us_sem_chave_retorna_500():
    # Não usa a fixture de propósito: aqui o alvo é o caminho SEM chave.
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/collectors/indicators-us")
        assert resp.status_code == 500


def test_indicators_us_schema_com_chave(resposta_indicadores_us):
    assert resposta_indicadores_us.status_code == 200
    body = resposta_indicadores_us.json()
    assert "data" in body
    assert "collected_at" in body


def test_indicators_us_campos_por_indicador(resposta_indicadores_us):
    for indicador in resposta_indicadores_us.json()["data"].values():
        assert "valor" in indicador
        assert "data" in indicador
