import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)
_SECRET = "test-cron-secret"


def _due(rows, enabled):
    return (
        patch("backend.api.cron_report.schedules.due_now", return_value=rows),
        patch("backend.api.cron_report.schedules.phones_with_engine_enabled", return_value=set(enabled)),
    )


@pytest.mark.unit
def test_cron_report_sem_agendamento_retorna_zero():
    p1, p2 = _due([], [])
    with p1, p2, patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    assert r.status_code == 200
    assert r.json()["sent"] == 0


@pytest.mark.unit
def test_cron_report_envia_secoes_agrupadas_por_usuario():
    rows = [
        {"phone": "5534999945010", "section": "commodities"},
        {"phone": "5534999945010", "section": "bolsas"},
    ]
    p1, p2 = _due(rows, ["5534999945010"])
    with p1, p2, \
         patch("backend.api.cron_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "Matheus"}), \
         patch("backend.api.cron_report.report_engine.generate_sections",
               return_value=["MSG-A", "MSG-B"]) as gen, \
         patch("backend.api.cron_report.whatsapp.send_message") as send, \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    assert r.status_code == 200
    body = r.json()
    assert body["users"] == 1 and body["sent"] == 1
    called_sections = gen.call_args.args[0]
    assert called_sections == {"commodities": True, "bolsas": True}
    assert send.call_count == 2


@pytest.mark.unit
def test_cron_report_filtra_quem_nao_tem_flag():
    rows = [{"phone": "999", "section": "bolsas"}]
    p1, p2 = _due(rows, [])  # ninguém habilitado
    with p1, p2, \
         patch("backend.api.cron_report.report_engine.generate_sections") as gen, \
         patch("backend.api.cron_report.whatsapp.send_message") as send, \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    assert r.json()["users"] == 0
    gen.assert_not_called()
    send.assert_not_called()


@pytest.mark.unit
def test_cron_report_isola_falha_de_usuario():
    rows = [{"phone": "A", "section": "bolsas"}, {"phone": "B", "section": "bolsas"}]
    p1, p2 = _due(rows, ["A", "B"])

    def gen(sections, user, **k):
        if user["phone"] == "A":
            raise RuntimeError("claude down")
        return ["ok"]

    with p1, p2, \
         patch("backend.api.cron_report.supabase.get_authorized_by_phone",
               side_effect=lambda p: {"phone": p, "name": ""}), \
         patch("backend.api.cron_report.report_engine.generate_sections", side_effect=gen), \
         patch("backend.api.cron_report.whatsapp.send_message"), \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    body = r.json()
    assert body["sent"] == 1 and body["failed"] == 1


@pytest.mark.unit
def test_cron_report_sem_segredo_401():
    with patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report")
    assert r.status_code == 401
