import os
from unittest.mock import patch

import httpx
import pytest

from backend.services import supabase

_ENV = {"SUPABASE_URL": "https://fake.supabase.co", "SUPABASE_KEY": "fake-key"}


def test_client_retenta_apos_timeout_transitorio():
    calls = {"n": 0}

    def fake_handle(self, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("The read operation timed out")
        return httpx.Response(200, json=[])

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        with supabase._client() as c:
            r = c.get("/system_alert_state?rule_id=eq.x&select=last_triggered_at")
    assert r.status_code == 200
    assert calls["n"] == 2


def test_client_retenta_apos_erro_de_conexao():
    calls = {"n": 0}

    def fake_handle(self, request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json=[])

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        with supabase._client() as c:
            r = c.get("/authorized_users?select=phone")
    assert r.status_code == 200
    assert calls["n"] == 2


def test_client_desiste_apos_segunda_falha():
    calls = {"n": 0}

    def fake_handle(self, request):
        calls["n"] += 1
        raise httpx.ReadTimeout("The read operation timed out")

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        with supabase._client() as c:
            with pytest.raises(httpx.ReadTimeout):
                c.get("/authorized_users?select=phone")
    assert calls["n"] == 2


def _capture_transport(response_json):
    """Transport fake que grava a request e devolve uma resposta fixa."""
    captured = {}

    def fake_handle(self, request):
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode() if request.content else ""
        return httpx.Response(200, json=response_json)

    return captured, fake_handle


def test_mark_news_sent_persiste_titulo():
    captured, fake_handle = _capture_transport([])
    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        supabase.mark_news_sent("abc123", title="OPEC+ corta produção")
    assert '"title": "OPEC+ corta produção"' in captured["body"] or \
           '"title":"OPEC+ corta produção"' in captured["body"]


def test_mark_news_sent_sem_titulo_nao_envia_campo():
    captured, fake_handle = _capture_transport([])
    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        supabase.mark_news_sent("abc123")
    assert "title" not in captured["body"]


def test_get_recent_sent_titles_retorna_lista():
    rows = [{"title": "OPEC+ corta produção"}, {"title": "Fed mantém juros"}]
    captured, fake_handle = _capture_transport(rows)
    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        titles = supabase.get_recent_sent_titles()
    assert titles == ["OPEC+ corta produção", "Fed mantém juros"]
    assert "title=not.is.null" in captured["url"]
    assert "sent_at=gte." in captured["url"]


def test_get_recent_sent_titles_encoda_cutoff_timestamp():
    """O cutoff ISO termina em '+00:00'. Sem percent-encoding o PostgREST lê o
    '+' como espaço (timestamp inválido) e devolve 400 — dedup degrada sempre.
    A URL precisa encodar o '+' (→ %2B)."""
    captured, fake_handle = _capture_transport([])
    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        supabase.get_recent_sent_titles()
    assert "+00:00" not in captured["url"]
    assert "%2B" in captured["url"]


def test_delete_old_history_encoda_cutoff_timestamp():
    """Mesma raiz: o cutoff vem do created_at do banco (contém '+00:00'). Sem
    encoding o DELETE vira 400/no-op e o histórico nunca é podado."""
    rows = [{"created_at": "2026-06-24T13:03:56.726574+00:00"}]
    captured, fake_handle = _capture_transport(rows)
    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        supabase.delete_old_history("553496592975")
    assert "+00:00" not in captured["url"]
    assert "%2B" in captured["url"]


def test_client_nao_retenta_erro_http():
    """4xx/5xx não é falha de transporte — raise_for_status cuida disso nos call sites."""
    calls = {"n": 0}

    def fake_handle(self, request):
        calls["n"] += 1
        return httpx.Response(500, json={"message": "internal"})

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        with supabase._client() as c:
            r = c.get("/authorized_users?select=phone")
    assert r.status_code == 500
    assert calls["n"] == 1


def test_count_recent_broadcasts_le_content_range():
    captured = {}

    def fake_handle(self, request):
        captured["url"] = str(request.url)
        captured["prefer"] = request.headers.get("prefer", "")
        return httpx.Response(200, json=[], headers={"content-range": "0-8/9"})

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        n = supabase.count_recent_broadcasts()
    assert n == 9
    assert "count=exact" in captured["prefer"]
    assert "title=not.is.null" in captured["url"]
    assert "+00:00" not in captured["url"]  # cutoff encodado (lição do bug fa2b5d0)


def test_count_recent_broadcasts_zero_quando_sem_header():
    def fake_handle(self, request):
        return httpx.Response(200, json=[])

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        n = supabase.count_recent_broadcasts()
    assert n == 0
