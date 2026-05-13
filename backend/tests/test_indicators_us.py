import pytest
import os
from fastapi.testclient import TestClient
from unittest.mock import patch
from backend.api.main import app

client = TestClient(app)


def test_indicators_us_sem_chave_retorna_500():
    with patch.dict(os.environ, {"FRED_API_KEY": ""}):
        resp = client.get("/api/collectors/indicators-us")
        assert resp.status_code == 500


def test_indicators_us_schema_com_chave(monkeypatch):
    if not os.getenv("FRED_API_KEY"):
        pytest.skip("FRED_API_KEY não configurada")
    resp = client.get("/api/collectors/indicators-us")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "collected_at" in body


def test_indicators_us_campos_por_indicador(monkeypatch):
    if not os.getenv("FRED_API_KEY"):
        pytest.skip("FRED_API_KEY não configurada")
    data = client.get("/api/collectors/indicators-us").json()["data"]
    for indicador in data.values():
        assert "valor" in indicador
        assert "data" in indicador
