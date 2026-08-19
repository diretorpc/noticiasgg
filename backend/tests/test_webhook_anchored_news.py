from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, _extract_quoted_message_id

client = TestClient(app)

# Sessão 'noticias-ancoradas', Parte C (18/08/2026): o webhook casa a resposta
# citada com a notícia enviada pelo id EXATO da mensagem — nunca o modelo
# escolhendo entre candidatas.

_REMOTE_JID = "139247134720249@lid"
_USER_PHONE = "5534999301855"
_AUTHORIZED = {"lid": _REMOTE_JID, "phone": _USER_PHONE, "name": "Ricardim"}
_STANZA_ID = "3EB0AB92509EBD8A820860"

_NOTICIA = {
    "titulo_pt": "Milho dos EUA perde qualidade",
    "fonte": "Farm Progress",
    "url": "https://www.farmprogress.com/x",
    "conteudo": "Condição boa/excelente caiu para 61%.",
}


# ── _extract_quoted_message_id (puro, sem HTTP) ────────────────────────────

@pytest.mark.unit
def test_extract_quoted_message_id_no_topo_do_registro():
    """Formato MEDIDO ao vivo em 18/08/2026 para messageType 'conversation':
    contextInfo é irmão de `message`, não filho."""
    data = {
        "message": {"conversation": "me fala mais sobre isso"},
        "contextInfo": {"stanzaId": _STANZA_ID, "quotedMessage": {}},
    }
    assert _extract_quoted_message_id(data) == _STANZA_ID


@pytest.mark.unit
def test_extract_quoted_message_id_dentro_de_extended_text_message():
    """Segunda tentativa: formato sugerido pela documentação, não o observado
    — mas o real pode variar por tipo de mensagem, então tenta os dois."""
    data = {
        "message": {
            "extendedTextMessage": {
                "text": "me fala mais",
                "contextInfo": {"stanzaId": _STANZA_ID},
            }
        }
    }
    assert _extract_quoted_message_id(data) == _STANZA_ID


@pytest.mark.unit
def test_extract_quoted_message_id_prefere_o_topo():
    data = {
        "message": {"extendedTextMessage": {"text": "x", "contextInfo": {"stanzaId": "id-de-dentro"}}},
        "contextInfo": {"stanzaId": "id-do-topo"},
    }
    assert _extract_quoted_message_id(data) == "id-do-topo"


@pytest.mark.unit
def test_extract_quoted_message_id_sem_citacao_devolve_none():
    assert _extract_quoted_message_id({"message": {"conversation": "oi"}}) is None
    assert _extract_quoted_message_id({}) is None


@pytest.mark.unit
def test_extract_quoted_message_id_contextinfo_sem_stanza_id():
    data = {"message": {"conversation": "oi"}, "contextInfo": {"participant": "x"}}
    assert _extract_quoted_message_id(data) is None


# ── Integração via /api/webhook ─────────────────────────────────────────────

def _payload(text="me fala mais sobre isso", stanza_id=_STANZA_ID):
    d = {
        "key": {"fromMe": False, "remoteJid": _REMOTE_JID},
        "pushName": "Ricardim",
        "message": {"conversation": text},
    }
    if stanza_id:
        d["contextInfo"] = {"stanzaId": stanza_id}
    return {"data": d}


@pytest.mark.unit
def test_webhook_resposta_citada_injeta_noticia_no_generate_report():
    with patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_authorized_by_jid", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main._maybe_summarize"), \
         patch("backend.api.main.supabase.get_news_by_message_id", return_value=_NOTICIA) as mock_get_news, \
         patch("backend.api.main.reporter.generate_report", return_value="resposta") as mock_generate, \
         patch("backend.api.main.whatsapp.send_message"):
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    mock_get_news.assert_called_once_with(_STANZA_ID)
    assert mock_generate.call_args.kwargs["anchored_news"] == _NOTICIA


@pytest.mark.unit
def test_webhook_sem_citacao_nao_busca_noticia():
    with patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_authorized_by_jid", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main._maybe_summarize"), \
         patch("backend.api.main.supabase.get_news_by_message_id") as mock_get_news, \
         patch("backend.api.main.reporter.generate_report", return_value="resposta") as mock_generate, \
         patch("backend.api.main.whatsapp.send_message"):
        resp = client.post("/api/webhook", json=_payload(stanza_id=None))
    assert resp.status_code == 200
    mock_get_news.assert_not_called()
    assert mock_generate.call_args.kwargs["anchored_news"] is None


@pytest.mark.unit
def test_webhook_id_citado_desconhecido_nao_ancora_nada():
    """get_news_by_message_id devolve None (id não é de notícia, ou já foi
    limpo) — o fluxo segue igual a antes, sem inventar nada."""
    with patch("backend.api.main.supabase.get_authorized", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_authorized_by_jid", return_value=_AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main._maybe_summarize"), \
         patch("backend.api.main.supabase.get_news_by_message_id", return_value=None), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta") as mock_generate, \
         patch("backend.api.main.whatsapp.send_message"):
        resp = client.post("/api/webhook", json=_payload())
    assert resp.status_code == 200
    assert mock_generate.call_args.kwargs["anchored_news"] is None
