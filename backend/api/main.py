import json
import os
import re
import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic

from backend.collectors import market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br, agro_br, esalq, eia
from backend.services import reporter, whatsapp, supabase
from backend.services import media as media_service
from backend.api import send_report, cron_report, check_alerts

logger = logging.getLogger("noticiasgg")
logging.basicConfig(level=logging.INFO)

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
app.include_router(polls_br.router)
app.include_router(agro_br.router)
app.include_router(send_report.router)
app.include_router(cron_report.router)
app.include_router(check_alerts.router)
app.include_router(esalq.router)
app.include_router(eia.router)


PHONE_RE = re.compile(r"^\D*(\d{10,13})\D*$")


@app.head("/api/health")
async def health_head():
    from fastapi.responses import Response
    return Response(status_code=200)


@app.get("/api/health")
async def health():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    checks: dict = {}

    # Chaves configuradas (sem chamadas externas)
    missing_keys = [
        k for k, v in {
            "anthropic": os.getenv("ANTHROPIC_API_KEY"),
            "news_api": os.getenv("NEWS_API_KEY"),
            "scraper_api": os.getenv("SCRAPER_API_KEY"),
            "evolution": os.getenv("EVOLUTION_API_URL"),
            "supabase": os.getenv("SUPABASE_URL"),
            "fred": os.getenv("FRED_API_KEY"),
        }.items() if not v
    ]
    checks["keys"] = {
        "status": "error" if missing_keys else "ok",
        "faltando": missing_keys,
    }

    # Pesquisas eleitorais — lê do cache Supabase (rápido)
    try:
        polls = supabase.get_polls()
        checks["polls"] = {
            "status": "ok" if polls else "warn",
            "institutos": len(polls) if polls else 0,
            "nomes": [p.get("instituto") for p in polls] if polls else [],
        }
    except Exception as e:
        checks["polls"] = {"status": "error", "message": str(e)}

    has_error = any(v.get("status") == "error" for v in checks.values())
    has_warn = any(v.get("status") == "warn" for v in checks.values())
    overall = "error" if has_error else ("warn" if has_warn else "ok")

    return {"status": overall, "checks": checks, "checked_at": now.isoformat()}


@app.post("/api/save-polls")
async def save_polls(request: Request):
    body = await request.json()
    polls = body.get("data", [])
    if polls:
        supabase.save_polls(polls)
    return {"status": "ok", "saved": len(polls)}


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


_VERB_FALA = r"\bfal[ae][r]?\b"  # fala / fale / falar / faler
_TTS_SPEED_BIG_DOWN_RE = re.compile(
    _VERB_FALA + r".{0,10}\b(bem|muito|bastante)\b.{0,10}\b(mais\s+)?(devagar|lento|pausad)",
    re.IGNORECASE,
)
_TTS_SPEED_SMALL_DOWN_RE = re.compile(
    _VERB_FALA + r".{0,10}\b(mais\s+)?(devagar|lento|pausad)"
    r"|\b(mais\s+)?(devagar|lento|pausad)\b.{0,10}\bpor\s+favor\b"
    r"|\bvelocidade\b.{0,15}\b(mais\s+)?(devagar|lento|baixa|menor)\b",
    re.IGNORECASE,
)
_TTS_SPEED_BIG_UP_RE = re.compile(
    _VERB_FALA + r".{0,10}\b(bem|muito|bastante)\b.{0,10}\b(mais\s+)?(r[áa]pido|veloz|acelerado)"
    r"|\bvelocidade\b.{0,15}\b(bem|muito|bastante)\b.{0,15}\b(mais\s+)?(r[áa]pido|alta|maior)\b",
    re.IGNORECASE,
)
_TTS_SPEED_SMALL_UP_RE = re.compile(
    _VERB_FALA + r".{0,10}\b(mais\s+)?(r[áa]pid[oa]|veloz|acelera)"
    r"|\bacelera\b"
    r"|\bvelocidade\b.{0,15}\b(mais\s+)?(r[áa]pid[oa]|alta|maior)\b",
    re.IGNORECASE,
)
_TTS_SPEED_NORMAL_RE = re.compile(
    r"\bvelocidade\s+(normal|padr[ãa]o|original|default)\b"
    r"|\bvolta\b.{0,15}\bvelocidade\b",
    re.IGNORECASE,
)
_TTS_SPEED_ANY_RE = re.compile(
    r"\b(r[áa]pido|devagar|veloz|lento|acelerado|pausado)\b",
    re.IGNORECASE,
)
_TTS_VOICE_RE = re.compile(
    r"\b(muda[r]?|usa[r]?|quero|coloca[r]?|ativa[r]?|testa[r]?|bota[r]?|tenta[r]?)\b.{0,20}\bvoz\b.{0,15}(alloy|echo|fable|nova|onyx|shimmer)"
    r"|\bvoz\s+(para\s+|pra\s+)?(alloy|echo|fable|nova|onyx|shimmer)"
    r"|\b(alloy|echo|fable|nova|onyx|shimmer)\b.{0,10}\b(voz|voice)\b",
    re.IGNORECASE,
)
_TTS_LIST_VOICES_RE = re.compile(
    r"\b(quais?|que|mostre?|lista[r]?|ver?|quero\s+ver)\b.{0,20}\b(vozes?|opções?\s+de\s+voz)\b"
    r"|\bvozes?\s+(disponíveis?|tem|existem|há|posso\s+escolher)\b"
    r"|\bque\s+vozes?\s+(tem|há|existem)\b",
    re.IGNORECASE,
)

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
    """Pré-check determinístico para comandos de velocidade e voz TTS."""
    base = {"intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": None, "audio_for_media": None, "reset": False,
            "list_voices": False}

    if _TTS_LIST_VOICES_RE.search(text):
        return {**base, "list_voices": True, "tts_voice": None, "tts_speed": None, "reply": _VOICES_LIST_REPLY}

    voice_match = _TTS_VOICE_RE.search(text)
    if voice_match:
        # Extrai o nome da voz de qualquer grupo que tenha capturado
        voice = next((g for g in voice_match.groups() if g and g.lower() in ("alloy", "echo", "fable", "nova", "onyx", "shimmer")), None)
        if voice:
            return {**base, "tts_voice": voice.lower(), "tts_speed": None, "reply": f"Voz alterada para *{voice.lower()}*."}

    if _TTS_SPEED_BIG_DOWN_RE.search(text):
        new_speed = round(max(0.5, current_speed - 0.15), 2)
        return {**base, "tts_voice": None, "tts_speed": new_speed, "reply": f"Falando mais devagar agora (velocidade: {new_speed})."}

    if _TTS_SPEED_SMALL_DOWN_RE.search(text):
        new_speed = round(max(0.5, current_speed - 0.07), 2)
        return {**base, "tts_voice": None, "tts_speed": new_speed, "reply": f"Um pouco mais devagar (velocidade: {new_speed})."}

    if _TTS_SPEED_BIG_UP_RE.search(text):
        new_speed = round(min(1.5, current_speed + 0.15), 2)
        return {**base, "tts_voice": None, "tts_speed": new_speed, "reply": f"Falando mais rápido agora (velocidade: {new_speed})."}

    if _TTS_SPEED_SMALL_UP_RE.search(text):
        new_speed = round(min(1.5, current_speed + 0.07), 2)
        return {**base, "tts_voice": None, "tts_speed": new_speed, "reply": f"Um pouco mais rápido (velocidade: {new_speed})."}

    if _TTS_SPEED_NORMAL_RE.search(text):
        return {**base, "tts_voice": None, "tts_speed": 0.95, "reply": "Velocidade normal (0.95)."}

    return None


_AUDIO_TEXT_ON_RE = re.compile(
    r"\b(texto|textos|mensagens?\s+de\s+texto)\b.{0,25}\b(áudio|audio)\b"
    r"|\b(responde|resposta|respostas)\b.{0,25}\b(texto|textos)\b.{0,25}\b(áudio|audio)\b"
    r"|\b(quero|ativa|liga)\b.{0,15}\b(áudio|audio)\b.{0,25}\b(texto|textos|mensagens?)\b",
    re.IGNORECASE,
)
_AUDIO_MEDIA_ON_RE = re.compile(
    r"\b(imagens?|fotos?|documentos?|pdf|mídia|mídias|arquivos?)\b.{0,25}\b(áudio|audio)\b"
    r"|\b(responde|resposta)\b.{0,25}\b(imagens?|fotos?|documentos?|mídia)\b.{0,25}\b(áudio|audio)\b",
    re.IGNORECASE,
)
_AUDIO_ALL_ON_RE = re.compile(
    # "tudo/qualquer coisa em áudio"
    r"\b(tudo|todos?|qualquer)\b.{0,20}\b(áudio|audio|voz)\b"
    # verbo de ação (qualquer conjugação via radical) + áudio
    r"|\b(quer\w*|ativ\w*|lig\w*|habilit\w*|prefer\w*|respond\w*|pod\w*|consegu\w*|fal\w*|mand\w*|envi\w*)\b.{0,30}\b(áudio|audio|voz)\b"
    # áudio + confirmação/pedido
    r"|\b(áudio|audio|voz)\b.{0,25}\b(ativ\w*|lig\w*|resposta|modo|por\s+favor|pfv|pls|please)\b",
    re.IGNORECASE,
)
_AUDIO_TEXT_OFF_RE = re.compile(
    r"\b(texto|textos|mensagens?\s+de\s+texto)\b.{0,25}\b(texto|sem\s+áudio|desativa|só\s+texto)\b"
    r"|\b(desativa|desliga|sem)\b.{0,15}\b(áudio|audio)\b.{0,25}\b(texto|textos|mensagens?)\b",
    re.IGNORECASE,
)
_AUDIO_MEDIA_OFF_RE = re.compile(
    r"\b(imagens?|fotos?|documentos?|pdf|mídia|mídias)\b.{0,25}\b(texto|sem\s+áudio|desativa)\b"
    r"|\b(desativa|desliga|sem)\b.{0,15}\b(áudio|audio)\b.{0,25}\b(imagens?|fotos?|mídia)\b",
    re.IGNORECASE,
)
_AUDIO_ALL_OFF_RE = re.compile(
    r"\b(desativa|desliga|para|cancela|sem|desabilita|desativar)\b.{0,25}\b(áudio|audio)\b"
    r"|\b(resposta\s+em\s+texto|modo\s+texto|tudo\s+em\s+texto|só\s+texto|somente\s+texto)\b",
    re.IGNORECASE,
)


def _quick_audio_check(text: str) -> dict | None:
    """Pré-check determinístico para preferência de áudio, evitando falsos negativos do LLM."""
    # Se tem palavras de velocidade (rápido, devagar, veloz...), não é ativação de áudio
    if _TTS_SPEED_ANY_RE.search(text):
        return None
    # Verificar padrões específicos antes do padrão geral
    if _AUDIO_TEXT_ON_RE.search(text) and not _AUDIO_MEDIA_ON_RE.search(text):
        return {
            "intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": True, "audio_for_media": None, "reset": False,
            "reply": "Certo! Vou responder suas mensagens de texto em áudio. Para imagens e documentos continuo em texto.",
        }
    if _AUDIO_MEDIA_ON_RE.search(text) and not _AUDIO_TEXT_ON_RE.search(text):
        return {
            "intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": None, "audio_for_media": True, "reset": False,
            "reply": "Certo! Vou responder imagens, fotos e documentos em áudio. Textos continuam em texto.",
        }
    if _AUDIO_TEXT_OFF_RE.search(text) and not _AUDIO_MEDIA_OFF_RE.search(text):
        return {
            "intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": False, "audio_for_media": None, "reset": False,
            "reply": "Entendido! Vou responder suas mensagens de texto em texto novamente.",
        }
    if _AUDIO_MEDIA_OFF_RE.search(text) and not _AUDIO_TEXT_OFF_RE.search(text):
        return {
            "intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": None, "audio_for_media": False, "reset": False,
            "reply": "Entendido! Vou responder imagens e documentos em texto novamente.",
        }
    if _AUDIO_ALL_ON_RE.search(text):
        return {
            "intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": True, "audio_for_media": True, "reset": False,
            "reply": "Certo! A partir de agora respondo tudo em áudio — textos, imagens e documentos. Para voltar ao texto, é só falar 'desativa áudio'.",
        }
    if _AUDIO_ALL_OFF_RE.search(text):
        return {
            "intent": "preference", "sections": None, "report_time": None,
            "audio_for_text": False, "audio_for_media": False, "reset": False,
            "reply": "Entendido! Vou responder tudo em texto daqui pra frente.",
        }
    return None


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
- polls_br → pesquisas, pesquisas eleitorais, eleições, intenção de voto, polls

Responda SOMENTE com JSON:
{
  "intent": "preference",
  "sections": {todas as 8 seções com true/false} ou null se não mencionado,
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
- Se não mencionado → tts_voice: null

Regras de velocidade TTS (tts_speed):
- ATENÇÃO: mensagens com "rápido", "devagar", "veloz" ou "lento" são SEMPRE tts_speed. Nunca audio_for_text.
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
    "polls_br": "pesquisas",
}


def _build_settings_summary(prefs: dict | None) -> str:
    p = prefs or {}
    audio_text = "sim" if p.get("audio_for_text") else "não"
    audio_media = "sim" if p.get("audio_for_media") else "não"
    voice = p.get("tts_voice") or "nova"
    speed = p.get("tts_speed") or 0.85
    report_time = p.get("report_time") or "não configurado"
    sections = p.get("sections") or {}
    active = [_SECTION_LABELS.get(k, k) for k, v in sections.items() if v] if sections else list(_SECTION_LABELS.values())
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
        batch_size = min(total, 50)
        all_msgs = supabase.get_history(phone, limit=batch_size)
        old_msgs = all_msgs[:-_KEEP_RECENT] if len(all_msgs) > _KEEP_RECENT else []
        if not old_msgs:
            return
        from backend.services import summarizer
        existing = supabase.get_summary(phone)
        new_summary = summarizer.summarize(old_msgs, existing)
        supabase.save_summary(phone, new_summary)
        supabase.delete_old_history(phone, keep_recent=_KEEP_RECENT)
    except Exception:
        logger.warning("summarization failed for %s", phone, exc_info=True)


def _detect_preference_intent(text: str, current_sections: dict | None = None, tts_speed: float = 0.85) -> dict:
    context = f"\nvelocidade_atual: {tts_speed:.2f}"
    if current_sections:
        context += f"\nseções_atuais: {json.dumps(current_sections, ensure_ascii=False)}"
    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=_PREFERENCE_SYSTEM,
            messages=[{"role": "user", "content": text + context}],
        )
        return json.loads(response.content[0].text)
    except Exception:
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

    try:
        data = payload.get("data", {})
        key = data.get("key", {})
        if key.get("fromMe"):
            return {"status": "ignored", "reason": "fromMe"}

        remote_jid = key.get("remoteJid", "")
        push_name = data.get("pushName", "")
        msg_info = _extract_message(data.get("message", {}))
        if msg_info["type"] == "unknown":
            return {"status": "ignored", "reason": "unsupported media type"}
        # Para texto usa o conteúdo direto; para mídia o texto é extraído depois da transcrição/análise
        text = msg_info.get("text", "") if msg_info["type"] == "text" else "[mídia]"

        admin_phone = _admin_phone()
        authorized = supabase.get_authorized(remote_jid)

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
        # TTS check primeiro: evita que "fala mais rápido" seja classificado como ativar áudio
        intent = (
            (_quick_tts_check(text, tts_speed) or _quick_audio_check(text) or _detect_preference_intent(text, current_sections=current_sections, tts_speed=tts_speed))
            if msg_info["type"] == "text"
            else {"intent": "message"}
        )

        if intent.get("intent") == "preference":
            if intent.get("reset"):
                supabase.delete_preferences(target_phone)
            else:
                new_sections = intent.get("sections")
                new_time = intent.get("report_time")
                new_audio_text = intent.get("audio_for_text")
                new_audio_media = intent.get("audio_for_media")
                new_tts_voice = intent.get("tts_voice")
                new_tts_speed = intent.get("tts_speed")
                if any(v is not None for v in [new_sections, new_time, new_audio_text, new_audio_media, new_tts_voice, new_tts_speed]):
                    supabase.save_preferences(
                        target_phone,
                        sections=new_sections,
                        report_time=new_time,
                        audio_for_text=new_audio_text,
                        audio_for_media=new_audio_media,
                        tts_voice=new_tts_voice,
                        tts_speed=new_tts_speed,
                    )
                    if new_tts_voice:
                        tts_voice = new_tts_voice
                    if new_tts_speed is not None:
                        tts_speed = new_tts_speed
            reply = intent.get("reply", "Preferências atualizadas!")
            # list_voices nunca é enviado como áudio — é uma lista visual
            if not intent.get("list_voices") and bool((current_prefs or {}).get("audio_for_text", False)):
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
            audio_intent = _quick_tts_check(text, tts_speed) or _quick_audio_check(text) or _detect_preference_intent(text, current_sections=current_sections, tts_speed=tts_speed)
            if audio_intent and audio_intent.get("intent") == "preference":
                new_audio_text = audio_intent.get("audio_for_text")
                new_audio_media = audio_intent.get("audio_for_media")
                new_tts_voice = audio_intent.get("tts_voice")
                new_tts_speed = audio_intent.get("tts_speed")
                if any(v is not None for v in [new_audio_text, new_audio_media, new_tts_voice, new_tts_speed]):
                    supabase.save_preferences(
                        target_phone,
                        sections=None,
                        report_time=None,
                        audio_for_text=new_audio_text,
                        audio_for_media=new_audio_media,
                        tts_voice=new_tts_voice,
                        tts_speed=new_tts_speed,
                    )
                    if new_tts_voice:
                        tts_voice = new_tts_voice
                    if new_tts_speed is not None:
                        tts_speed = new_tts_speed
                reply = audio_intent.get("reply", "Preferências atualizadas!")
                try:
                    audio_bytes = media_service.text_to_speech(reply, voice=tts_voice, speed=tts_speed)
                    whatsapp.send_audio(target_phone, audio_bytes)
                except Exception:
                    whatsapp.send_message(target_phone, reply)
                return {"status": "ok", "reason": "preference_updated"}

            supabase.save_message(target_phone, "user", f"[áudio transcrito] {text}")
            _t = time.monotonic()
            reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"), sections={})
            logger.info("audio: report %.1fs", time.monotonic() - _t)
            supabase.save_message(target_phone, "assistant", reply)
            _maybe_summarize(target_phone)

            if audio_for_media:
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
            )
            supabase.save_message(target_phone, "assistant", reply)
            _maybe_summarize(target_phone)
            if audio_for_media:
                try:
                    audio_bytes = media_service.text_to_speech(reply, voice=tts_voice, speed=tts_speed)
                    whatsapp.send_audio(target_phone, audio_bytes)
                    return {"status": "ok"}
                except Exception:
                    pass  # fallback para texto se TTS falhar
            whatsapp.send_message(target_phone, reply)
            return {"status": "ok"}

        # ── Texto (fluxo original) ─────────────────────────────────────────────
        supabase.save_message(target_phone, "user", text)
        reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"), sections={})
        supabase.save_message(target_phone, "assistant", reply)
        _maybe_summarize(target_phone)
        if audio_for_text:
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
        return {"status": "error", "detail": str(e)}
