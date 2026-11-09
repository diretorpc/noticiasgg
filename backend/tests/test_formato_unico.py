"""Pedido de formato SÓ PARA AGORA ("manda em texto dessa vez, tô em reunião").

Medido pelo Apolo em 09/11/2026 com o Haiku real: o pedido pontual gravava
`audio_for_text=False` PARA SEMPRE, e a resposta dizia "Ok, próxima resposta em texto"
— a pessoa esperava o áudio voltar sozinho, e ele não voltava.

Regra de agora, sem guardar estado nenhum:
- pontual COM pergunta junto → a pergunta é respondida no formato pedido, nada gravado;
- pontual SOZINHO → nada gravado, texto fixo ensinando a mandar a pergunta junto;
- voz/velocidade pontual → nada gravado, texto fixo dizendo que essas só mudam de vez.

Os testes `unit` simulam o Haiku. A 1ª versão desta correção passou em todos eles e
NÃO funcionava: o Haiku real nunca devolvia `pontual` quando havia pergunta junto, e o
teste simulava justamente essa resposta (falha de processo, 6ª revisão do Apolo). Por
isso o `smoke` no fim chama o Haiku de verdade nos casos de pergunta junto.
"""
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.api import main
from backend.api.main import app

AUTHORIZED = {"lid": "553499930185@lid", "phone": "5534999301855", "name": "Ricardim"}
_TUDO_EM_AUDIO = {"audio_for_text": True, "audio_for_media": True}


def _intent(**campos):
    base = {"intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": None, "audio_for_media": None, "tts_voice": None,
            "tts_speed": None, "list_voices": False, "reset": False, "pontual": False,
            "pergunta_junto": False, "reply": "Ok, próxima resposta em texto."}
    return {**base, **campos}


@pytest.mark.unit
def test_prompt_pede_pontual_e_pergunta_junto():
    assert '"pontual"' in main._PREFERENCE_SYSTEM
    assert '"pergunta_junto"' in main._PREFERENCE_SYSTEM
    assert "manda em texto dessa vez, como tá o dólar?" in main._PREFERENCE_SYSTEM


@pytest.mark.unit
@pytest.mark.parametrize("campos,formato", [
    ({"audio_for_text": False, "audio_for_media": False}, "texto"),
    ({"audio_for_text": False}, "texto"),
    ({"audio_for_text": True, "audio_for_media": True}, "audio"),
])
def test_pontual_com_pergunta_vira_conversa_no_formato(campos, formato):
    r = main._settle_preference(_intent(pontual=True, pergunta_junto=True, **campos))
    assert r == {"intent": "message", "_formato_unico": formato}


@pytest.mark.unit
def test_pontual_sozinho_nao_grava_e_ensina_a_mandar_junto():
    r = main._settle_preference(_intent(pontual=True, audio_for_text=False, audio_for_media=False))
    assert r["intent"] == "preference" and r["_gravar"] == {}
    texto = main._preference_reply(r, AUTHORIZED)
    assert "em texto dessa vez:" in texto
    assert "desativa áudio" in texto
    assert "próxima" not in texto.lower(), "não pode prometer o que não guarda"


@pytest.mark.unit
@pytest.mark.parametrize("campos", [{"tts_speed": 0.78}, {"tts_voice": "echo"}, {}])
def test_pergunta_junto_sem_formato_vira_conversa_comum(campos):
    """Haiku real: "fala mais devagar só nessa: o que é Selic?" → velocidade + pontual +
    pergunta_junto. Sem formato, caía no texto fixo de voz e a Selic ficava sem
    resposta (7ª revisão do Apolo). Pergunta junto é SEMPRE respondida."""
    r = main._settle_preference(_intent(pontual=True, pergunta_junto=True, **campos))
    assert r == {"intent": "message"}


@pytest.mark.unit
def test_pontual_sem_voz_nem_formato_vira_conversa():
    """"só hoje me manda só o mercado" → seções + pontual: recebia o texto fixo de VOZ."""
    r = main._settle_preference(_intent(pontual=True, sections={"market": True}))
    assert r == {"intent": "message"}


@pytest.mark.unit
@pytest.mark.parametrize("campos", [{"tts_speed": 0.78}, {"tts_voice": "echo"}])
def test_voz_ou_velocidade_pontual_nao_grava(campos):
    """Haiku real: "só dessa vez fala mais devagar" → `tts_speed` + `pontual`, e a
    resposta "Próxima resposta mais devagar" — gravando para sempre."""
    r = main._settle_preference(_intent(pontual=True, **campos))
    assert r["_gravar"] == {}
    texto = main._preference_reply(r, AUTHORIZED)
    assert "muda a voz para" in texto


@pytest.mark.unit
def test_reset_vale_mesmo_com_pontual():
    r = main._settle_preference(_intent(reset=True, pontual=True))
    assert r["intent"] == "preference" and r.get("reset") is True


@pytest.mark.unit
def test_permanente_continua_gravando():
    r = main._settle_preference(_intent(audio_for_text=False, audio_for_media=False))
    assert r["_gravar"] == {"audio_for_text": False, "audio_for_media": False}


@pytest.mark.unit
def test_chat_sabe_que_a_resposta_ja_sai_no_formato_pedido():
    """Sonnet real, 2 de 2: "dessa vez em áudio: como fechou o ibovespa?" saía EM ÁUDIO
    abrindo com "O pedido de áudio não foi aplicado" (7ª revisão do Apolo)."""
    from backend.services import reporter
    chat = reporter._build_system(None, {}, formato_resposta="audio")
    assert "já sai em áudio" in chat
    assert "já sai em" not in reporter._build_system(None, {})


@pytest.mark.unit
def test_chat_sabe_que_voz_se_troca_pelo_chat():
    """Sonnet real, pedido misto: "Mudança de voz não é algo que consigo ajustar por
    aqui — isso é com o admin." Falso: voz se troca dizendo "muda a voz para X"."""
    from backend.services import reporter
    chat = reporter._build_system(None, {})
    assert "muda a voz para" in chat


def _texto(prefs, intent, mensagem="manda em texto dessa vez, o dólar subiu?",
           resposta="O dólar subiu 0,4%."):
    payload = {"data": {"key": {"fromMe": False, "remoteJid": "553499930185@lid"},
                        "pushName": "Ricardim", "message": {"conversation": mensagem}}}
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=prefs), \
         patch("backend.api.main._detect_preference_intent", return_value=intent), \
         patch("backend.api.main.supabase.save_preferences") as mock_save, \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main.supabase.get_news_by_message_id", return_value=None), \
         patch("backend.api.main._maybe_summarize"), \
         patch("backend.api.main.reporter.generate_report", return_value=resposta) as mock_chat, \
         patch("backend.api.main.media_service.text_to_speech", return_value=b"mp3") as mock_tts, \
         patch("backend.api.main.whatsapp.send_audio") as mock_audio, \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        TestClient(app).post("/api/webhook", json=payload)
    return {"save": mock_save, "chat": mock_chat, "tts": mock_tts, "audio": mock_audio,
            "enviado": mock_send.call_args.args[1] if mock_send.called else None}


@pytest.mark.unit
def test_texto_dessa_vez_com_pergunta_responde_em_texto_e_nao_grava():
    r = _texto(_TUDO_EM_AUDIO, _intent(pontual=True, pergunta_junto=True,
                                       audio_for_text=False, audio_for_media=False))
    r["save"].assert_not_called()
    r["chat"].assert_called_once()
    assert r["chat"].call_args.kwargs["formato_resposta"] == "texto"
    r["tts"].assert_not_called()
    assert r["enviado"] == "O dólar subiu 0,4%."


@pytest.mark.unit
def test_audio_dessa_vez_com_pergunta_responde_em_audio_e_nao_grava():
    r = _texto({"audio_for_text": False}, _intent(pontual=True, pergunta_junto=True,
                                                  audio_for_text=True, audio_for_media=True))
    r["save"].assert_not_called()
    assert r["chat"].call_args.kwargs["formato_resposta"] == "audio"
    r["tts"].assert_called_once()
    r["audio"].assert_called_once()


@pytest.mark.unit
def test_pontual_sozinho_sai_escrito_mesmo_com_audio_ligado():
    """O texto fixo ensina a escrever um comando — falado, não serve para copiar."""
    r = _texto(_TUDO_EM_AUDIO, _intent(pontual=True, audio_for_text=False, audio_for_media=False),
               mensagem="manda em texto dessa vez")
    r["save"].assert_not_called()
    r["chat"].assert_not_called()
    r["tts"].assert_not_called()
    assert "em texto dessa vez:" in r["enviado"]


@pytest.mark.unit
def test_sem_pedido_pontual_o_formato_gravado_vale():
    r = _texto({"audio_for_text": True}, {"intent": "message"}, mensagem="o dólar subiu?")
    r["tts"].assert_called_once()


@pytest.mark.unit
def test_pontual_com_pergunta_por_audio_responde_em_texto():
    payload = {"data": {"key": {"fromMe": False, "remoteJid": "553499930185@lid"},
                        "pushName": "Ricardim", "message": {"audioMessage": {"seconds": 3}}}}
    with patch("backend.api.main.supabase.get_authorized", return_value=AUTHORIZED), \
         patch("backend.api.main.supabase.get_preferences", return_value=_TUDO_EM_AUDIO), \
         patch("backend.api.main.supabase.get_history", return_value=[]), \
         patch("backend.api.main.supabase.get_summary", return_value=None), \
         patch("backend.api.main.supabase.save_message"), \
         patch("backend.api.main._maybe_summarize"), \
         patch("backend.api.main.whatsapp.download_media", return_value={"base64": "x"}), \
         patch("backend.api.main.media_service.transcribe_audio",
               return_value="responde em texto dessa vez, como tá a soja?"), \
         patch("backend.api.main._detect_preference_intent",
               return_value=_intent(pontual=True, pergunta_junto=True,
                                    audio_for_text=False, audio_for_media=False)), \
         patch("backend.api.main.supabase.save_preferences") as mock_save, \
         patch("backend.api.main.reporter.generate_report", return_value="Soja estável."), \
         patch("backend.api.main.media_service.text_to_speech", return_value=b"mp3") as mock_tts, \
         patch("backend.api.main.whatsapp.send_audio"), \
         patch("backend.api.main.whatsapp.send_message") as mock_send:
        TestClient(app).post("/api/webhook", json=payload)
    mock_save.assert_not_called()
    mock_tts.assert_not_called()
    assert mock_send.call_args.args[1] == "Soja estável."


# ── Haiku DE VERDADE (custa crédito, fora do CI) ──────────────────────────────

@pytest.mark.smoke
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="precisa de ANTHROPIC_API_KEY")
@pytest.mark.parametrize("frase,formato", [
    ("manda em texto dessa vez, como tá o dólar?", "texto"),
    ("tô em reunião, responde por escrito: a selic caiu?", "texto"),
    ("dessa vez em áudio: como fechou o ibovespa?", "audio"),
    ("sem áudio dessa vez, o dólar subiu?", "texto"),
])
def test_smoke_pontual_com_pergunta_no_haiku_real(frase, formato):
    r = main._settle_preference(main._detect_preference_intent(frase))
    assert r == {"intent": "message", "_formato_unico": formato}


@pytest.mark.smoke
@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="precisa de ANTHROPIC_API_KEY")
@pytest.mark.parametrize("frase", [
    "fala mais devagar só nessa: o que é Selic?",
    "só dessa vez com a voz echo: como tá o bitcoin?",
    "só hoje me manda só o mercado",
    "dessa vez manda o relatório às 18h",
])
def test_smoke_pontual_sem_formato_e_respondido_no_haiku_real(frase):
    """Os casos da 7ª revisão do Apolo — a medição de 56/56 não tinha nenhum deles."""
    r = main._settle_preference(main._detect_preference_intent(frase))
    assert r == {"intent": "message"}


@pytest.mark.unit
def test_pedido_misto_avisa_que_a_voz_nao_foi_trocada():
    r = main._settle_preference(_intent(pontual=True, tts_voice="onyx",
                                        audio_for_text=False, audio_for_media=False))
    assert r["_gravar"] == {}
    assert "A voz eu não troquei" in main._preference_reply(r, AUTHORIZED)
