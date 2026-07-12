import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from backend.services import auth

_PRIV = ec.generate_private_key(ec.SECP256R1())
_PUB = _PRIV.public_key()
_OTHER_PRIV = ec.generate_private_key(ec.SECP256R1())


def _token(key=_PRIV, aud="authenticated", exp_offset=3600):
    return jwt.encode(
        {"sub": "u1", "aud": aud, "exp": int(time.time()) + exp_offset},
        key, algorithm="ES256",
    )


class _FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=_PUB)


def test_decode_valid_token():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()):
        payload = auth.decode_token(_token())
    assert payload["sub"] == "u1"


def test_verify_missing_header_raises_401():
    with pytest.raises(HTTPException) as exc:
        auth.verify_supabase_jwt(authorization=None)
    assert exc.value.status_code == 401


def test_verify_invalid_signature_raises_401():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()):
        with pytest.raises(HTTPException) as exc:
            auth.verify_supabase_jwt(authorization=f"Bearer {_token(key=_OTHER_PRIV)}")
    assert exc.value.status_code == 401


def test_verify_valid_bearer_returns_payload():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()):
        payload = auth.verify_supabase_jwt(authorization=f"Bearer {_token()}")
    assert payload["sub"] == "u1"


def test_require_admin_allows_listed_email():
    with patch.dict(os.environ, {"ADMIN_EMAILS": "matheusmouro@hotmail.com, outro@x.com"}):
        payload = auth.require_admin({"sub": "u1", "email": "Matheusmouro@Hotmail.com"})
    assert payload["email"] == "Matheusmouro@Hotmail.com"


def test_require_admin_denies_unlisted_email():
    with patch.dict(os.environ, {"ADMIN_EMAILS": "matheusmouro@hotmail.com"}):
        with pytest.raises(HTTPException) as exc:
            auth.require_admin({"sub": "u2", "email": "attacker@evil.com"})
    assert exc.value.status_code == 403


def test_require_admin_denies_when_allowlist_unset():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ADMIN_EMAILS", None)
        with pytest.raises(HTTPException) as exc:
            auth.require_admin({"sub": "u1", "email": "matheusmouro@hotmail.com"})
    assert exc.value.status_code == 403


def test_require_admin_denies_payload_without_email():
    with patch.dict(os.environ, {"ADMIN_EMAILS": "matheusmouro@hotmail.com"}):
        with pytest.raises(HTTPException) as exc:
            auth.require_admin({"sub": "u1"})
    assert exc.value.status_code == 403
