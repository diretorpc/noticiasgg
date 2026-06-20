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


def test_save_user_prefs_requires_auth():
    resp = client.post("/api/admin/user-prefs", json={"phone": "5511"})
    assert resp.status_code == 401


def test_save_user_prefs_calls_supabase():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.save_preferences") as mock_save:
        resp = client.post(
            "/api/admin/user-prefs",
            json={"phone": "5511", "tts_voice": "onyx", "tts_speed": 0.9,
                  "audio_for_text": True},
            headers={"Authorization": f"Bearer {_token()}"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_save.assert_called_once()
    kwargs = mock_save.call_args.kwargs
    assert kwargs["tts_voice"] == "onyx"
    assert kwargs["audio_for_text"] is True


def test_reset_user_prefs_calls_delete():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.delete_preferences") as mock_del:
        resp = client.delete("/api/admin/user-prefs/5511",
                             headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    mock_del.assert_called_once_with("5511")
