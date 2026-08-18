from unittest.mock import MagicMock, patch

import pytest

from backend.services import supabase


def _fake_client(response):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)
    client.get = MagicMock(return_value=response)
    return client


@pytest.mark.unit
def test_log_sent_news_envia_campos_ricos():
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({
            "news_id": "abc123",
            "titulo_pt": "USDA mostra queda na qualidade do milho",
            "titulo_original": "Corn Rated 61% Good to Excellent",
            "fonte": "Reuters",
            "url": "https://example.com/usda",
            "categoria": "OFERTA/CLIMA",
            "resumo": "Condição boa/excelente do milho cai.",
            "direcao": "alta",
            "score": 7,
            "ativos": ["milho", "soja"],
            "publicado_em": "2026-08-18T10:00:00+00:00",
        })
    path = client.post.call_args[0][0]
    enviado = client.post.call_args[1]["json"]
    assert path == "/news_log"
    assert enviado["news_id"] == "abc123"
    assert enviado["url"] == "https://example.com/usda"
    assert enviado["ativos"] == ["milho", "soja"]
    assert enviado["score"] == 7
    assert "sent_at" in enviado


@pytest.mark.unit
def test_log_sent_news_ignora_campo_desconhecido():
    """Chave fora do contrato não pode virar coluna inexistente no POST —
    o PostgREST devolve 400 e o registro se perde em silêncio."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123", "coluna_que_nao_existe": "x"})
    enviado = client.post.call_args[1]["json"]
    assert "coluna_que_nao_existe" not in enviado
    assert enviado["news_id"] == "abc123"


@pytest.mark.unit
def test_log_sent_news_nunca_estoura_para_o_chamador():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123"})  # não deve levantar


@pytest.mark.unit
def test_get_news_log_filtra_por_janela_e_ordena():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[{"news_id": "abc123", "titulo_pt": "t"}])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        linhas = supabase.get_news_log(hours=48, limit=5)
    url = client.get.call_args[0][0]
    assert url.startswith("/news_log?")
    assert "order=sent_at.desc" in url
    assert "limit=5" in url
    assert "sent_at=gte." in url
    assert linhas == [{"news_id": "abc123", "titulo_pt": "t"}]


@pytest.mark.unit
def test_get_news_log_devolve_lista_vazia_em_falha():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=RuntimeError("timeout"))
    with patch.object(supabase, "_client", return_value=client):
        assert supabase.get_news_log() == []
