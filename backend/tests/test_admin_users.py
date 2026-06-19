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


def test_users_requires_auth():
    resp = client.get("/api/admin/users")
    assert resp.status_code == 401


def test_users_returns_users_with_prefs():
    authed = [{"phone": "5511", "name": "Ana"}, {"phone": "5522", "name": "Bia"}]
    prefs_5511 = {"sections": {"market": True}, "report_time": "08:00",
                  "audio_for_text": True, "audio_for_media": None,
                  "tts_voice": "onyx", "tts_speed": 0.9}
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.list_authorized", return_value=authed), \
         patch("backend.api.admin.supabase.get_preferences",
               side_effect=lambda p: prefs_5511 if p == "5511" else None):
        resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert users[0]["phone"] == "5511"
    assert users[0]["preferences"]["tts_voice"] == "onyx"
    assert users[1]["preferences"] is None
