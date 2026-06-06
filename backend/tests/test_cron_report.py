import os
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

_SECRET = "test-cron-secret"
USERS_08 = [
    {"phone": "5534999301855", "name": "Ricardim", "sections": None},
]


def test_cron_report_sem_usuarios_retorna_ok():
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=[]), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"), \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        resp = client.get("/api/cron/report",
                          headers={"x-cron-secret": _SECRET})
    assert resp.status_code == 200
    assert resp.json()["sent"] == 0


def test_cron_report_envia_para_usuarios_do_horario():
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=USERS_08), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"), \
         patch("backend.api.cron_report.reporter.generate_report", return_value="relatório"), \
         patch("backend.api.cron_report.whatsapp.send_message") as mock_send, \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        resp = client.get("/api/cron/report",
                          headers={"x-cron-secret": _SECRET})
    assert resp.status_code == 200
    assert resp.json()["sent"] == 1
    mock_send.assert_called_once_with("5534999301855", "relatório")


def test_cron_report_sem_header_retorna_401():
    with patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        resp = client.get("/api/cron/report")
    assert resp.status_code == 401
