from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

USERS_08 = [
    {"phone": "5534999301855", "name": "Ricardim", "sections": None},
]


def test_cron_report_sem_usuarios_retorna_ok():
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=[]), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"):
        resp = client.get("/api/cron/report",
                          headers={"x-vercel-cron": "1"})
    assert resp.status_code == 200
    assert resp.json()["sent"] == 0


def test_cron_report_envia_para_usuarios_do_horario():
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=USERS_08), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"), \
         patch("backend.api.cron_report.supabase.get_news_feedback", return_value=[]), \
         patch("backend.api.cron_report.reporter.generate_report", return_value="relatório"), \
         patch("backend.api.cron_report.whatsapp.send_message") as mock_send:
        resp = client.get("/api/cron/report",
                          headers={"x-vercel-cron": "1"})
    assert resp.status_code == 200
    assert resp.json()["sent"] == 1
    mock_send.assert_called_once_with("5534999301855", "relatório")


def test_cron_report_sem_header_retorna_401():
    resp = client.get("/api/cron/report")
    assert resp.status_code == 401


def test_cron_report_passa_news_feedback_para_reporter():
    feedback = [{"important_topics": ["Fed"], "unimportant_topics": []}]
    with patch("backend.api.cron_report.supabase.get_users_for_hour", return_value=USERS_08), \
         patch("backend.api.cron_report._current_hour_brt", return_value="08:00"), \
         patch("backend.api.cron_report.supabase.get_news_feedback", return_value=feedback), \
         patch("backend.api.cron_report.reporter.generate_report", return_value="relatório") as mock_gen, \
         patch("backend.api.cron_report.whatsapp.send_message"):
        resp = client.get("/api/cron/report", headers={"x-vercel-cron": "1"})
    assert resp.status_code == 200
    call_kwargs = mock_gen.call_args[1]
    assert call_kwargs.get("news_feedback") == feedback
