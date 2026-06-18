import os

import jwt
from fastapi import Header, HTTPException


def decode_token(token: str) -> dict:
    """Valida um JWT Supabase (HS256) e retorna o payload.
    Lança jwt.PyJWTError se inválido/expirado."""
    secret = os.environ["SUPABASE_JWT_SECRET"]
    return jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")


def verify_supabase_jwt(authorization: str | None = Header(default=None)) -> dict:
    """Dependência FastAPI: exige `Authorization: Bearer <jwt>` válido."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return decode_token(authorization.split(" ", 1)[1])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")
