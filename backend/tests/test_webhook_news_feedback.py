from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

AUTHORIZED = {"lid": "553499930185@lid", "phone": "5534999301855", "name": "Ricardim"}


def _make_webhook(text):
    return {
        "data": {
            "key": {"fromMe": False, "remoteJid": "553499930185@lid"},
            "pushName": "Ricardim",
            "message": {"conversation": text},
        }
    }


def test_webhook_news_feedback_salva_e_confirma():
    intent = {"intent": "news_feedback", "important": ["Fed"], "unimportant": ["eleições"]}
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main._detect_news_feedback", return_value=intent), \
         patch("backend.api.main.supabase.save_news_feedback") as mock_save, \
         patch("backend.api.main._generate_feedback_confirmation", return_value="Anotado!"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_make_webhook("só a notícia do Fed foi boa"))
    assert resp.status_code == 200
    assert resp.json()["reason"] == "news_feedback_saved"
    mock_save.assert_called_once_with("5534999301855", ["Fed"], ["eleições"], "só a notícia do Fed foi boa")
    mock_send.assert_called_once_with("5534999301855", "Anotado!")


def test_webhook_news_reset_apaga_e_confirma():
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main._detect_news_feedback", return_value={"intent": "news_reset"}), \
         patch("backend.api.main.supabase.delete_news_feedback") as mock_delete, \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_make_webhook("apaga minhas preferências de notícias"))
    assert resp.status_code == 200
    assert resp.json()["reason"] == "news_feedback_reset"
    mock_delete.assert_called_once_with("5534999301855")
    mock_send.assert_called_once()


def test_webhook_mensagem_normal_passa_news_feedback_para_reporter():
    feedback = [{"important_topics": ["Fed"], "unimportant_topics": []}]
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main._detect_news_feedback", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_news_feedback", return_value=feedback), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta") as mock_gen, \
         patch("backend.api.main.whatsapp.send_message"):
        resp = client.post("/api/webhook", json=_make_webhook("qual o dólar?"))
    assert resp.status_code == 200
    call_kwargs = mock_gen.call_args[1]
    assert call_kwargs.get("news_feedback") == feedback


def test_webhook_save_news_feedback_falha_nao_bloqueia_resposta():
    intent = {"intent": "news_feedback", "important": ["Fed"], "unimportant": []}
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main._detect_news_feedback", return_value=intent), \
         patch("backend.api.main.supabase.save_news_feedback", side_effect=Exception("timeout")), \
         patch("backend.api.main._generate_feedback_confirmation", return_value="Anotado!"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_make_webhook("só a notícia do Fed foi boa"))
    assert resp.status_code == 200
    mock_send.assert_called_once_with("5534999301855", "Anotado!")


def test_detect_news_feedback_retorna_message_quando_listas_vazias():
    """Se Haiku retorna news_feedback mas com listas vazias, trata como message."""
    from backend.api.main import _detect_news_feedback
    from unittest.mock import MagicMock
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"intent": "news_feedback", "important": [], "unimportant": []}')]
    with patch("backend.api.main.Anthropic") as MockA:
        MockA.return_value.messages.create.return_value = mock_response
        result = _detect_news_feedback("olá tudo bem")
    assert result["intent"] == "message"


def test_detect_news_feedback_fallback_em_excecao():
    from backend.api.main import _detect_news_feedback
    with patch("backend.api.main.Anthropic", side_effect=Exception("network error")):
        result = _detect_news_feedback("só a notícia do Fed foi boa")
    assert result["intent"] == "message"


def test_detect_news_feedback_com_last_report_nao_quebra_api():
    """last_report deve ser injetado no system, não como primeiro assistant message."""
    from backend.api.main import _detect_news_feedback
    from unittest.mock import MagicMock
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"intent": "news_feedback", "important": ["Fed"], "unimportant": []}')]
    with patch("backend.api.main.Anthropic") as MockA:
        MockA.return_value.messages.create.return_value = mock_response
        result = _detect_news_feedback("só a primeira foi boa", last_report="Relatório de ontem...")
    # Verificar que messages[0] é "user" (não "assistant")
    call_kwargs = MockA.return_value.messages.create.call_args[1]
    assert call_kwargs["messages"][0]["role"] == "user"
    assert len(call_kwargs["messages"]) == 1
    assert result["intent"] == "news_feedback"
