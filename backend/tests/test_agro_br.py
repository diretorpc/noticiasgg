import pytest
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)


def test_agro_br_cbot_status_200():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    assert resp.status_code == 200


def test_agro_br_cbot_schema():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    body = resp.json()
    assert "data" in body
    assert "collected_at" in body
    assert "commodities_cbot" in body["data"]


def test_agro_br_cbot_campos():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    data = resp.json()["data"]["commodities_cbot"]
    assert len(data) > 0
    for ativo in data.values():
        assert "preco" in ativo
        assert "moeda" in ativo
        assert "unidade" in ativo
