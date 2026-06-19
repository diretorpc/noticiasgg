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


def test_validate_rss_requires_auth():
    resp = client.post("/api/admin/validate-rss", json={"url": "https://x.com/rss"})
    assert resp.status_code == 401


def test_validate_rss_returns_check():
    result = {"valid": True, "item_count": 3, "sample_title": "Top", "error": None}
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.news.validate_feed", return_value=result):
        resp = client.post("/api/admin/validate-rss",
                           json={"url": "https://x.com/rss"},
                           headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    assert resp.json() == result
