import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth, report_engine, supabase

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.verify_supabase_jwt] = lambda: {"sub": "admin"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_preview_report_returns_messages(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "name": "Gustavo"})
    monkeypatch.setattr(report_engine, "generate_sections",
                        lambda sections, user, **k: ["MSG1", "MSG2"])
    r = client.post("/api/admin/preview-report",
                    json={"phone": "5534999999999", "sections": {"bolsas": True}})
    assert r.status_code == 200
    assert r.json() == {"messages": ["MSG1", "MSG2"]}


@pytest.mark.unit
def test_preview_report_unknown_user_uses_empty_name(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone", lambda phone: None)
    captured = {}

    def gen(sections, user, **k):
        captured["user"] = user
        return []

    monkeypatch.setattr(report_engine, "generate_sections", gen)
    r = client.post("/api/admin/preview-report", json={"phone": "999", "sections": None})
    assert r.status_code == 200
    assert captured["user"]["name"] == ""
