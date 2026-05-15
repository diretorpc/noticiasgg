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


def test_resposta_normal_usa_phone():
    with patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    mock_send.assert_called_once_with(_USER_PHONE, "resposta")


def test_confirmacao_preferencia_usa_phone():
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
    mock_send.assert_called_once_with(_USER_PHONE, "Feito!")


def test_usuario_nao_autorizado_recebe_confirmacao():
    with patch("backend.api.main.supabase.get_authorized", return_value=None), \
         patch("backend.api.main.supabase.upsert_pending"), \
         patch("backend.api.main._admin_phone", return_value="5534999945010"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    assert resp.json()["reason"] == "pending auth"
    calls = [c.args[0] for c in mock_send.call_args_list]
    assert _REMOTE_JID in calls


def test_usuario_nao_autorizado_confirmacao_falha_silenciosa():
    def raise_on_user_jid(number, text):
        if number == _REMOTE_JID:
            raise Exception("connection error")

    with patch("backend.api.main.supabase.get_authorized", return_value=None), \
         patch("backend.api.main.supabase.upsert_pending"), \
         patch("backend.api.main._admin_phone", return_value="5534999945010"), \
         patch("backend.api.main.whatsapp.send_message", side_effect=raise_on_user_jid):
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    assert resp.json()["reason"] == "pending auth"


def test_autorizacao_envia_boas_vindas_pelo_lid():
    _ADMIN_PHONE = "5534999945010"
    admin_jid = "999000111@lid"
    admin_authorized = {"lid": admin_jid, "phone": _ADMIN_PHONE, "name": "Matheus"}
    new_user_lid = "555888777@lid"
    pending_user = {"lid": new_user_lid, "push_name": "Ricardim", "last_message": "oi"}

    with patch("backend.api.main.supabase.get_authorized", return_value=admin_authorized), \
         patch("backend.api.main._admin_phone", return_value=_ADMIN_PHONE), \
         patch("backend.api.main.supabase.pop_oldest_pending", return_value=pending_user), \
         patch("backend.api.main.supabase.add_authorized"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload(remote_jid=admin_jid, text="5534999301855"))
    assert resp.status_code == 200
    assert resp.json()["reason"] == "admin command"
    calls = [c.args[0] for c in mock_send.call_args_list]
    assert new_user_lid in calls
    assert _USER_PHONE not in calls
