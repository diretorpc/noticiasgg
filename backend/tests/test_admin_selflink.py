import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth, supabase

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.require_admin] = lambda: {"sub": "admin"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_generate_selflink(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "name": "G.Mouro"})
    monkeypatch.setattr(supabase, "set_selflink_token", lambda phone: "TOK123")
    monkeypatch.setenv("PANEL_BASE_URL", "https://painel.example.com")
    r = client.post("/api/admin/selflink/5516991016898")
    assert r.status_code == 200
    assert r.json() == {"url": "https://painel.example.com/me?token=TOK123", "token": "TOK123"}


@pytest.mark.unit
def test_generate_selflink_unknown_phone(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone", lambda phone: None)
    r = client.post("/api/admin/selflink/000")
    assert r.status_code == 404


@pytest.mark.unit
def test_revoke_selflink(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase, "clear_selflink_token", lambda phone: captured.update(phone=phone))
    r = client.delete("/api/admin/selflink/5516991016898")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["phone"] == "5516991016898"
