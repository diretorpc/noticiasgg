"""Leitor de preferências por WhatsApp (`main._detect_preference_intent`).

Medido pelo Apolo em 09/11/2026 com o Haiku real: 29 de 29 respostas vieram dentro
de cerca de código (```json ... ```). O `json.loads` direto falhava, o `except`
engolia calado e TODO pedido ("remove cripto") virava conversa — nada era salvo.
Os testes do webhook não viam porque trocam o leitor inteiro por um dublê.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api import main
from backend.api.main import app
from backend.services import selflink

pytestmark = pytest.mark.unit

_CERCADO = '```json\n{"intent": "preference", "sections": {"crypto": false}, "reply": "Cripto removida."}\n```'


def _haiku_responde(texto):
    resposta = MagicMock()
    resposta.content = [MagicMock(text=texto)]
    return resposta


@pytest.mark.parametrize("bruto", [
    _CERCADO,
    '{"intent": "preference", "sections": {"crypto": false}, "reply": "Cripto removida."}',
    '```\n{"intent": "preference", "sections": {"crypto": false}, "reply": "Cripto removida."}\n```',
    'Aqui está:\n{"intent": "preference", "sections": {"crypto": false}, "reply": "Cripto removida."}',
])
def test_le_o_json_com_ou_sem_cerca(bruto):
    assert main._parse_json_reply(bruto)["sections"] == {"crypto": False}


def test_resposta_cercada_do_haiku_vira_preferencia():
    with patch("backend.api.main.Anthropic") as MockA, \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}):
        MockA.return_value.messages.create.return_value = _haiku_responde(_CERCADO)
        intent = main._detect_preference_intent("remove cripto")
    assert intent["intent"] == "preference"
    assert intent["sections"] == {"crypto": False}


def test_falha_de_leitura_nao_fica_calada(caplog):
    with patch("backend.api.main.Anthropic") as MockA, \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}), \
         caplog.at_level(logging.WARNING, logger="noticiasgg"):
        MockA.return_value.messages.create.return_value = _haiku_responde("não sei")
        intent = main._detect_preference_intent("remove cripto")
    assert intent == {"intent": "message"}
    assert any("leitor de preferências" in r.getMessage() for r in caplog.records)


def test_usuario_sem_preferencia_tambem_manda_secoes_atuais_ao_haiku():
    """Medido com o Haiku real em 09/11/2026: sem `seções_atuais`, "remove cripto"
    volta 3 de 3 vezes com `sections: null` e a resposta "Criptomoedas removidas" —
    confirma ao usuário uma mudança que não foi gravada."""
    with patch("backend.api.main.Anthropic") as MockA, \
         patch.dict("os.environ", {"ANTHROPIC_API_KEY": "x"}):
        MockA.return_value.messages.create.return_value = _haiku_responde('{"intent": "message"}')
        main._detect_preference_intent("remove cripto", current_sections=None)
    enviado = MockA.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "seções_atuais" in enviado
    assert '"crypto": true' in enviado


# ── Seções e horário do relatório: o WhatsApp NÃO grava, o chat aponta o /me ──
# `user_preferences.sections`/`report_time` não são lidos por nada que entrega
# mensagem: o relatório sai da grade `report_schedules` (`cron_report.py`), o chat
# usa `sections={}`, e o único leitor era `send_report.py` (rota do n8n, desligado).
# Gravar ali e responder "agendado para 18h" seria confirmar o que não acontece
# (3ª revisão do Apolo, 09/11/2026; decisão do Matheus: mandar para o /me).

AUTHORIZED = {"lid": "553499930185@lid", "phone": "5534999301855", "name": "Ricardim"}
COM_LINK = {**AUTHORIZED, "selflink_token": "tok123"}


def _webhook(texto):
    return {"data": {"key": {"fromMe": False, "remoteJid": "553499930185@lid"},
                     "pushName": "Ricardim", "message": {"conversation": texto}}}


def _roda(intent, user=AUTHORIZED, texto="remove cripto", resposta_chat="resposta do chat"):
    with patch("backend.api.main.supabase.get_authorized", return_value=user), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent", return_value=intent), \
         patch("backend.api.main.supabase.save_preferences") as mock_save, \
         patch("backend.api.main.supabase.delete_preferences") as mock_delete, \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.supabase.save_message") as mock_hist, \
         patch("backend.api.main.supabase.get_news_by_message_id", return_value=None), \
         patch("backend.api.main._maybe_summarize"), \
         patch("backend.api.main.reporter.generate_report", return_value=resposta_chat) as mock_chat, \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        TestClient(app).post("/api/webhook", json=_webhook(texto))
    return {
        "save": mock_save, "delete": mock_delete, "chat": mock_chat, "hist": mock_hist,
        "enviado": mock_send.call_args.args[1] if mock_send.called else None,
    }


def _intent(**campos):
    base = {"intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": None, "audio_for_media": None, "tts_voice": None,
            "tts_speed": None, "list_voices": False, "reset": False, "reply": "Feito."}
    return {**base, **campos}


def test_pedido_so_de_secao_vai_ao_chat():
    """Aviso fixo engolia pergunta: "quero saber só do mercado hoje" (o Haiku lê como
    configuração) recebia "ajuste na sua página" em vez dos números. O chat responde a
    informação E sabe que não altera relatório (regra no prompt)."""
    r = _roda(_intent(sections={"crypto": False}, reply="Cripto removida."), user=COM_LINK)
    r["save"].assert_not_called()
    r["chat"].assert_called_once()
    assert r["enviado"] == "resposta do chat"


def test_o_modelo_ve_o_marcador_nunca_o_token():
    """Com o token no prompt, uma página raspada com injeção podia mandar o modelo
    levá-lo a `read_article`/`search_web` (que saem para terceiros) — e com o token se
    reescreve a grade do relatório pelo `PUT /api/me/schedule` (achado 2, 4ª revisão
    do Apolo). O código troca o marcador pelo link só na saída; o histórico guarda o
    marcador, para o token não voltar ao modelo no turno seguinte."""
    r = _roda(_intent(sections={"crypto": False}), user=COM_LINK,
              resposta_chat=f"Ajuste em {selflink.LINK_PLACEHOLDER}")
    assert r["chat"].call_args.kwargs["panel_link"] == selflink.LINK_PLACEHOLDER
    assert r["enviado"].endswith("/me?token=tok123")
    salvo_assistente = [c.args[2] for c in r["hist"].call_args_list if c.args[1] == "assistant"]
    assert salvo_assistente == [f"Ajuste em {selflink.LINK_PLACEHOLDER}"]


def test_sem_link_o_modelo_nao_recebe_marcador():
    r = _roda(_intent(report_time="18:00", reply="Relatório agendado para 18h."), texto="relatório às 18h")
    r["save"].assert_not_called()
    assert r["chat"].call_args.kwargs["panel_link"] is None


def test_pedido_misto_grava_o_audio_e_redireciona_o_relatorio():
    r = _roda(_intent(sections={"crypto": False}, tts_voice="onyx", reply="Voz onyx e cripto removida."),
              user=COM_LINK)
    kw = r["save"].call_args.kwargs
    assert kw["sections"] is None and kw["report_time"] is None and kw["tts_voice"] == "onyx"
    assert "cripto removida" not in r["enviado"].lower()
    assert "Ajustei" in r["enviado"]
    assert r["enviado"].endswith("/me?token=tok123")


def test_confirmacao_sem_nada_a_gravar_vira_conversa():
    """Medido com o Haiku real: "não quero mais receber o relatório" voltou como
    preferência com TODOS os campos nulos, e o bot respondia "Relatório diário
    desativado" sem gravar nada."""
    r = _roda(_intent(reply="Relatório diário desativado."), texto="não quero mais receber o relatório")
    r["save"].assert_not_called()
    r["chat"].assert_called_once()
    assert r["enviado"] == "resposta do chat"


def test_so_secao_aposentada_vira_conversa_sem_gravar():
    r = _roda(_intent(sections={"polls_br": False}))
    r["save"].assert_not_called()
    r["chat"].assert_called_once()


def test_reset_diz_o_que_voltou_e_nao_promete_o_relatorio():
    """Haiku real, 3 de 3: "volta o relatório pro padrão" → `reset: true`. O reset
    apaga voz/áudio, não a grade; o "Preferências resetadas." dele fazia o usuário
    achar que o relatório tinha voltado (achado 1, 4ª revisão do Apolo)."""
    r = _roda(_intent(reset=True, reply="Preferências resetadas."), user=COM_LINK,
              texto="volta o relatório pro padrão")
    r["delete"].assert_called_once()
    assert r["enviado"] != "Preferências resetadas."
    assert "Voz e áudio voltaram ao padrão" in r["enviado"]
    assert r["enviado"].endswith("/me?token=tok123")


@pytest.mark.parametrize("campo,valor", [
    ("tts_speed", "rápido"), ("tts_speed", 9.0), ("tts_speed", True),
    ("tts_voice", "masculina"), ("audio_for_text", "sim"),
])
def test_valor_invalido_do_haiku_nao_e_gravado(campo, valor):
    """`tts_speed` gravado como texto fazia `float()` estourar em TODA mensagem
    seguinte desse usuário — "Tive um problema" até alguém limpar o banco (achado 3)."""
    r = _roda(_intent(**{campo: valor}))
    r["save"].assert_not_called()
    r["chat"].assert_called_once()


def test_valor_valido_do_haiku_e_gravado():
    r = _roda(_intent(tts_voice="echo", tts_speed=1.1, audio_for_text=False, reply="Voz echo."))
    kw = r["save"].call_args.kwargs
    assert (kw["tts_voice"], kw["tts_speed"], kw["audio_for_text"]) == ("echo", 1.1, False)
    assert r["enviado"] == "Voz echo."


def test_link_do_painel_tem_fonte_unica():
    with patch.dict("os.environ", {"PANEL_BASE_URL": "https://painel.exemplo/"}):
        assert selflink.selflink_url("abc") == "https://painel.exemplo/me?token=abc"
        assert selflink.fill_link(f"veja {selflink.LINK_PLACEHOLDER}", COM_LINK) == \
            "veja https://painel.exemplo/me?token=tok123"


def test_prompt_do_chat_proibe_confirmar_mudanca_de_relatorio():
    """Medido em produção (Sonnet real, 09/11/2026): "manda o relatório às 18h" →
    "Configurado! A partir de hoje você recebe o relatório diário às 18h." Nada mudava."""
    from backend.services import reporter
    chat = reporter._build_system("Ana Lima", {}, panel_link=selflink.LINK_PLACEHOLDER)
    assert selflink.LINK_PLACEHOLDER in chat
    assert "NÃO" in chat and "horário" in chat
    assert "peça o link ao admin" in reporter._build_system("Ana Lima", {})
    relatorio = reporter._build_system("Ana Lima", {"market": {}}, panel_link=selflink.LINK_PLACEHOLDER)
    assert selflink.LINK_PLACEHOLDER not in relatorio


# ── Caminho de ÁUDIO: não tinha teste nenhum ──────────────────────────────────

def _roda_audio(intent, user=COM_LINK):
    payload = {"data": {"key": {"fromMe": False, "remoteJid": "553499930185@lid"},
                        "pushName": "Ricardim", "message": {"audioMessage": {"seconds": 2}}}}
    with patch("backend.api.main.supabase.get_authorized", return_value=user), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.whatsapp.download_media", return_value={"base64": "x"}), \
         patch("backend.api.main.media_service.transcribe_audio", return_value="volta pro padrão"), \
         patch("backend.api.main._detect_preference_intent", return_value=intent), \
         patch("backend.api.main.supabase.save_preferences") as mock_save, \
         patch("backend.api.main.supabase.delete_preferences") as mock_delete, \
         patch("backend.api.main.media_service.text_to_speech", side_effect=RuntimeError("sem tts")), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        TestClient(app).post("/api/webhook", json=payload)
    return mock_save, mock_delete, mock_send.call_args.args[1]


def test_reset_por_audio_apaga_e_diz_o_que_voltou():
    mock_save, mock_delete, enviado = _roda_audio(_intent(reset=True, reply="Preferências resetadas."))
    mock_delete.assert_called_once()
    assert "Voz e áudio voltaram ao padrão" in enviado


def test_audio_misto_grava_a_voz_e_redireciona_o_relatorio():
    mock_save, _, enviado = _roda_audio(_intent(tts_voice="onyx", sections={"crypto": False},
                                                reply="Voz onyx e cripto removida."))
    assert mock_save.call_args.kwargs["tts_voice"] == "onyx"
    assert "cripto removida" not in enviado.lower()
    assert enviado.endswith("/me?token=tok123")


# ── Link pessoal nunca sai em ÁUDIO (achado 1, 5ª revisão do Apolo) ──────────
# Falado, o link são ~89 caracteres (43 aleatórios do token) que a pessoa não tem
# onde clicar — e o token iria para o TTS de terceiro. Resposta com link sai escrita.

def _roda_midia(tipo, intent, prefs, resposta_chat):
    mensagem = {"audioMessage": {"seconds": 2}} if tipo == "audio" else {"imageMessage": {"caption": "olha"}}
    payload = {"data": {"key": {"fromMe": False, "remoteJid": "553499930185@lid"},
                        "pushName": "Ricardim", "message": mensagem}}
    with patch("backend.api.main.supabase.get_authorized", return_value=COM_LINK), \
         patch("backend.api.main.supabase.get_preferences", return_value=prefs), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.supabase.save_message") as mock_hist, \
         patch("backend.api.main._maybe_summarize"), \
         patch("backend.api.main.whatsapp.download_media", return_value={"base64": "x", "mimetype": "image/jpeg"}), \
         patch("backend.api.main.media_service.transcribe_audio", return_value="remove cripto"), \
         patch("backend.api.main._detect_preference_intent", return_value=intent), \
         patch("backend.api.main.supabase.save_preferences"), \
         patch("backend.api.main.supabase.delete_preferences"), \
         patch("backend.api.main.reporter.generate_report", return_value=resposta_chat), \
         patch("backend.api.main.media_service.text_to_speech", return_value=b"mp3") as mock_tts, \
         patch("backend.api.main.whatsapp.send_audio") as mock_audio, \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        TestClient(app).post("/api/webhook", json=payload)
    return {"tts": mock_tts, "audio": mock_audio, "hist": mock_hist,
            "enviado": mock_send.call_args.args[1] if mock_send.called else None}


_TUDO_EM_AUDIO = {"audio_for_text": True, "audio_for_media": True}
_COM_MARCADOR = f"Ajuste em {selflink.LINK_PLACEHOLDER}"


def test_reset_por_audio_com_tts_funcionando_manda_o_link_escrito():
    r = _roda_midia("audio", _intent(reset=True), _TUDO_EM_AUDIO, "x")
    r["tts"].assert_not_called()
    assert r["enviado"].endswith("/me?token=tok123")


def test_preferencia_por_texto_com_audio_ligado_manda_o_link_escrito():
    with patch("backend.api.main.supabase.get_authorized", return_value=COM_LINK), \
         patch("backend.api.main.supabase.get_preferences", return_value=_TUDO_EM_AUDIO), \
         patch("backend.api.main._detect_preference_intent", return_value=_intent(reset=True)), \
         patch("backend.api.main.supabase.delete_preferences"), \
         patch("backend.api.main.media_service.text_to_speech", return_value=b"mp3") as mock_tts, \
         patch("backend.api.main.whatsapp.send_audio"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        TestClient(app).post("/api/webhook", json=_webhook("volta pro padrão"))
    mock_tts.assert_not_called()
    assert mock_send.call_args.args[1].endswith("/me?token=tok123")


@pytest.mark.parametrize("tipo", ["audio", "image"])
def test_chat_por_audio_ou_midia_troca_o_marcador_e_nao_fala_o_link(tipo):
    r = _roda_midia(tipo, {"intent": "message"}, _TUDO_EM_AUDIO, _COM_MARCADOR)
    r["tts"].assert_not_called()
    assert r["enviado"] == "Ajuste em https://noticiasgg-painel.vercel.app/me?token=tok123"
    salvo = [c.args[2] for c in r["hist"].call_args_list if c.args[1] == "assistant"]
    assert salvo == [_COM_MARCADOR]


def test_chat_sem_link_continua_saindo_em_audio():
    r = _roda_midia("audio", {"intent": "message"}, _TUDO_EM_AUDIO, "Dólar em R$ 5,51.")
    r["tts"].assert_called_once()
    r["audio"].assert_called_once()


@pytest.mark.parametrize("resposta,fala", [(_COM_MARCADOR, False), ("Dólar em R$ 5,51.", True)])
def test_chat_por_texto_com_audio_ligado_so_fala_quando_nao_tem_link(resposta, fala):
    """O único ponto que nenhum teste vigiava (mutação da 6ª revisão do Apolo)."""
    with patch("backend.api.main.supabase.get_authorized", return_value=COM_LINK), \
         patch("backend.api.main.supabase.get_preferences", return_value=_TUDO_EM_AUDIO), \
         patch("backend.api.main._detect_preference_intent", return_value={"intent": "message"}), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.supabase.get_news_by_message_id", return_value=None), \
         patch("backend.api.main._maybe_summarize"), \
         patch("backend.api.main.reporter.generate_report", return_value=resposta), \
         patch("backend.api.main.media_service.text_to_speech", return_value=b"mp3") as mock_tts, \
         patch("backend.api.main.whatsapp.send_audio"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        TestClient(app).post("/api/webhook", json=_webhook("qual o dólar?"))
    assert mock_tts.called is fala
    if not fala:
        assert mock_send.call_args.args[1].endswith("/me?token=tok123")


# ── Pedidos de ÁUDIO vão ao Haiku, não a um regex ─────────────────────────────
# O regex `_quick_audio_check` LIGAVA o áudio em "não quero áudio", "sem áudio por
# favor", "prefere uma voz masculina" e "fala sobre a voz do Lula" (13/20 numa
# amostra de 09/11/2026). O Haiku, com a cerca consertada, acertou 20/20. O regex
# foi tirado; o de velocidade/voz (`_quick_tts_check`) fica.

@pytest.mark.parametrize("frase", [
    "não quero áudio", "sem áudio por favor", "não precisa mandar áudio",
    "prefere uma voz masculina", "fala sobre a voz do Lula no discurso",
])
def test_frase_de_audio_e_decidida_pelo_haiku(frase):
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent",
               return_value=_intent(audio_for_text=False, audio_for_media=False, reply="Áudio desligado.")) as leitor, \
         patch("backend.api.main.supabase.save_preferences") as mock_save, \
         patch("backend.api.main.whatsapp.send_message"):
        TestClient(app).post("/api/webhook", json=_webhook(frase))
    assert leitor.call_args.args[0] == frase
    assert mock_save.call_args.kwargs["audio_for_text"] is False


def test_velocidade_continua_no_regex_sem_chamar_o_haiku():
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=None), \
         patch("backend.api.main._detect_preference_intent") as leitor, \
         patch("backend.api.main.supabase.save_preferences") as mock_save, \
         patch("backend.api.main.whatsapp.send_message"):
        TestClient(app).post("/api/webhook", json=_webhook("fala mais devagar"))
    leitor.assert_not_called()
    assert mock_save.call_args.kwargs["tts_speed"] == 0.78


def test_chat_nao_promete_ativar_audio():
    """Pedido de áudio só chega ao Sonnet quando o leitor NÃO aplicou nada (Haiku
    fora do ar ou leitura errada). O prompt mandava responder "Ativando agora!" —
    confirmação de algo que não foi gravado."""
    from backend.services import reporter
    chat = reporter._build_system(None, {})
    assert "Ativando agora" not in chat
    assert "ativa áudio" in chat
    # Sonnet real, 1 de 3: "por que você parou de me mandar áudio?" → "fala com o admin"
    # (estendia a regra dos ALERTAS para o áudio). E "o sistema controla" expõe a
    # mecânica interna ao usuário (5ª rodada do Apolo na remoção do regex).
    assert "não é com o admin" in chat
    assert "quem liga e desliga isso é o sistema" not in chat
