import pytest
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)


def test_crypto_status_200():
    resp = client.get("/api/collectors/crypto")
    assert resp.status_code == 200


def test_crypto_schema():
    body = client.get("/api/collectors/crypto").json()
    assert "data" in body
    assert "collected_at" in body


def test_crypto_retorna_lista():
    data = client.get("/api/collectors/crypto").json()["data"]
    assert isinstance(data, list)
    assert len(data) > 0


def test_crypto_campos_obrigatorios():
    moedas = client.get("/api/collectors/crypto").json()["data"]
    for moeda in moedas:
        assert "nome" in moeda
        assert "simbolo" in moeda
        # Stablecoins (ex: USDT) não têm preco_usd, só volume
        if moeda["simbolo"] != "USDT":
            assert "preco_usd" in moeda
            assert "variacao_24h_pct" in moeda
