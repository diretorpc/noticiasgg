import json
from unittest.mock import MagicMock, patch

import pytest

from backend.services import alert_checker, supabase


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


@pytest.mark.unit
def test_format_news_alert_inclui_link():
    result = {"categoria": "OFERTA/CLIMA", "ativos": ["milho"], "direcao": "alta"}
    msg = alert_checker._format_news_alert(
        result, "Reuters", "Milho perde qualidade nos EUA", 7, False,
        url="https://example.com/usda",
    )
    assert "https://example.com/usda" in msg
    assert "Milho perde qualidade nos EUA" in msg


@pytest.mark.unit
def test_format_news_alert_sem_url_nao_quebra():
    msg = alert_checker._format_news_alert({}, "Reuters", "Título", 7, False, url="")
    assert "Título" in msg
    assert "http" not in msg


def _prepara_check_news(monkeypatch, artigo, classificacao):
    """Isola _check_news de rede, banco e IA. Devolve o dict onde o log cai
    e a lista de mensagens que teriam ido ao WhatsApp."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    gravado: dict = {}
    enviadas: list[str] = []

    monkeypatch.setattr(alert_checker.supabase, "log_sent_news", gravado.update)
    monkeypatch.setattr(alert_checker.supabase, "mark_news_sent", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "set_alert_triggered", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "is_news_sent", lambda *a, **k: False)
    monkeypatch.setattr(alert_checker.supabase, "get_recent_sent_titles", lambda *a, **k: [])
    monkeypatch.setattr(alert_checker, "_cooldown_ok", lambda *a, **k: True)
    monkeypatch.setattr(
        alert_checker, "_broadcast",
        lambda msg, recipients, errors=None: (enviadas.append(msg), 1)[1],
    )
    monkeypatch.setattr("backend.collectors.news.collect", lambda *a, **k: [artigo])

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=json.dumps(classificacao))]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_msg)
    monkeypatch.setattr(alert_checker, "Anthropic", lambda *a, **k: fake_client)
    return gravado, enviadas


_ARTIGO = {
    "titulo": "Corn Rated 61% Good to Excellent",
    "fonte": "Reuters",
    "url": "https://example.com/usda",
    "publicado_em": "2026-08-18T10:00:00+00:00",
}

_CLASSIFICACAO = {
    "score": 7,
    "categoria": "OFERTA/CLIMA",
    "titulo_pt": "Milho dos EUA perde qualidade",
    "resumo": "Condição boa/excelente cai para 61%.",
    "ativos": ["milho"],
    "direcao": "alta",
    "duplicada": False,
}


@pytest.mark.unit
def test_check_news_grava_no_log_apos_entregar(monkeypatch):
    gravado, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert gravado["url"] == "https://example.com/usda"
    assert gravado["titulo_pt"] == "Milho dos EUA perde qualidade"
    assert gravado["titulo_original"] == "Corn Rated 61% Good to Excellent"
    assert gravado["fonte"] == "Reuters"
    assert gravado["publicado_em"] == "2026-08-18T10:00:00+00:00"
    assert gravado["categoria"] == "OFERTA/CLIMA"
    assert gravado["resumo"] == "Condição boa/excelente cai para 61%."
    assert gravado["score"] == 7


@pytest.mark.unit
def test_check_news_manda_o_link_na_mensagem(monkeypatch):
    _, enviadas = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert len(enviadas) == 1
    assert "https://example.com/usda" in enviadas[0]


@pytest.mark.unit
def test_check_news_em_test_mode_nao_grava_no_log(monkeypatch):
    """test_mode existe para conferência visual sem sujar o estado — o log
    não pode virar a exceção que suja."""
    gravado, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news(
        [{"phone": "5534999945010", "name": "Matheus"}], test_mode=True
    )

    assert gravado == {}
