import pytest
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)


def test_indicators_br_status_200():
    resp = client.get("/api/collectors/indicators-br")
    assert resp.status_code == 200


def test_indicators_br_schema():
    body = client.get("/api/collectors/indicators-br").json()
    assert "data" in body
    assert "collected_at" in body


def test_indicators_br_contem_selic():
    data = client.get("/api/collectors/indicators-br").json()["data"]
    chaves = list(data.keys())
    assert any("SELIC" in k for k in chaves)


def test_indicators_br_campos_por_indicador():
    data = client.get("/api/collectors/indicators-br").json()["data"]
    for indicador in data.values():
        assert "valor" in indicador
        assert "data" in indicador
