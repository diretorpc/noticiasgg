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


_NEWSAPI_PAYLOAD = {
    "status": "ok",
    "sources": [
        {"id": "reuters", "name": "Reuters", "category": "general",
         "language": "en", "country": "us", "description": "x", "url": "x"},
    ],
}


def test_newsapi_sources_requires_auth():
    resp = client.get("/api/admin/newsapi-sources")
    assert resp.status_code == 401


def test_newsapi_sources_returns_simplified_list():
    fake = SimpleNamespace(
        status_code=200,
        json=lambda: _NEWSAPI_PAYLOAD,
        raise_for_status=lambda: None,
    )
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.httpx.get", return_value=fake):
        resp = client.get("/api/admin/newsapi-sources",
                          headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert sources == [{"id": "reuters", "name": "Reuters", "category": "general",
                        "language": "en", "country": "us"}]
