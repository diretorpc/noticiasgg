import pytest
from fastapi import HTTPException

from backend.services import selflink, supabase


@pytest.mark.unit
def test_resolve_phone_valid_token(monkeypatch):
    monkeypatch.setattr(supabase, "get_by_selflink_token",
                        lambda tok: {"phone": "5534999945010", "name": "Matheus"})
    assert selflink.resolve_phone("abc123") == "5534999945010"


@pytest.mark.unit
def test_resolve_phone_none_or_empty_raises():
    for bad in (None, "", "   "):
        with pytest.raises(HTTPException) as ei:
            selflink.resolve_phone(bad)
        assert ei.value.status_code == 401


@pytest.mark.unit
def test_resolve_phone_unknown_token_raises(monkeypatch):
    monkeypatch.setattr(supabase, "get_by_selflink_token", lambda tok: None)
    with pytest.raises(HTTPException) as ei:
        selflink.resolve_phone("nope")
    assert ei.value.status_code == 401


@pytest.mark.unit
def test_get_by_selflink_token_empty_short_circuits():
    # token vazio não deve consultar o banco (evita casar com nulls); retorna None
    assert supabase.get_by_selflink_token("") is None
    assert supabase.get_by_selflink_token(None) is None
