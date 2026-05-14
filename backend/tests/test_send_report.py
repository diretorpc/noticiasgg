from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

PAYLOAD_DEFAULT = {
    "number": "5534999945010",
    "textMessage": {"text": "Relatório do n8n aqui."}
}


def test_send_report_sem_preferencias_envia_texto_n8n():
    with patch("backend.api.send_report.supabase.get_preferences", return_value=None), \
         patch("backend.api.send_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "Matheus"}), \
         patch("backend.api.send_report.whatsapp.send_message") as mock_send:
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_send.assert_called_once()
    args = mock_send.call_args[0]
    assert "Matheus" in args[1]


def test_send_report_com_horario_customizado_pula():
    with patch("backend.api.send_report.supabase.get_preferences",
               return_value={"phone": "5534999945010", "sections": None, "report_time": "08:00"}):
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


def test_send_report_com_sections_gera_novo_relatorio():
    sections = {"market": True, "crypto": False, "indicators_us": False, "indicators_br": False,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
    with patch("backend.api.send_report.supabase.get_preferences",
               return_value={"phone": "5534999945010", "sections": sections, "report_time": None}), \
         patch("backend.api.send_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "Matheus"}), \
         patch("backend.api.send_report.reporter.generate_report",
               return_value="relatório filtrado") as mock_gen, \
         patch("backend.api.send_report.whatsapp.send_message") as mock_send:
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.status_code == 200
    mock_gen.assert_called_once_with(
        "Gere o relatório diário.",
        sections=sections,
        user_name="Matheus",
    )
    mock_send.assert_called_once_with("5534999945010", "relatório filtrado")


def test_send_report_usuario_nao_encontrado_envia_sem_nome():
    with patch("backend.api.send_report.supabase.get_preferences", return_value=None), \
         patch("backend.api.send_report.supabase.get_authorized_by_phone", return_value=None), \
         patch("backend.api.send_report.whatsapp.send_message") as mock_send:
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_send.assert_called_once_with("5534999945010", "Relatório do n8n aqui.")


def test_send_report_supabase_error_retorna_erro():
    with patch("backend.api.send_report.supabase.get_preferences",
               side_effect=Exception("timeout")):
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.json()["status"] == "error"


def test_send_report_reporter_error_usa_fallback():
    sections = {"market": True, "crypto": False, "indicators_us": False, "indicators_br": False,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
    with patch("backend.api.send_report.supabase.get_preferences",
               return_value={"phone": "5534999945010", "sections": sections, "report_time": None}), \
         patch("backend.api.send_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "Matheus"}), \
         patch("backend.api.send_report.reporter.generate_report",
               side_effect=Exception("Claude timeout")), \
         patch("backend.api.send_report.whatsapp.send_message") as mock_send:
        resp = client.post("/api/send-report", json=PAYLOAD_DEFAULT)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_send.assert_called_once_with("5534999945010", "Relatório do n8n aqui.")


def test_send_report_payload_invalido_retorna_422():
    resp = client.post("/api/send-report", json={"number": "5534999945010"})
    assert resp.status_code == 422
