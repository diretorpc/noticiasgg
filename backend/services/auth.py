import os

import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException

# Supabase migrou pra chaves assimétricas (ES256/RS256). Validamos via JWKS
# (chaves públicas), sem segredo compartilhado no backend.
_ALGORITHMS = ["ES256", "RS256"]
_jwks_client: PyJWKClient | None = None


def _jwks_url() -> str:
    return f"{os.environ['SUPABASE_URL']}/auth/v1/.well-known/jwks.json"


def _get_jwks_client() -> PyJWKClient:
    """Singleton do PyJWKClient — cacheia as chaves públicas entre requests
    (evita refetch a cada chamada no serverless)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_jwks_url(), cache_keys=True)
    return _jwks_client


def decode_token(token: str) -> dict:
    """Valida um JWT Supabase (assimétrico, ES256/RS256) via JWKS e retorna
    o payload. Lança jwt.PyJWTError se inválido/expirado."""
    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token, signing_key.key, algorithms=_ALGORITHMS, audience="authenticated"
    )


def verify_supabase_jwt(authorization: str | None = Header(default=None)) -> dict:
    """Dependência FastAPI: exige `Authorization: Bearer <jwt>` válido."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return decode_token(authorization.split(" ", 1)[1])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")
