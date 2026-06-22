import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import selflink, supabase, schedules

client = TestClient(app)

PHONE = "5534999945010"


@pytest.fixture(autouse=True)
def _bypass_token():
    app.dependency_overrides[selflink.selflink_phone] = lambda: PHONE
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_me_returns_scoped_bundle(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "name": "Matheus"})
    monkeypatch.setattr(schedules, "get_for_phone",
                        lambda phone: [{"section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(supabase, "get_preferences",
                        lambda phone: {"sections": {"market": True}, "report_time": "enabled",
                                       "audio_for_text": True, "audio_for_media": False,
                                       "tts_voice": "nova", "tts_speed": 0.85})
    r = client.get("/api/me?token=x")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Matheus"
    assert body["schedule"] == {"bolsas": {"0": [7]}}
    assert body["sections"] == {"market": True}
    assert body["audio"] == {"audio_for_text": True, "audio_for_media": False,
                             "tts_voice": "nova", "tts_speed": 0.85}


@pytest.mark.unit
def test_put_me_preserves_report_time(monkeypatch):
    monkeypatch.setattr(supabase, "get_preferences", lambda phone: {"report_time": "enabled"})
    captured = {}
    monkeypatch.setattr(supabase, "save_preferences",
                        lambda phone, **kw: captured.update(phone=phone, **kw))
    r = client.put("/api/me?token=x", json={"sections": {"market": True},
                                            "audio_for_text": True, "audio_for_media": False,
                                            "tts_voice": "nova", "tts_speed": 0.85})
    assert r.status_code == 200
    assert captured["phone"] == PHONE
    assert captured["report_time"] == "enabled"
    assert captured["sections"] == {"market": True}


@pytest.mark.unit
def test_put_me_schedule_replaces_without_touching_engine_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(schedules, "grid_to_rows",
                        lambda phone, grid: [{"phone": phone, "section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(schedules, "replace_for_phone",
                        lambda phone, rows: captured.update(rows=rows, phone=phone))

    def _boom(*a, **k):
        raise AssertionError("set_engine_flag não deve ser chamado pelo /me")

    monkeypatch.setattr(schedules, "set_engine_flag", _boom)
    r = client.put("/api/me/schedule?token=x", json={"schedule": {"bolsas": {"0": [7]}}})
    assert r.status_code == 200
    assert captured["phone"] == PHONE
    assert captured["rows"][0]["section"] == "bolsas"


@pytest.mark.unit
def test_me_requires_valid_token():
    # sem o override de dependência, token inválido → 401
    app.dependency_overrides.clear()
    r = client.get("/api/me")
    assert r.status_code == 401
