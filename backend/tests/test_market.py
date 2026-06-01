import pytest
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)


def test_market_status_200():
    resp = client.get("/api/collectors/market")
    assert resp.status_code == 200


def test_market_schema():
    resp = client.get("/api/collectors/market")
    body = resp.json()
    assert "data" in body
    assert "collected_at" in body


def test_market_categorias():
    resp = client.get("/api/collectors/market")
    data = resp.json()["data"]
    assert "bolsas" in data
    assert "cambio" in data


def test_market_bolsas_campos():
    resp = client.get("/api/collectors/market")
    bolsas = resp.json()["data"]["bolsas"]
    for ativo in bolsas.values():
        assert "preco" in ativo
        assert "variacao_pct" in ativo
