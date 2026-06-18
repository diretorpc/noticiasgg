import os
import time
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException

from backend.services import auth

_SECRET = "test-jwt-secret"


def _token(secret=_SECRET, aud="authenticated", exp_offset=3600):
    return jwt.encode(
        {"sub": "u1", "aud": aud, "exp": int(time.time()) + exp_offset},
        secret, algorithm="HS256",
    )


def test_decode_valid_token():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        payload = auth.decode_token(_token())
    assert payload["sub"] == "u1"


def test_verify_missing_header_raises_401():
    with pytest.raises(HTTPException) as exc:
        auth.verify_supabase_jwt(authorization=None)
    assert exc.value.status_code == 401


def test_verify_invalid_token_raises_401():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        with pytest.raises(HTTPException) as exc:
            auth.verify_supabase_jwt(authorization="Bearer garbage")
    assert exc.value.status_code == 401


def test_verify_valid_bearer_returns_payload():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        payload = auth.verify_supabase_jwt(authorization=f"Bearer {_token()}")
    assert payload["sub"] == "u1"
