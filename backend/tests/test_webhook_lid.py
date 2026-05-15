from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

_REMOTE_JID = "139247134720249@lid"
_USER_PHONE = "5534999301855"
_AUTHORIZED = {"lid": _REMOTE_JID, "phone": _USER_PHONE, "name": "Ricardim"}


def _payload(remote_jid=_REMOTE_JID, text="olá"):
    return {
        "data": {
            "key": {"fromMe": False, "remoteJid": remote_jid},
            "pushName": "Teste",
            "message": {"conversation": text},
        }
    }


def test_resposta_normal_usa_remote_jid():
    with patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    mock_send.assert_called_once_with(_REMOTE_JID, "resposta")


def test_confirmacao_preferencia_usa_remote_jid():
    intent = {
        "intent": "preference",
        "sections": None,
        "report_time": None,
        "reset": False,
        "reply": "Feito!",
    }
    with patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value=intent), \
         patch("backend.api.main.supabase.save_preferences"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload(text="quero só crypto"))
    assert resp.status_code == 200
    mock_send.assert_called_once_with(_REMOTE_JID, "Feito!")
