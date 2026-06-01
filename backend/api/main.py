import json
import os
import re
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic

from backend.collectors import market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br, agro_br
from backend.services import reporter, whatsapp, supabase
from backend.services import media as media_service
from backend.api import send_report, cron_report

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


PHONE_RE = re.compile(r"^\D*(\d{10,13})\D*$")

_DATA_KEYWORDS = re.compile(
    r"\b("
    # relatório explícito
    r"relat[oó]rio|resumo|an[áa]lise|panorama|overview|briefing|"
    # câmbio e moedas
    r"d[oó]lar|dolar|euro|libra|iene|yuan|renminbi|peso|"
    r"c[âa]mbio|forex|moeda|convers[ãa]o|"
    # cripto
    r"bitcoin|btc|ethereum|eth|cripto|crypto|altcoin|blockchain|"
    r"solana|sol|bnb|xrp|ripple|cardano|ada|dogecoin|doge|"
    # bolsas e índices
    r"bolsa|ibovespa|ibrx|nasdaq|s&p|s&p500|dow\s*jones|nikkei|ftse|"
    r"dax|cac|shanghai|hang\s*seng|b3|nyse|"
    # ações e mercado
    r"a[çc][ãa]o|a[çc][õo]es|papel|papeis|ticker|pregão|pregao|"
    r"mercado|investimento|carteira|portf[oó]lio|"
    # indicadores BR
    r"selic|ipca|igpm|igp-m|pib|c[âa]mbio|inpc|"
    # indicadores EUA
    r"cpi|ppi|gdp|fed|federal\s*reserve|taxa\s*de\s*juros|juros|"
    r"desemprego|emprego|payroll|inflac[ãa]o|infla[çc][ãa]o|"
    # commodities
    r"commodity|commodities|petr[oó]leo|brent|wti|g[aá]s|"
    r"ouro|prata|cobre|min[eé]rio|"
    r"soja|milho|caf[eé]|a[çc][uú]car|algod[ãa]o|trigo|boi|"
    # cotações e preços (requer contexto — não usar palavras genéricas de tempo)
    r"cota[çc][ãa]o|pregão|pregao|"
    # notícias
    r"not[ií]cia|not[ií]cias|novidade|acontec"
    r")\b",
    re.IGNORECASE,
)


def _needs_market_data(text: str) -> bool:
    return bool(_DATA_KEYWORDS.search(text))


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


_AUDIO_ON_RE = re.compile(
    r"\b(quero|ativa|liga|habilita|modo|prefiro|manda|envia|responde)\b.{0,25}\b(áudio|audio)\b"
    r"|\b(áudio|audio)\b.{0,25}\b(ativa|liga|resposta|modo|por\s+favor)\b",
    re.IGNORECASE,
)
_AUDIO_OFF_RE = re.compile(
    r"\b(desativa|desliga|para|cancela|sem|desabilita|desativar)\b.{0,25}\b(áudio|audio)\b"
    r"|\b(resposta\s+em\s+texto|modo\s+texto|só\s+texto|somente\s+texto)\b",
    re.IGNORECASE,
)


def _quick_audio_check(text: str) -> dict | None:
    """Pré-check determinístico para preferência de áudio, evitando falsos negativos do LLM."""
    if _AUDIO_ON_RE.search(text):
        return {
            "intent": "preference",
            "sections": None,
            "report_time": None,
            "audio_response": True,
            "reset": False,
            "reply": "Certo! A partir de agora vou responder seus áudios com mensagens de voz. 🎙️ Para voltar ao texto, é só falar 'desativa áudio'.",
        }
    if _AUDIO_OFF_RE.search(text):
        return {
            "intent": "preference",
            "sections": None,
            "report_time": None,
            "audio_response": False,
            "reset": False,
            "reply": "Entendido! Vou responder apenas com texto daqui pra frente.",
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
  "audio_response": true/false ou null se não mencionado,
  "reset": false,
  "reply": "mensagem de confirmação amigável em português"
}

Regras de seções:
- "quero só X e Y" → todas false exceto X e Y
- "salve apenas X" ou "somente X" → todas false exceto X
- "remove X" → apenas X=false (manter restante do contexto atual)
- "adiciona X" → apenas X=true (manter restante do contexto atual)

Regras de horário:
- "às 8h" → "08:00"
- "às 20h30" ou "8 e meia" → arredondar para próxima hora cheia

Regras de áudio:
- "quero resposta em áudio", "responde em áudio", "ativa áudio", "modo áudio" → audio_response: true
- "desativa áudio", "resposta em texto", "para de responder em áudio", "modo texto" → audio_response: false
- Se não mencionado → audio_response: null

Reset: "volta pro padrão", "quero tudo de volta", "cancela preferências" → {"intent": "preference", "sections": null, "report_time": null, "audio_response": null, "reset": true, "reply": "..."}

CATEGORIA 2 — Qualquer outra mensagem:
Responda SOMENTE com JSON: {"intent": "message"}"""


def _detect_preference_intent(text: str, current_sections: dict | None = None) -> dict:
    context = ""
    if current_sections:
        context = f"\n\nConfiguração atual do usuário: {json.dumps(current_sections, ensure_ascii=False)}"
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


@app.post("/api/webhook")
async def whatsapp_webhook(request: Request):
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

        # Detectar intenção de preferência — apenas para mensagens de texto
        current_prefs = supabase.get_preferences(target_phone)
        current_sections = current_prefs.get("sections") if current_prefs else None
        intent = (
            (_quick_audio_check(text) or _detect_preference_intent(text, current_sections=current_sections))
            if msg_info["type"] == "text"
            else {"intent": "message"}
        )

        if intent.get("intent") == "preference":
            if intent.get("reset"):
                supabase.delete_preferences(target_phone)
            else:
                new_sections = intent.get("sections")
                new_time = intent.get("report_time")
                new_audio = intent.get("audio_response")
                if new_sections is not None or new_time is not None or new_audio is not None:
                    supabase.save_preferences(
                        target_phone,
                        sections=new_sections,
                        report_time=new_time,
                        audio_response=new_audio,
                    )
            reply = intent.get("reply", "Preferências atualizadas!")
            whatsapp.send_message(target_phone, reply)
            return {"status": "ok", "reason": "preference_updated"}

        # Buscar histórico
        history = supabase.get_history(target_phone, limit=10)
        anthropic_history = [{"role": h["role"], "content": h["content"]} for h in history]
        audio_response_pref = bool((current_prefs or {}).get("audio_response", False))

        # ── Áudio ──────────────────────────────────────────────────────────────
        if msg_info["type"] == "audio":
            try:
                media = whatsapp.download_media(data)
            except Exception:
                whatsapp.send_message(target_phone, "Não consegui baixar o áudio, tente novamente.")
                return {"status": "ok", "reason": "media_download_failed"}
            try:
                text = media_service.transcribe_audio(media["base64"], media.get("mimetype", "audio/ogg"))
            except Exception:
                whatsapp.send_message(target_phone, "Não consegui transcrever o áudio.")
                return {"status": "ok", "reason": "transcription_failed"}

            sections = current_sections if _needs_market_data(text) else {}
            supabase.save_message(target_phone, "user", f"[áudio transcrito] {text}")
            reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"), sections=sections)
            supabase.save_message(target_phone, "assistant", reply)

            if audio_response_pref:
                try:
                    audio_bytes = media_service.text_to_speech(reply)
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
            whatsapp.send_message(target_phone, reply)
            return {"status": "ok"}

        # ── Texto (fluxo original) ─────────────────────────────────────────────
        sections = current_sections if _needs_market_data(text) else {}
        supabase.save_message(target_phone, "user", text)
        reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"), sections=sections)
        supabase.save_message(target_phone, "assistant", reply)
        whatsapp.send_message(target_phone, reply)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("webhook error")
        return {"status": "error", "detail": str(e)}
