"""Quando a geração falha, o usuário precisa ser avisado — não ficar no vácuo.

Regressão do caso real de 16/07/2026: a API do Claude devolveu 500, o webhook
engoliu o erro e o bot simplesmente emudeceu para o usuário.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)

_JID = "5516991016898@s.whatsapp.net"
_USER = {"lid": "255666618896603@lid", "phone": "5516991016898", "name": "G.Mouro"}

_PAYLOAD = {
    "data": {
        "key": {"remoteJid": _JID, "fromMe": False, "id": "X1"},
        "pushName": "G.Mouro",
        "message": {"conversation": "me manda as noticias do dia"},
    }
}


def _base_patches():
    return [
        patch("backend.api.main.supabase.get_authorized_by_jid", return_value=_USER),
        patch("backend.api.main.supabase.get_preferences", return_value=None),
        patch("backend.api.main.supabase.get_history", return_value=[]),
        patch("backend.api.main.supabase.get_summary", return_value=None),
        patch("backend.api.main.supabase.save_message"),
        patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}),
    ]


def test_falha_na_geracao_avisa_o_usuario():
    patches = _base_patches()
    for p in patches:
        p.start()
    try:
        with patch("backend.api.main.reporter.generate_report",
                   side_effect=Exception("Error code: 500 - api_error")), \
             patch("backend.api.main.whatsapp.send_message") as mock_send:
            resp = client.post("/api/webhook", json=_PAYLOAD)

        assert resp.json()["status"] == "error"
        mock_send.assert_called_once()
        destino, texto = mock_send.call_args[0]
        assert destino == _JID  # responde para quem escreveu
        assert "problema" in texto.lower()  # avisa, em vez de ficar mudo
    finally:
        for p in patches:
            p.stop()


def test_falha_no_aviso_nao_derruba_o_webhook():
    """Se até o aviso falhar, o webhook ainda responde (sem estourar exceção)."""
    patches = _base_patches()
    for p in patches:
        p.start()
    try:
        with patch("backend.api.main.reporter.generate_report",
                   side_effect=Exception("boom")), \
             patch("backend.api.main.whatsapp.send_message",
                   side_effect=Exception("evolution fora do ar")):
            resp = client.post("/api/webhook", json=_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
    finally:
        for p in patches:
            p.stop()
