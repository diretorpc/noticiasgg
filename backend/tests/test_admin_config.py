import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth

client = TestClient(app)

_PRIV = ec.generate_private_key(ec.SECP256R1())
_PUB = _PRIV.public_key()


def _token():
    return jwt.encode(
        {"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600},
        _PRIV, algorithm="ES256",
    )


class _FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=_PUB)


def test_agent_config_requires_auth():
    resp = client.get("/api/admin/agent-config")
    assert resp.status_code == 401


def test_agent_config_returns_all_sections():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()):
        resp = client.get("/api/admin/agent-config",
                          headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"]["model"] == "claude-sonnet-4-6"
    assert "reuters" in body["news"]["sources_finance"]
    assert body["audio"]["tts_voice"] == "nova"


def test_agent_config_exposes_no_secrets():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()):
        resp = client.get("/api/admin/agent-config",
                          headers={"Authorization": f"Bearer {_token()}"})
    raw = resp.text.lower()
    assert "api_key" not in raw
    assert "sk-" not in raw
