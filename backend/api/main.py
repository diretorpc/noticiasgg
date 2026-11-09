import json
import os
import re
import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic

from backend.collectors import market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, agro_br, esalq, eia, soja_disponivel
from backend.services import reporter, whatsapp, supabase, health, selflink
from backend.services import media as media_service
from backend.services.secrets_mask import sanitize_error
from backend.api import send_report, cron_report, check_alerts, admin, me, health_digest, cron_investing, cron_soja

logger = logging.getLogger("noticiasgg")
logging.basicConfig(level=logging.INFO)
# httpx loga a URL completa (com api_key=... em query string) no nível INFO;
# silenciar evita vazar chaves (ScraperAPI, FRED, EIA, NewsAPI) nos logs da Vercel
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="noticiasgg", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(crypto.router)
app.include_router(indicators_us.router)
app.include_router(indicators_br.router)
app.include_router(news.router)
app.include_router(commodities_br.router)
app.include_router(politics_br.router)
app.include_router(agro_br.router)
app.include_router(send_report.router)
app.include_router(cron_report.router)
app.include_router(check_alerts.router)
app.include_router(esalq.router)
app.include_router(eia.router)
app.include_router(soja_disponivel.router)
app.include_router(admin.router)
app.include_router(me.router)
app.include_router(health_digest.router)
app.include_router(cron_investing.router)
app.include_router(cron_soja.router)


PHONE_RE = re.compile(r"^\D*(\d{10,13})\D*$")


@app.head("/api/health")
async def health_head():
    from fastapi.responses import Response
    return Response(status_code=200)


@app.get("/api/health")
async def health_endpoint():
    return health.collect_status()


def _extract_message(message: dict) -> dict:
    """Detecta o tipo da mensagem e retorna metadados para o webhook processar.

    Retornos possíveis:
      {"type": "text", "text": str}
      {"type": "audio"}
      {"type": "image", "caption": str}
      {"type": "document", "caption": str, "filename": str, "mime": str}
      {"type": "unknown"}
    """
    text = message.get("conversation") or message.get("extendedTextMessage", {}).get("text")
    if text:
        return {"type": "text", "text": text}
    if message.get("audioMessage") or message.get("pttMessage"):
        return {"type": "audio"}
    if message.get("imageMessage"):
        caption = message["imageMessage"].get("caption", "")
        return {"type": "image", "caption": caption}
    if message.get("documentMessage"):
        doc = message["documentMessage"]
        return {
            "type": "document",
            "caption": doc.get("caption", ""),
            "filename": doc.get("fileName", "arquivo"),
            "mime": doc.get("mimetype", "application/octet-stream"),
        }
    if message.get("documentWithCaptionMessage"):
        inner = message["documentWithCaptionMessage"].get("message", {}).get("documentMessage", {})
        return {
            "type": "document",
            "caption": inner.get("caption", ""),
            "filename": inner.get("fileName", "arquivo"),
            "mime": inner.get("mimetype", "application/octet-stream"),
        }
    return {"type": "unknown"}


def _extract_quoted_message_id(data: dict) -> str | None:
    """Id da mensagem CITADA quando o usuário responde com "Responder" no
    WhatsApp (sessão 'noticias-ancoradas', Parte C, 18/08/2026).

    Medido AO VIVO em 18/08/2026 (mensagem de teste enviada, respondida com
    "Responder" pelo dono): para texto simples (`messageType` "conversation")
    o `contextInfo` mora no TOPO do registro — irmão de `message`, NÃO dentro
    dele. `data.get("contextInfo")` é a primeira tentativa por ser a que foi
    OBSERVADA; `message.extendedTextMessage.contextInfo` é a segunda porque o
    formato pode variar por tipo de mensagem (não foi o que apareceu na
    medição, mas é o caminho sugerido pela forma como a Evolution documenta
    outros campos aninhados)."""
    stanza_id = (data.get("contextInfo") or {}).get("stanzaId")
    if stanza_id:
        return stanza_id
    message = data.get("message", {}) or {}
    ext = message.get("extendedTextMessage", {}) or {}
    return (ext.get("contextInfo") or {}).get("stanzaId")


def _admin_phone() -> str:
    return os.environ.get("REPLY_TO_NUMBER", "")


def _handle_admin_command(text: str) -> str | None:
    """Comandos do admin para autorizar pendentes. Retorna mensagem de status ou None."""
    stripped = text.strip()

    if stripped.lower() == "/pendentes":
        with supabase._client() as c:
            r = c.get("/pending_auth?select=*&order=created_at.asc")
            r.raise_for_status()
            pending = r.json()
        if not pending:
            return "Nenhum pedido pendente."
        lines = [f"{i+1}. {p['push_name']} (LID {p['lid'][:12]}...): \"{p['last_message'][:50]}\"" for i, p in enumerate(pending)]
        return "*Pedidos pendentes:*\n" + "\n".join(lines) + "\n\nResponda com o número da pessoa (ex: 5534999999999) para autorizar o mais antigo."

    m = PHONE_RE.match(stripped)
    if m:
        phone = m.group(1)
        pending = supabase.pop_oldest_pending()
        if not pending:
            return None  # número solto sem pendência — trata como mensagem normal
        supabase.add_authorized(pending["lid"], phone, pending["push_name"])
        whatsapp.send_message(pending["lid"], "Olá! Você foi autorizado a conversar com o agente Notícias GG. Pode mandar suas perguntas sobre mercado, cotações e notícias financeiras.")
        return f"Autorizado: {pending['push_name']} → {phone}"

    return None


# Comandos de velocidade/voz só valem quando a mensagem INTEIRA é o comando (fullmatch).
# A versão antiga procurava palavras soltas em qualquer lugar e engolia pergunta de
# mercado — 12 de 12 medidas em 09/11/2026: "a inflação acelera em outubro?" mudava a
# velocidade, "qual a nova voz da oposição?" trocava a voz, "o que as vozes do mercado
# dizem?" devolvia a lista. Frase com mais coisa vai ao Haiku, que lê o sentido.
_CMD_PREFIXO = r"(?:(?:ei|oi|agora|por\s+favor|pfv)[\s,]+)?"
_CMD_SUFIXO = r"(?:[\s,]+(?:por\s+favor|pfv|pls|please|a[ií]))*"
_FALA = r"(?:fala|fale|falar)"
_MUITO = r"(?:bem|muito|bastante)"
_DEVAGAR = r"(?:devagar|lento|pausado)"
_RAPIDO = r"(?:r[áa]pido|veloz|acelerado)"
_NOMES_VOZ = r"(alloy|echo|fable|nova|onyx|shimmer)"


def _comando(nucleo: str) -> re.Pattern:
    return re.compile(f"{_CMD_PREFIXO}(?:{nucleo}){_CMD_SUFIXO}", re.IGNORECASE)


_TTS_SPEED_BIG_DOWN_RE = _comando(rf"(?:{_FALA}\s+)?{_MUITO}\s+mais\s+{_DEVAGAR}")
_TTS_SPEED_SMALL_DOWN_RE = _comando(
    rf"(?:{_FALA}\s+)?(?:um\s+pouco\s+)?mais\s+{_DEVAGAR}|{_FALA}\s+{_DEVAGAR}"
    r"|velocidade\s+mais\s+(?:baixa|lenta)|diminui\s+a\s+velocidade")
_TTS_SPEED_BIG_UP_RE = _comando(
    rf"(?:{_FALA}\s+)?{_MUITO}\s+mais\s+{_RAPIDO}|velocidade\s+{_MUITO}\s+mais\s+(?:alta|r[áa]pida)")
_TTS_SPEED_SMALL_UP_RE = _comando(
    rf"(?:{_FALA}\s+)?(?:um\s+pouco\s+)?mais\s+{_RAPIDO}|{_FALA}\s+{_RAPIDO}|acelera"
    r"|velocidade\s+mais\s+(?:alta|r[áa]pida)|aumenta\s+a\s+velocidade")
_TTS_SPEED_NORMAL_RE = _comando(
    r"velocidade\s+(?:normal|padr[ãa]o|original|default)"
    r"|volta\s+(?:a\s+|pra\s+|para\s+)?(?:a\s+)?velocidade(?:\s+(?:normal|padr[ãa]o|original))?")
# "voz" é obrigatória: "nova" sozinha é palavra comum, e "quero uma voz nova" é pedir
# OUTRA voz, não a chamada "nova" (que já é a padrão) — esse vai ao Haiku.
_TTS_VOICE_RE = _comando(
    r"(?:(?:muda|mudar|troca|trocar|usa|usar|quero|coloca|bota|testa|ativa)\s+(?:a\s+)?)?"
    rf"voz\s+(?:para\s+|pra\s+)?(?:a\s+)?{_NOMES_VOZ}|{_NOMES_VOZ}\s+(?:voz|voice)")
_TTS_LIST_VOICES_RE = _comando(
    r"(?:quais|que)\s+(?:s[ãa]o\s+)?(?:as\s+)?vozes"
    r"(?:\s+(?:tem|t[êe]m|h[áa]|existem|dispon[íi]veis|posso\s+escolher))?"
    r"|(?:lista|listar|mostra|mostre|mostrar|ver|quero\s+ver)\s+(?:as\s+)?vozes(?:\s+dispon[íi]veis)?"
    r"|vozes(?:\s+dispon[íi]veis)?|op[çc][õo]es\s+de\s+voz")

_VOICES_LIST_REPLY = (
    "🎙 *Vozes disponíveis:*\n"
    "• *nova* — feminina, suave (padrão)\n"
    "• *shimmer* — feminina, expressiva\n"
    "• *alloy* — neutra\n"
    "• *echo* — masculina\n"
    "• *fable* — expressiva\n"
    "• *onyx* — grave\n\n"
    "Para mudar: \"muda a voz para onyx\""
)


def _quick_tts_check(text: str, current_speed: float = 0.85) -> dict | None:
    """Pré-check determinístico para comandos de velocidade e voz TTS — só quando a
    mensagem inteira é o comando (ver `_comando`)."""
    base = {"intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": None, "audio_for_media": None, "reset": False,
            "list_voices": False}
    # `rstrip`, não `re.sub(...+$)`: a regex era quadrática — 65 mil caracteres de
    # pontuação seguidos de uma letra levavam 10,66 s (achado 1, 7ª revisão do Apolo).
    # O `?` NÃO sai: "mais rápido?" no meio de uma conversa é pergunta, vai ao Haiku.
    # Só a lista de vozes aceita o `?` ("quais vozes tem?").
    text = re.sub(r"\s+", " ", text.strip()).rstrip(" .!…")

    if _TTS_LIST_VOICES_RE.fullmatch(text.rstrip(" ?")):
        return {**base, "list_voices": True, "tts_voice": None, "tts_speed": None, "reply": _VOICES_LIST_REPLY}

    voice_match = _TTS_VOICE_RE.fullmatch(text)
    if voice_match:
        # Extrai o nome da voz de qualquer grupo que tenha capturado
        voice = next((g for g in voice_match.groups() if g and g.lower() in ("alloy", "echo", "fable", "nova", "onyx", "shimmer")), None)
        if voice:
            return {**base, "tts_voice": voice.lower(), "tts_speed": None, "reply": f"Voz alterada para *{voice.lower()}*."}

    if _TTS_SPEED_BIG_DOWN_RE.fullmatch(text):
        new_speed = round(max(0.5, current_speed - 0.15), 2)
        return {**base, "tts_voice": None, "tts_speed": new_speed, "reply": f"Falando mais devagar agora (velocidade: {new_speed})."}

    if _TTS_SPEED_SMALL_DOWN_RE.fullmatch(text):
        new_speed = round(max(0.5, current_speed - 0.07), 2)
        return {**base, "tts_voice": None, "tts_speed": new_speed, "reply": f"Um pouco mais devagar (velocidade: {new_speed})."}

    if _TTS_SPEED_BIG_UP_RE.fullmatch(text):
        new_speed = round(min(1.5, current_speed + 0.15), 2)
        return {**base, "tts_voice": None, "tts_speed": new_speed, "reply": f"Falando mais rápido agora (velocidade: {new_speed})."}

    if _TTS_SPEED_SMALL_UP_RE.fullmatch(text):
        new_speed = round(min(1.5, current_speed + 0.07), 2)
        return {**base, "tts_voice": None, "tts_speed": new_speed, "reply": f"Um pouco mais rápido (velocidade: {new_speed})."}

    if _TTS_SPEED_NORMAL_RE.fullmatch(text):
        return {**base, "tts_voice": None, "tts_speed": 0.95, "reply": "Velocidade normal (0.95)."}

    return None


# Não há mais pré-check de ÁUDIO por regex: `_quick_audio_check` LIGAVA o áudio em
# "não quero áudio", "sem áudio por favor", "prefere uma voz masculina" (13/20 numa
# amostra de 09/11/2026). Ele existia para cobrir "falsos negativos do LLM" — que eram,
# na verdade, a cerca de código descartando 100% das respostas do Haiku. Consertada a
# cerca, o Haiku acertou 20/20 nas mesmas frases. O de velocidade/voz acima fica:
# acerta, e faz a conta da velocidade sem depender do modelo.


_PREFERENCE_SYSTEM = """Você é um parser de intenções. Analise a mensagem e classifique em uma de duas categorias.

CATEGORIA 1 — Pedido de configuração do relatório diário ou preferências de resposta:
Seções disponíveis e seus aliases em português:
- market → bolsas, ações, mercado, índices, ibovespa, nasdaq, s&p
- crypto → cripto, criptomoedas, bitcoin, btc, ethereum
- indicators_us → indicadores eua, indicadores americanos, fed, cpi, juros eua
- indicators_br → indicadores br, indicadores brasil, selic, ipca, juros brasil
- news → notícias, news, manchetes
- commodities_br → commodities, soja, milho, petróleo, agro commodities
- politics_br → política, política brasil, notícias políticas

Responda SOMENTE com JSON:
{
  "intent": "preference",
  "sections": {todas as 7 seções com true/false} ou null se não mencionado,
  "report_time": "HH:00" ou null,
  "audio_for_text": true/false ou null se não mencionado,
  "audio_for_media": true/false ou null se não mencionado,
  "tts_voice": "nome_da_voz" ou null se não mencionado,
  "tts_speed": 0.00 ou null se não mencionado,
  "list_voices": false,
  "reset": false,
  "reply": "confirmação direta, sem bajulação"
}

Regras de seções:
- "quero só X e Y" → todas false exceto X e Y
- "salve apenas X" ou "somente X" → todas false exceto X
- "remove X" → apenas X=false (manter restante do contexto atual)
- "adiciona X" → apenas X=true (manter restante do contexto atual)

Regras de horário:
- "às 8h" → "08:00"
- "às 20h30" ou "8 e meia" → arredondar para próxima hora cheia

Regras de áudio — dois campos independentes (audio_for_text e audio_for_media):
- "tudo em áudio", "quero resposta em áudio", "ativa áudio" → audio_for_text: true, audio_for_media: true
- "textos em áudio", "responde meus textos em áudio" → audio_for_text: true, audio_for_media: null
- "imagens em áudio", "fotos em áudio", "documentos em áudio", "mídias em áudio" → audio_for_text: null, audio_for_media: true
- "desativa áudio", "tudo em texto", "modo texto" → audio_for_text: false, audio_for_media: false
- "textos em texto", "desativa áudio nos textos" → audio_for_text: false, audio_for_media: null
- "imagens em texto", "fotos em texto", "mídias em texto" → audio_for_text: null, audio_for_media: false
- Se não mencionado → audio_for_text: null, audio_for_media: null

Regras de voz TTS (tts_voice):
- "muda a voz para X", "quero a voz X", "usa a voz X", "voz X" → tts_voice: "X"
- Vozes válidas: alloy, echo, fable, nova, onyx, shimmer. Ignorar se não for uma dessas.
- Voz descrita ("voz masculina" → echo, "mais grave" → onyx, "feminina" → shimmer) → a da lista abaixo que bate.
- Pedido de OUTRA voz sem dizer qual nem descrever ("quero uma voz nova", "outra voz", "troca a voz") → tts_voice: null e list_voices: true. "nova" só é a voz quando usada como NOME ("usa a voz nova").
- Se não mencionado → tts_voice: null

Regras de velocidade TTS (tts_speed):
- ATENÇÃO: pedido de velocidade da FALA ("rápido", "devagar", "veloz", "lento") é tts_speed, nunca audio_for_text.
- Mas se a mensagem pergunta CONTEÚDO (mercado, preço, notícia, explicação), é CATEGORIA 2, mesmo com essas palavras: "me fala rápido: o dólar subiu?", "fala devagar que eu sou leigo, o que é Selic?", "a inflação acelera?".
- A velocidade atual está no contexto como "velocidade_atual: X.XX"
- "fala mais devagar", "fale mais devagar", "um pouco mais devagar", "velocidade mais baixa" → tts_speed: max(0.5, velocidade_atual - 0.07), 2 casas decimais
- "fala bem mais devagar", "muito mais devagar", "bem mais lento" → tts_speed: max(0.5, velocidade_atual - 0.15), 2 casas decimais
- "fala mais rápido", "fale mais rápido", "um pouco mais rápido", "velocidade mais alta" → tts_speed: min(1.5, velocidade_atual + 0.07), 2 casas decimais
- "fala bem mais rápido", "muito mais rápido", "bem mais rápido" → tts_speed: min(1.5, velocidade_atual + 0.15), 2 casas decimais
- "velocidade normal", "velocidade padrão", "velocidade original" → tts_speed: 0.95
- Se não mencionado → tts_speed: null

Listagem de vozes:
- "quais vozes têm?", "lista as vozes", "mostra as vozes", "que vozes existem", "opções de voz" → list_voices: true
- Nesse caso, reply deve ser EXATAMENTE:
  "🎙 *Vozes disponíveis:*\n• *nova* — feminina, suave (padrão)\n• *shimmer* — feminina, expressiva\n• *alloy* — neutra\n• *echo* — masculina\n• *fable* — expressiva\n• *onyx* — grave\n\nPara mudar: \"muda a voz para onyx\""
- Se não mencionado → list_voices: false

Reset: "volta pro padrão", "quero tudo de volta", "cancela preferências" → {"intent": "preference", "sections": null, "report_time": null, "audio_for_text": null, "audio_for_media": null, "tts_voice": null, "tts_speed": null, "list_voices": false, "reset": true, "reply": "Preferências resetadas."}

CATEGORIA 2 — Qualquer outra mensagem:
Responda SOMENTE com JSON: {"intent": "message"}"""

_SECTION_LABELS: dict[str, str] = {
    "market": "mercado",
    "crypto": "cripto",
    "indicators_us": "indicadores EUA",
    "indicators_br": "indicadores BR",
    "news": "notícias",
    "commodities_br": "commodities",
    "politics_br": "política",
}


def _build_settings_summary(prefs: dict | None) -> str:
    p = prefs or {}
    audio_text = "sim" if p.get("audio_for_text") else "não"
    audio_media = "sim" if p.get("audio_for_media") else "não"
    voice = p.get("tts_voice") or "nova"
    speed = p.get("tts_speed") or 0.85
    report_time = p.get("report_time") or "não configurado"
    sections = p.get("sections") or {}
    # Só seções que ainda existem: preferência salva pode guardar chave aposentada
    # (`polls_br`, removida em 11/2026 depois das eleições) e ela não pode aparecer crua.
    active = [_SECTION_LABELS[k] for k, v in sections.items() if v and k in _SECTION_LABELS] if sections else list(_SECTION_LABELS.values())
    sections_str = ", ".join(active) if active else "nenhuma"
    return (
        "⚙️ *Suas configurações*\n\n"
        "*Áudio*\n"
        f"• Textos em áudio: {audio_text}\n"
        f"• Mídias em áudio: {audio_media}\n"
        f"• Voz: {voice}\n"
        f"• Velocidade: {speed}\n\n"
        "*Relatório diário*\n"
        f"• Horário: {report_time}\n"
        f"• Seções ativas: {sections_str}\n\n"
        "Para alterar: \"muda a voz para onyx\", \"fala mais devagar\", \"ativa áudio\", etc."
    )


_SUMMARY_THRESHOLD = 20
_KEEP_RECENT = 6


def _build_history_with_summary(history: list[dict], summary: str | None) -> list[dict]:
    raw = [{"role": h["role"], "content": h["content"]} for h in history]
    if not summary:
        return raw
    return [
        {"role": "user", "content": f"[CONTEXTO DA CONVERSA ANTERIOR]\n{summary}"},
        {"role": "assistant", "content": "Entendido."},
        *raw,
    ]


def _maybe_summarize(phone: str) -> None:
    """Sumariza e comprime histórico quando ultrapassa o limite."""
    try:
        total = supabase.count_history(phone)
        if total <= _SUMMARY_THRESHOLD:
            return
        antigas = supabase.get_history_for_summary(
            phone, keep_recent=_KEEP_RECENT, limit=50, total=total)
        if not antigas:
            return
        from backend.services import summarizer
        existing = supabase.get_summary(phone)
        msgs = [{"role": m["role"], "content": m["content"]} for m in antigas]
        novo = summarizer.summarize(msgs, existing)
        if not novo:
            # Falha do Haiku não pode custar histórico. Sem resumo novo, nada é
            # apagado e o próximo turno tenta de novo.
            logger.warning("resumo falhou para %s — histórico preservado", phone)
            return
        supabase.save_summary(phone, novo)
        # Corte exato: só o que entrou no resumo.
        supabase.delete_history_until(phone, antigas[-1]["created_at"])
    except Exception:
        logger.warning("summarization failed for %s", phone, exc_info=True)


def _known_sections(sections: dict | None) -> dict | None:
    """Só as seções que existem hoje. Preferência gravada guarda chave aposentada
    (`polls_br`, 11/2026) e o painel a regrava inteira a cada save. Com ela no
    contexto, o Haiku zerou TODAS as seções em 5 de 8 pedidos de "remove cripto"
    (medido pelo Apolo com chamada real) — então ela não entra no modelo nem volta
    dele para o banco."""
    if sections is None:
        return None
    # `or None`: sobrando nada, `{}` gravado APAGARIA as seções escolhidas; `None`
    # é "não mexe" para `save_preferences` (achado 1, 2ª revisão do Apolo).
    return {k: v for k, v in sections.items() if k in reporter.ALL_SECTIONS} or None


def _base_sections(current: dict | None) -> dict:
    """As seções valendo agora, só as conhecidas. Sem preferência gravada é o padrão
    (tudo ligado), o mesmo que `reporter._collect_all` usa quando `sections` é None.
    Fonte única para o que o Haiku VÊ e para a base do que se GRAVA — se as duas
    discordassem, o modelo decidiria sobre uma lista e o banco receberia outra."""
    if current is None:
        return {s: True for s in reporter.ALL_SECTIONS}
    return {k: v for k, v in current.items() if k in reporter.ALL_SECTIONS}


_AUDIO_FIELDS = ("audio_for_text", "audio_for_media", "tts_voice", "tts_speed")
_TTS_VOICES = ("alloy", "echo", "fable", "nova", "onyx", "shimmer")


def _valid_audio_field(campo: str, valor) -> bool:
    """O que o Haiku manda gravar passa por aqui. `tts_speed` gravado como texto fazia
    `float()` estourar em TODA mensagem seguinte do usuário ("Tive um problema" até
    limpar o banco), e voz fora da lista virava "Voz alterada" com TTS caindo calado
    (achado 3, 4ª revisão do Apolo). `bool` antes de número: `True` é `int` em Python."""
    if valor is None:
        return False
    if campo in ("audio_for_text", "audio_for_media"):
        return isinstance(valor, bool)
    if campo == "tts_voice":
        return valor in _TTS_VOICES
    if campo == "tts_speed":
        return (isinstance(valor, (int, float)) and not isinstance(valor, bool)
                and 0.5 <= valor <= 1.5)
    return False


def _settle_preference(intent: dict) -> dict:
    """Decide o que um pedido de preferência FAZ de verdade, antes de responder.

    Seções e horário do relatório NÃO se gravam pelo WhatsApp: `user_preferences.
    sections`/`report_time` não são lidos por nada que entrega mensagem — o relatório
    sai da grade `report_schedules` (`cron_report.py`), o chat usa `sections={}`, e o
    único leitor era `send_report.py` (rota do n8n, desligado). Gravar ali e responder
    "agendado para 18h" é confirmar o que não acontece (3ª revisão do Apolo,
    09/11/2026; decisão do Matheus: mandar para o /me).

    Sem nada a gravar, sem reset e sem lista de vozes, o pedido vira CONVERSA — mesmo
    quando fala de seção/horário. O Haiku real respondeu "Relatório diário desativado"
    sem campo nenhum por trás, e leu "quero saber só do mercado hoje" como configuração;
    um aviso fixo ali engolia a pergunta. O chat responde a informação e, pela regra de
    `reporter._REPORT_RULES`, aponta o /me quando é mesmo pedido de relatório."""
    if intent.get("intent") != "preference":
        return intent
    gravar = {k: intent.get(k) for k in _AUDIO_FIELDS if _valid_audio_field(k, intent.get(k))}
    if not (gravar or intent.get("reset") or intent.get("list_voices")):
        return {"intent": "message"}
    quer_relatorio = (_known_sections(intent.get("sections")) is not None
                      or intent.get("report_time") is not None)
    return {**intent, "_gravar": gravar, "_quer_relatorio": quer_relatorio}


def _preference_reply(intent: dict, user: dict | None) -> str:
    """Resposta de um pedido já decidido por `_settle_preference`. O `reply` do Haiku só
    sai quando ele descreve exatamente o que foi gravado.

    - Reset: apaga voz/áudio, NÃO a grade. Haiku real, 3 de 3: "volta o relatório pro
      padrão" → `reset: true` + "Preferências resetadas." — o usuário entendia que o
      relatório tinha voltado (achado 1, 4ª revisão do Apolo).
    - Pedido MISTO (voz/áudio + seção/horário): o `reply` confirmaria as duas coisas,
      e só uma aconteceu."""
    onde = selflink.onde_ajustar(selflink.panel_link(user))
    if intent.get("reset"):
        return f"Voz e áudio voltaram ao padrão. Seções e horário do relatório diário se ajustam {onde}"
    if intent["_quer_relatorio"]:
        prefixo = "Ajustei a voz/áudio. " if intent["_gravar"] else ""
        return f"{prefixo}Seções e horário do relatório diário eu não mudo por aqui: ajuste {onde}"
    return intent.get("reply", "Preferências atualizadas!")


def _link_for_model(user: dict | None) -> str | None:
    """O modelo recebe o MARCADOR, nunca o token — ver `selflink.LINK_PLACEHOLDER`."""
    return selflink.LINK_PLACEHOLDER if selflink.panel_link(user) else None


_CERCA_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _parse_json_reply(text: str) -> dict:
    """JSON do Haiku, com ou sem cerca de código. Medido em 09/11/2026: 29 de 29
    respostas vieram como ```json ... ```, e o `json.loads` direto descartava todas.
    Último recurso: o trecho entre a primeira `{` e a última `}`."""
    limpo = _CERCA_RE.sub("", text.strip())
    try:
        return json.loads(limpo)
    except ValueError:
        inicio, fim = limpo.find("{"), limpo.rfind("}")
        if inicio == -1 or fim <= inicio:
            raise
        return json.loads(limpo[inicio:fim + 1])


def _detect_preference_intent(text: str, current_sections: dict | None = None, tts_speed: float = 0.85) -> dict:
    # SEMPRE com `seções_atuais`, inclusive para quem nunca salvou preferência: sem
    # ela o Haiku real devolveu `sections: null` com "Criptomoedas removidas" em 3 de 3
    # pedidos — confirmava ao usuário uma mudança que não foi gravada (09/11/2026).
    atuais = _base_sections(current_sections)
    context = f"\nvelocidade_atual: {tts_speed:.2f}"
    context += f"\nseções_atuais: {json.dumps(atuais, ensure_ascii=False)}"
    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_PREFERENCE_SYSTEM,
            messages=[{"role": "user", "content": text + context}],
        )
        intent = _parse_json_reply(response.content[0].text)
        if not isinstance(intent, dict):
            raise ValueError(f"esperava objeto JSON, veio {type(intent).__name__}")
        return intent
    except Exception as e:
        # Calado, este `except` escondeu que NENHUM pedido de preferência
        # por texto era salvo. Cair para conversa continua certo; sumir sem rastro, não.
        logger.warning("leitor de preferências falhou, tratando como conversa: %s",
                       sanitize_error(e))
        return {"intent": "message"}


def _webhook_authorized(request: Request) -> bool:
    """Verifica a origem do webhook. Opt-in: só exige segredo quando
    WEBHOOK_SECRET está configurado. Aceita via header `x-webhook-secret`
    ou query param `token` (a URL do webhook na Evolution é fixa)."""
    import hmac
    secret = os.environ.get("WEBHOOK_SECRET")
    if not secret:
        return True  # não configurado → comportamento legado (sem verificação)
    provided = request.headers.get("x-webhook-secret") or request.query_params.get("token", "")
    return bool(provided) and hmac.compare_digest(provided, secret)


@app.post("/api/webhook")
async def whatsapp_webhook(request: Request):
    if not _webhook_authorized(request):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"status": "error", "detail": "unauthorized"})
    payload = await request.json()
    logger.info(f"webhook payload: {payload}")

    remote_jid = ""  # definido aqui para o handler de erro saber a quem responder
    try:
        data = payload.get("data", {})
        key = data.get("key", {})
        if key.get("fromMe"):
            return {"status": "ignored", "reason": "fromMe"}

        # A Evolution reenvia a mesma mensagem (mesmo id) a cada ~65s quando o
        # webhook demora — sem esta trava o agente responde do zero a cada
        # reenvio. Reserva a etiqueta no início; reenvio bate no conflito e para.
        msg_id = key.get("id", "")
        if msg_id:
            try:
                is_new_message = supabase.claim_message(msg_id)
            except Exception:
                logger.warning("dedup: claim falhou para %s — processando mesmo assim", msg_id)
                is_new_message = True
            if not is_new_message:
                logger.info("dedup: mensagem %s já processada — ignorando reenvio", msg_id)
                return {"status": "ignored", "reason": "duplicate"}

        remote_jid = key.get("remoteJid", "")
        push_name = data.get("pushName", "")
        msg_info = _extract_message(data.get("message", {}))
        if msg_info["type"] == "unknown":
            return {"status": "ignored", "reason": "unsupported media type"}
        # Para texto usa o conteúdo direto; para mídia o texto é extraído depois da transcrição/análise
        text = msg_info.get("text", "") if msg_info["type"] == "text" else "[mídia]"

        admin_phone = _admin_phone()
        # O remoteJid muda de formato entre versões da Evolution (v1: @lid,
        # v2: @s.whatsapp.net) — resolve nas duas grafias.
        authorized = supabase.get_authorized_by_jid(remote_jid)

        if not authorized:
            # Não autorizado → cria pendência e notifica admin
            supabase.upsert_pending(remote_jid, push_name, text)
            if admin_phone:
                try:
                    whatsapp.send_message(
                        admin_phone,
                        f"Novo pedido de acesso:\n\n*{push_name}* mandou: \"{text}\"\n\nResponda com o número da pessoa (ex: 5534999999999) para autorizar.",
                    )
                except Exception:
                    logger.warning("failed to notify admin for pending user %s", remote_jid)
            try:
                whatsapp.send_message(
                    remote_jid,
                    "Vou enviar uma mensagem para o admin liberar o seu acesso, só um momento! 🙏",
                )
            except Exception:
                logger.warning("failed to notify pending user %s", remote_jid)
            return {"status": "ok", "reason": "pending auth"}

        target_phone = authorized["phone"]
        target_jid = remote_jid
        is_admin = target_phone == admin_phone

        if is_admin:
            admin_response = _handle_admin_command(text)
            if admin_response is not None:
                whatsapp.send_message(admin_phone, admin_response)
                return {"status": "ok", "reason": "admin command"}

        # Carregar preferências e extrair parâmetros TTS
        current_prefs = supabase.get_preferences(target_phone)
        current_sections = current_prefs.get("sections") if current_prefs else None
        tts_voice = (current_prefs or {}).get("tts_voice") or "nova"
        tts_speed = float((current_prefs or {}).get("tts_speed") or 0.85)

        # Comando !ajustes — sempre em texto para o usuário ver as configurações claramente
        if msg_info["type"] == "text" and text.strip().lower() == "!ajustes":
            whatsapp.send_message(target_phone, _build_settings_summary(current_prefs))
            return {"status": "ok"}

        # Detectar intenção de preferência — apenas para mensagens de texto
        # Velocidade/voz por regex primeiro (determinístico, faz a conta da velocidade);
        # o resto — áudio liga/desliga, reset, voz por descrição — decide o Haiku.
        intent = (
            (_quick_tts_check(text, tts_speed) or _detect_preference_intent(text, current_sections=current_sections, tts_speed=tts_speed))
            if msg_info["type"] == "text"
            else {"intent": "message"}
        )

        intent = _settle_preference(intent)
        if intent.get("intent") == "preference":
            gravar = intent["_gravar"]
            if intent.get("reset"):
                supabase.delete_preferences(target_phone)
            elif gravar:
                supabase.save_preferences(
                    target_phone,
                    sections=None,
                    report_time=None,
                    audio_for_text=gravar.get("audio_for_text"),
                    audio_for_media=gravar.get("audio_for_media"),
                    tts_voice=gravar.get("tts_voice"),
                    tts_speed=gravar.get("tts_speed"),
                )
                if gravar.get("tts_voice"):
                    tts_voice = gravar["tts_voice"]
                if gravar.get("tts_speed") is not None:
                    tts_speed = gravar["tts_speed"]
            reply = _preference_reply(intent, authorized)
            # list_voices nunca é enviado como áudio — é uma lista visual
            if (not intent.get("list_voices") and not selflink.has_link(reply)
                    and bool((current_prefs or {}).get("audio_for_text", False))):
                try:
                    whatsapp.send_audio(target_phone, media_service.text_to_speech(reply, voice=tts_voice, speed=tts_speed))
                    return {"status": "ok", "reason": "preference_updated"}
                except Exception:
                    pass
            whatsapp.send_message(target_phone, reply)
            return {"status": "ok", "reason": "preference_updated"}

        # Buscar histórico com resumo comprimido
        history = supabase.get_history(target_phone, limit=_KEEP_RECENT)
        summary = supabase.get_summary(target_phone)
        anthropic_history = _build_history_with_summary(history, summary)
        audio_for_text = bool((current_prefs or {}).get("audio_for_text", False))
        audio_for_media = bool((current_prefs or {}).get("audio_for_media", False))

        # ── Áudio ──────────────────────────────────────────────────────────────
        if msg_info["type"] == "audio":
            _t = time.monotonic()
            try:
                media = whatsapp.download_media(data)
            except Exception:
                logger.warning("audio: download falhou após %.1fs", time.monotonic() - _t)
                whatsapp.send_message(target_phone, "Não consegui baixar o áudio, tente novamente.")
                return {"status": "ok", "reason": "media_download_failed"}
            logger.info("audio: download %.1fs", time.monotonic() - _t)
            _t = time.monotonic()
            try:
                text = media_service.transcribe_audio(media["base64"], media.get("mimetype", "audio/ogg"))
            except Exception:
                logger.warning("audio: transcrição falhou após %.1fs", time.monotonic() - _t)
                whatsapp.send_message(target_phone, "Não consegui transcrever o áudio.")
                return {"status": "ok", "reason": "transcription_failed"}
            logger.info("audio: transcribe %.1fs", time.monotonic() - _t)

            # Preferência enviada via áudio → detecta e confirma em áudio
            audio_intent = _settle_preference(
                _quick_tts_check(text, tts_speed)
                or _detect_preference_intent(text, current_sections=current_sections, tts_speed=tts_speed))
            if audio_intent.get("intent") == "preference":
                gravar = audio_intent["_gravar"]
                # O reset por áudio nunca apagou nada e mesmo assim respondia
                # "Preferências resetadas" — mesma confirmação vazia do texto.
                if audio_intent.get("reset"):
                    supabase.delete_preferences(target_phone)
                elif gravar:
                    supabase.save_preferences(
                        target_phone,
                        sections=None,
                        report_time=None,
                        audio_for_text=gravar.get("audio_for_text"),
                        audio_for_media=gravar.get("audio_for_media"),
                        tts_voice=gravar.get("tts_voice"),
                        tts_speed=gravar.get("tts_speed"),
                    )
                    if gravar.get("tts_voice"):
                        tts_voice = gravar["tts_voice"]
                    if gravar.get("tts_speed") is not None:
                        tts_speed = gravar["tts_speed"]
                reply = _preference_reply(audio_intent, authorized)
                if selflink.has_link(reply):
                    whatsapp.send_message(target_phone, reply)
                    return {"status": "ok", "reason": "preference_updated"}
                try:
                    audio_bytes = media_service.text_to_speech(reply, voice=tts_voice, speed=tts_speed)
                    whatsapp.send_audio(target_phone, audio_bytes)
                except Exception:
                    whatsapp.send_message(target_phone, reply)
                return {"status": "ok", "reason": "preference_updated"}

            supabase.save_message(target_phone, "user", f"[áudio transcrito] {text}")
            _t = time.monotonic()
            reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"),
                                             sections={}, user_phone=target_phone,
                                             panel_link=_link_for_model(authorized))
            logger.info("audio: report %.1fs", time.monotonic() - _t)
            supabase.save_message(target_phone, "assistant", reply)
            reply = selflink.fill_link(reply, authorized)  # histórico guarda o marcador
            _maybe_summarize(target_phone)

            if audio_for_media and not selflink.has_link(reply):
                try:
                    audio_bytes = media_service.text_to_speech(reply, voice=tts_voice, speed=tts_speed)
                    whatsapp.send_audio(target_phone, audio_bytes)
                    return {"status": "ok"}
                except Exception:
                    pass  # fallback para texto se TTS falhar
            whatsapp.send_message(target_phone, reply)
            return {"status": "ok"}

        # ── Imagem ou Documento ────────────────────────────────────────────────
        if msg_info["type"] in ("image", "document"):
            try:
                media = whatsapp.download_media(data)
            except Exception:
                whatsapp.send_message(target_phone, "Não consegui baixar a mídia, tente novamente.")
                return {"status": "ok", "reason": "media_download_failed"}

            caption = msg_info.get("caption", "")
            mime = media.get("mimetype", "image/jpeg")

            # Limite de tamanho: base64 de 20MB ≈ ~27M chars
            if len(media.get("base64", "")) > 27_000_000:
                whatsapp.send_message(target_phone, "Arquivo muito grande para processar (limite: 20 MB).")
                return {"status": "ok", "reason": "file_too_large"}

            user_text = caption or ("Analise este documento" if msg_info["type"] == "document" else "Analise esta imagem")
            supabase.save_message(target_phone, "user", f"[{msg_info['type']}] {caption}")
            reply = reporter.generate_report(
                user_text,
                history=anthropic_history,
                user_name=authorized.get("name"),
                sections={},
                media_attachment={"type": msg_info["type"], "b64": media["base64"], "mime": mime},
                user_phone=target_phone,
                panel_link=_link_for_model(authorized),
            )
            supabase.save_message(target_phone, "assistant", reply)
            reply = selflink.fill_link(reply, authorized)  # histórico guarda o marcador
            _maybe_summarize(target_phone)
            if audio_for_media and not selflink.has_link(reply):
                try:
                    audio_bytes = media_service.text_to_speech(reply, voice=tts_voice, speed=tts_speed)
                    whatsapp.send_audio(target_phone, audio_bytes)
                    return {"status": "ok"}
                except Exception:
                    pass  # fallback para texto se TTS falhar
            whatsapp.send_message(target_phone, reply)
            return {"status": "ok"}

        # ── Texto (fluxo original) ─────────────────────────────────────────────
        # Resposta citando um alerta de notícia: casa pelo id EXATO da mensagem
        # (contextInfo.stanzaId) — determinístico, não é o modelo escolhendo
        # entre candidatas. Id desconhecido (mensagem não é notícia, ou o
        # registro já foi limpo) devolve None e o fluxo segue igual a antes.
        quoted_message_id = _extract_quoted_message_id(data)
        anchored_news = supabase.get_news_by_message_id(quoted_message_id) if quoted_message_id else None

        supabase.save_message(target_phone, "user", text)
        reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"),
                                         sections={}, anchored_news=anchored_news,
                                         user_phone=target_phone,
                                         panel_link=_link_for_model(authorized))
        supabase.save_message(target_phone, "assistant", reply)
        reply = selflink.fill_link(reply, authorized)  # histórico guarda o marcador
        _maybe_summarize(target_phone)
        if audio_for_text and not selflink.has_link(reply):
            try:
                audio_bytes = media_service.text_to_speech(reply, voice=tts_voice, speed=tts_speed)
                whatsapp.send_audio(target_phone, audio_bytes)
                return {"status": "ok"}
            except Exception:
                pass  # fallback para texto se TTS falhar
        whatsapp.send_message(target_phone, reply)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("webhook error")
        # Sem este aviso o bot simplesmente emudece quando algo falha no meio
        # (ex.: 500 da API do Claude) e o usuário não sabe se espera ou reenvia.
        if remote_jid:
            try:
                whatsapp.send_message(
                    remote_jid,
                    "Tive um problema para gerar sua resposta agora 😕\n\nPode mandar de novo daqui a pouco?",
                )
            except Exception:
                logger.warning("falha ao avisar %s sobre o erro do webhook", remote_jid)
        return {"status": "error", "detail": str(e)}
