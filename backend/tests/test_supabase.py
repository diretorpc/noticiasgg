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
