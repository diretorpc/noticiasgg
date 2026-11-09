import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import selflink, supabase, schedules

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit

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
    assert "sections" not in body  # campo morto (test_campo_morto.py)
    assert body["audio"] == {"audio_for_text": True, "audio_for_media": False,
                             "tts_voice": "nova", "tts_speed": 0.85}


@pytest.mark.unit
def test_put_me_grava_o_audio(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase, "save_preferences",
                        lambda phone, **kw: captured.update(phone=phone, **kw))
    r = client.put("/api/me?token=x", json={"audio_for_text": True, "audio_for_media": False,
                                            "tts_voice": "nova", "tts_speed": 0.85})
    assert r.status_code == 200
    assert captured == {"phone": PHONE, "audio_for_text": True, "audio_for_media": False,
                        "tts_voice": "nova", "tts_speed": 0.85}


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
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "use_new_report_engine": True})
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


@pytest.mark.unit
def test_put_me_schedule_grade_invalida_devolve_422_sem_tocar_no_banco(monkeypatch):
    chamadas = []
    monkeypatch.setattr(schedules, "replace_for_phone",
                        lambda phone, rows: chamadas.append(rows))
    r = client.put("/api/me/schedule?token=x", json={"schedule": {"bolsas": {"9": [7]}}})
    assert r.status_code == 422
    assert chamadas == []


@pytest.mark.unit
def test_put_me_schedule_payload_malformado_devolve_422(monkeypatch):
    monkeypatch.setattr(schedules, "replace_for_phone", lambda phone, rows: None)
    r = client.put("/api/me/schedule?token=x", json={"schedule": {"bolsas": {"0": 7}}})
    assert r.status_code == 422


# ── Envio desligado: a tela e o PUT dizem a verdade (decisão do dono, 09/11/2026) ──
# O cron só manda para quem tem `use_new_report_engine` ligada. A grade do /me salva
# mesmo com ela desligada, mas a tela não pode prometer envio. O /me nunca liga a chave.

@pytest.mark.unit
@pytest.mark.parametrize("flag,esperado", [(True, True), (False, False), (None, False)])
def test_get_me_devolve_envio_ligado(monkeypatch, flag, esperado):
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "name": "Ana", "use_new_report_engine": flag})
    monkeypatch.setattr(schedules, "get_for_phone", lambda phone: [])
    monkeypatch.setattr(supabase, "get_preferences", lambda phone: {})
    r = client.get("/api/me?token=x")
    assert r.status_code == 200
    assert r.json()["envio_ligado"] is esperado


@pytest.mark.unit
@pytest.mark.parametrize("flag,esperado", [(True, True), (False, False)])
def test_put_schedule_grava_e_devolve_a_chave_lida_na_hora(monkeypatch, flag, esperado):
    gravado = []
    monkeypatch.setattr(schedules, "grid_to_rows",
                        lambda phone, grid: [{"phone": phone, "section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(schedules, "replace_for_phone", lambda phone, rows: gravado.append(rows))
    monkeypatch.setattr(schedules, "set_engine_flag",
                        lambda *a, **k: pytest.fail("o /me não liga a chave"))
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "use_new_report_engine": flag})
    r = client.put("/api/me/schedule?token=x", json={"schedule": {"bolsas": {"0": [7]}}})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "envio_ligado": esperado}
    assert len(gravado) == 1  # com envio desligado a grade AINDA salva


@pytest.mark.unit
def test_put_schedule_leitura_da_chave_falha_e_nada_e_gravado(monkeypatch):
    # A chave é lida ANTES de gravar. Lida depois, uma falha nessa leitura devolvia
    # 500 com a grade já salva: a tela dizia "Erro" e a mudança tinha valido.
    gravado = []
    monkeypatch.setattr(schedules, "grid_to_rows",
                        lambda phone, grid: [{"phone": phone, "section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(schedules, "replace_for_phone", lambda phone, rows: gravado.append(rows))

    def _falha(phone):
        raise RuntimeError("supabase fora")

    monkeypatch.setattr(supabase, "get_authorized_by_phone", _falha)
    r = TestClient(app, raise_server_exceptions=False).put(
        "/api/me/schedule?token=x", json={"schedule": {"bolsas": {"0": [7]}}})
    assert r.status_code == 500
    assert gravado == []
