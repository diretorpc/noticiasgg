import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.services import auth, schedules

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.verify_supabase_jwt] = lambda: {"sub": "admin"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_schedules_builds_grid(monkeypatch):
    monkeypatch.setattr(schedules, "get_for_phone",
                        lambda phone: [{"section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(schedules, "phones_with_engine_enabled", lambda: {"555"})
    r = client.get("/api/admin/schedules/555")
    assert r.status_code == 200
    assert r.json() == {"use_new_engine": True, "schedule": {"bolsas": {"0": [7]}}}


@pytest.mark.unit
def test_put_schedules_replaces_and_sets_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(schedules, "grid_to_rows",
                        lambda phone, grid: [{"phone": phone, "section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(schedules, "replace_for_phone",
                        lambda phone, rows: captured.update(rows=rows, phone=phone))
    monkeypatch.setattr(schedules, "set_engine_flag",
                        lambda phone, enabled: captured.update(flag=enabled))
    r = client.put("/api/admin/schedules/555",
                   json={"use_new_engine": True, "schedule": {"bolsas": {"0": [7]}}})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["phone"] == "555"
    assert captured["flag"] is True
    assert captured["rows"][0]["section"] == "bolsas"
