"""Deduplicação de mensagens do WhatsApp reenviadas pela Evolution.

A Evolution reenvia a mesma mensagem (mesmo key.id) a cada ~65s quando o
webhook demora a responder. `claim_message` reserva a etiqueta no banco; o
reenvio bate na chave primária (409) e é descartado. A atomicidade real vem
da PRIMARY KEY em processed_messages — aqui testamos o mapeamento da resposta.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import backend.services.supabase as supabase
from backend.api.main import app


def _base_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "k")


def _mock_client(status_code: int) -> MagicMock:
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_client.__enter__.return_value.post.return_value = mock_resp
    return mock_client


def test_claim_message_nova_retorna_true(monkeypatch):
    _base_env(monkeypatch)
    with patch("backend.services.supabase.httpx.Client", return_value=_mock_client(201)):
        assert supabase.claim_message("3EB0DB360B218B04C777E3") is True


def test_claim_message_duplicada_retorna_false(monkeypatch):
    """409 = violação de chave primária = etiqueta já reservada = reenvio."""
    _base_env(monkeypatch)
    with patch("backend.services.supabase.httpx.Client", return_value=_mock_client(409)):
        assert supabase.claim_message("3EB0DB360B218B04C777E3") is False


# ── Trava no webhook ────────────────────────────────────────────────────────

client = TestClient(app)
_REMOTE_JID = "139247134720249@lid"
_AUTHORIZED = {"lid": _REMOTE_JID, "phone": "5534999301855", "name": "Ricardim"}


def _payload(msg_id="3EB0DB360B218B04C777E3", text="olá"):
    return {
        "data": {
            "key": {"fromMe": False, "remoteJid": _REMOTE_JID, "id": msg_id},
            "pushName": "Teste",
            "message": {"conversation": text},
        }
    }


def test_webhook_ignora_mensagem_duplicada():
    """Reenvio (claim_message=False) → ignorado, sem gerar relatório."""
    with patch("backend.api.main.supabase.claim_message", return_value=False), \
         patch("backend.api.main.reporter.generate_report") as mock_gen, \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    assert resp.json()["reason"] == "duplicate"
    mock_gen.assert_not_called()
    mock_send.assert_not_called()


def test_webhook_processa_mensagem_nova():
    """Etiqueta nova (claim_message=True) → segue o fluxo normal e responde."""
    with patch("backend.api.main.supabase.claim_message", return_value=True), \
         patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    mock_send.assert_called_once_with(_AUTHORIZED["phone"], "resposta")


def test_webhook_claim_falha_processa_mesmo_assim():
    """Banco de dedup fora do ar não pode deixar o usuário sem resposta."""
    with patch("backend.api.main.supabase.claim_message", side_effect=Exception("supabase timeout")), \
         patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    mock_send.assert_called_once_with(_AUTHORIZED["phone"], "resposta")
