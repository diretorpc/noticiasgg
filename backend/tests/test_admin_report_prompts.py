import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth, supabase, config, report_prompts, report_engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.verify_supabase_jwt] = lambda: {"sub": "admin"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_report_prompts(monkeypatch):
    monkeypatch.setattr(report_prompts, "describe_prompts",
                        lambda: [{"section": "bolsas", "value": "V", "is_custom": True, "default": "D"}])
    r = client.get("/api/admin/report-prompts")
    assert r.status_code == 200
    assert r.json() == {"prompts": [{"section": "bolsas", "value": "V", "is_custom": True, "default": "D"}]}


@pytest.mark.unit
def test_put_report_prompt_upserts_and_clears_cache(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase, "upsert_config", lambda k, v: captured.update(key=k, val=v))
    monkeypatch.setattr(config, "clear_cache", lambda: captured.update(cleared=True))
    r = client.put("/api/admin/report-prompts/bolsas", json={"prompt": "NOVO PROMPT"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "is_custom": True}
    assert captured == {"key": "report_prompt_bolsas", "val": "NOVO PROMPT", "cleared": True}


@pytest.mark.unit
def test_put_report_prompt_rejects_unknown_section():
    r = client.put("/api/admin/report-prompts/inexistente", json={"prompt": "x"})
    assert r.status_code == 400


@pytest.mark.unit
def test_delete_report_prompt_resets(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase, "delete_config", lambda k: captured.update(key=k))
    monkeypatch.setattr(config, "clear_cache", lambda: captured.update(cleared=True))
    r = client.delete("/api/admin/report-prompts/analise")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "is_custom": False}
    assert captured == {"key": "report_prompt_analise", "cleared": True}


@pytest.mark.unit
def test_preview_section_returns_text(monkeypatch):
    monkeypatch.setattr(report_engine, "preview_section", lambda section, prompt, **k: f"OUT:{section}:{prompt}")
    r = client.post("/api/admin/preview-section", json={"section": "noticias", "prompt": "P"})
    assert r.status_code == 200
    assert r.json() == {"text": "OUT:noticias:P"}


@pytest.mark.unit
def test_preview_section_rejects_unknown_section():
    r = client.post("/api/admin/preview-section", json={"section": "nope", "prompt": "P"})
    assert r.status_code == 400
