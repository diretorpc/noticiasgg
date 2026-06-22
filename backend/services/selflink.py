from fastapi import HTTPException, Query

from backend.services import supabase


def resolve_phone(token: str | None) -> str:
    if not token or not str(token).strip():
        raise HTTPException(status_code=401, detail="missing token")
    user = supabase.get_by_selflink_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="invalid or revoked token")
    return user["phone"]


def selflink_phone(token: str | None = Query(default=None)) -> str:
    return resolve_phone(token)
