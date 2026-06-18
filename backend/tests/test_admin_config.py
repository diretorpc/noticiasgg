import os
import time
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)
_SECRET = "test-jwt-secret"


def _token():
    return jwt.encode(
        {"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600},
        _SECRET, algorithm="HS256",
    )


def test_agent_config_requires_auth():
    resp = client.get("/api/admin/agent-config")
    assert resp.status_code == 401


def test_agent_config_returns_all_sections():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        resp = client.get("/api/admin/agent-config",
                          headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"]["model"] == "claude-sonnet-4-6"
    assert "reuters" in body["news"]["sources_finance"]
    assert body["audio"]["tts_voice"] == "nova"


def test_agent_config_exposes_no_secrets():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        resp = client.get("/api/admin/agent-config",
                          headers={"Authorization": f"Bearer {_token()}"})
    raw = resp.text.lower()
    assert "api_key" not in raw
    assert "sk-" not in raw
