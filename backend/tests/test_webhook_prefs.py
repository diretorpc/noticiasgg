import pytest
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
            "message": {"conversation": text}
        }
    }


def test_webhook_mensagem_normal_nao_salva_preferencias():
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main._detect_preference_intent",
               return_value={"intent": "message"}), \
         patch("backend.api.main.reporter.generate_report", return_value="resposta"), \
         patch("backend.api.main.whatsapp.send_message"), \
         patch("backend.api.main.supabase.save_preferences") as mock_save:
        resp = client.post("/api/webhook", json=_make_webhook("qual é o dólar hoje?"))
    assert resp.status_code == 200
    mock_save.assert_not_called()


def test_webhook_preferencia_salva_e_responde():
    intent_result = {
        "intent": "preference",
        "sections": {"market": False, "crypto": True, "indicators_us": False,
                     "indicators_br": False, "news": True, "commodities_br": False,
                     "politics_br": False},
        "report_time": None,
        "reset": False,
        "reply": "Feito! Seu relatório vai incluir apenas notícias e criptomoedas."
    }
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value=intent_result), \
         patch("backend.api.main.supabase.save_preferences") as mock_save, \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        resp = client.post("/api/webhook", json=_make_webhook("quero só notícias e crypto"))
    assert resp.status_code == 200
    mock_save.assert_called_once_with(
        "5534999301855",
        sections=intent_result["sections"],
        report_time=intent_result["report_time"],
        audio_for_text=None,
        audio_for_media=None,
        tts_voice=None,
        tts_speed=None,
    )
    mock_send.assert_called_once_with(
        "5534999301855",
        "Feito! Seu relatório vai incluir apenas notícias e criptomoedas."
    )


def test_webhook_reset_preferencias():
    intent_result = {
        "intent": "preference",
        "sections": None,
        "report_time": None,
        "reset": True,
        "reply": "Pronto! Você voltará a receber o relatório completo no horário padrão."
    }
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value=intent_result), \
         patch("backend.api.main.supabase.delete_preferences") as mock_delete, \
         patch("backend.api.main.whatsapp.send_message"):
        resp = client.post("/api/webhook", json=_make_webhook("volta pro padrão"))
    assert resp.status_code == 200
    mock_delete.assert_called_once_with("5534999301855")


# ── Seção aposentada (`polls_br`, 11/2026) — achado 2 do Apolo ───────────────
# Medido com o Haiku real: prompt de 7 seções + `seções_atuais` com a chave antiga
# fez o modelo zerar TODAS as seções em 5 de 8 pedidos de "remove cripto". A chave
# não pode chegar ao modelo, nem voltar dele para o banco.

@pytest.mark.unit
def test_contexto_do_parser_nao_leva_secao_aposentada():
    from unittest.mock import MagicMock
    from backend.api import main
    resposta = MagicMock()
    resposta.content = [MagicMock(text='{"intent": "message"}')]
    with patch("backend.api.main.Anthropic") as MockA, \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}):
        MockA.return_value.messages.create.return_value = resposta
        main._detect_preference_intent(
            "remove cripto", current_sections={"crypto": True, "news": True, "polls_br": True})
    enviado = MockA.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "polls_br" not in enviado
    assert '"crypto": true' in enviado


@pytest.mark.unit
def test_webhook_nao_salva_secao_desconhecida_devolvida_pelo_parser():
    intent_result = {
        "intent": "preference",
        "sections": {"market": True, "crypto": False, "polls_br": True},
        "report_time": None,
        "reset": False,
        "reply": "Feito.",
    }
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value=intent_result), \
         patch("backend.api.main.whatsapp.send_message"), \
         patch("backend.api.main.supabase.save_preferences") as mock_save:
        resp = client.post("/api/webhook", json=_make_webhook("remove cripto"))
    assert resp.status_code == 200
    assert mock_save.call_args.kwargs["sections"] == {"market": True, "crypto": False}


@pytest.mark.unit
def test_parser_so_com_secao_aposentada_nao_apaga_as_escolhas():
    """"tira as pesquisas eleitorais" pode voltar como `{"polls_br": False}`. Filtrado,
    isso vira `{}` — e `{}` gravado apaga as seções escolhidas (achado 1, 2ª revisão
    do Apolo). Sem seção conhecida, não há o que salvar."""
    intent_result = {
        "intent": "preference",
        "sections": {"polls_br": False},
        "report_time": None,
        "reset": False,
        "reply": "Feito.",
    }
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences",
               return_value={"sections": {"market": True, "crypto": True, "polls_br": True}}), \
         patch("backend.api.main._detect_preference_intent", return_value=intent_result), \
         patch("backend.api.main.whatsapp.send_message"), \
         patch("backend.api.main.supabase.save_preferences") as mock_save:
        resp = client.post("/api/webhook", json=_make_webhook("tira as pesquisas eleitorais"))
    assert resp.status_code == 200
    mock_save.assert_not_called()
