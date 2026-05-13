import pytest
import os
from fastapi.testclient import TestClient
from unittest.mock import patch
from backend.api.main import app

client = TestClient(app)


def test_news_sem_chave_retorna_500():
    with patch.dict(os.environ, {"NEWS_API_KEY": ""}):
        resp = client.get("/api/collectors/news")
        assert resp.status_code == 500


def test_news_schema_com_chave():
    if not os.getenv("NEWS_API_KEY"):
        pytest.skip("NEWS_API_KEY não configurada")
    resp = client.get("/api/collectors/news")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "collected_at" in body


def test_news_retorna_lista_com_chave():
    if not os.getenv("NEWS_API_KEY"):
        pytest.skip("NEWS_API_KEY não configurada")
    data = client.get("/api/collectors/news").json()["data"]
    assert isinstance(data, list)


def test_news_campos_obrigatorios_com_chave():
    if not os.getenv("NEWS_API_KEY"):
        pytest.skip("NEWS_API_KEY não configurada")
    artigos = client.get("/api/collectors/news").json()["data"]
    for a in artigos:
        assert "titulo" in a
        assert "fonte" in a
        assert "url" in a
