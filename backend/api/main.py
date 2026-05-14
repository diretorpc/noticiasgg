import json
import os
import re
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from anthropic import Anthropic

from backend.collectors import market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br
from backend.services import reporter, whatsapp, supabase
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
app.include_router(send_report.router)
app.include_router(cron_report.router)


PHONE_RE = re.compile(r"^\D*(\d{10,13})\D*$")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


def _extract_text(message: dict) -> str:
    return (
        message.get("conversation")
        or message.get("extendedTextMessage", {}).get("text")
        or ""
    )


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
        whatsapp.send_message(phone, "Olá! Você foi autorizado a conversar com o agente Notícias GG. Pode mandar suas perguntas sobre mercado, cotações e notícias financeiras.")
        return f"Autorizado: {pending['push_name']} → {phone}"

    return None


_PREFERENCE_SYSTEM = """Você é um parser de intenções. Analise a mensagem e classifique em uma de duas categorias.

CATEGORIA 1 — Pedido de configuração do relatório diário:
Seções disponíveis: market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br.

Responda SOMENTE com JSON:
{
  "intent": "preference",
  "sections": {todas as 8 seções com true/false},
  "report_time": "HH:00" ou null,
  "reset": false,
  "reply": "mensagem de confirmação amigável em português"
}

Regras de seções:
- "quero só X e Y" → todas false exceto X e Y
- "remove X" → apenas X=false (manter restante do contexto atual)
- "adiciona X" → apenas X=true (manter restante do contexto atual)

Regras de horário:
- "às 8h" → "08:00"
- "às 20h30" ou "8 e meia" → arredondar para próxima hora cheia

Reset: "volta pro padrão", "quero tudo de volta", "cancela preferências" → {"intent": "preference", "sections": null, "report_time": null, "reset": true, "reply": "..."}

CATEGORIA 2 — Qualquer outra mensagem:
Responda SOMENTE com JSON:
{"intent": "message", "needs_data": true ou false}

needs_data = true se o usuário pedir:
- relatório, resumo, análise do mercado
- cotações, preços, valores de ações/moedas/cripto
- notícias financeiras ou econômicas
- indicadores (Selic, IPCA, juros, PIB, CPI, etc.)
- commodities, petróleo, ouro, soja

needs_data = false para QUALQUER mensagem que não exija dados em tempo real, incluindo:
- saudações e despedidas (oi, olá, bom dia, boa tarde, boa noite, tchau, até mais)
- agradecimentos (obrigado, valeu, show)
- confirmações e respostas curtas (ok, entendi, certo, sim, não)
- perguntas conceituais ("o que é Selic?", "como funciona a bolsa?", "o que é inflação?")
- qualquer conversa casual que não dependa de dados de mercado atuais

Em caso de dúvida, prefira needs_data = false."""


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
        text = _extract_text(data.get("message", {}))
        if not text:
            return {"status": "ignored", "reason": "no text"}

        admin_phone = _admin_phone()
        authorized = supabase.get_authorized(remote_jid)

        if not authorized:
            # Não autorizado → cria pendência e notifica admin
            supabase.upsert_pending(remote_jid, push_name, text)
            if admin_phone:
                whatsapp.send_message(
                    admin_phone,
                    f"Novo pedido de acesso:\n\n*{push_name}* mandou: \"{text}\"\n\nResponda com o número da pessoa (ex: 5534999999999) para autorizar.",
                )
            return {"status": "ok", "reason": "pending auth"}

        target_phone = authorized["phone"]
        is_admin = target_phone == admin_phone

        if is_admin:
            admin_response = _handle_admin_command(text)
            if admin_response is not None:
                whatsapp.send_message(admin_phone, admin_response)
                return {"status": "ok", "reason": "admin command"}

        # Detectar intenção de preferência antes de gerar resposta
        current_prefs = supabase.get_preferences(target_phone)
        current_sections = current_prefs.get("sections") if current_prefs else None
        intent = _detect_preference_intent(text, current_sections=current_sections)

        if intent.get("intent") == "preference":
            if intent.get("reset"):
                supabase.delete_preferences(target_phone)
            else:
                new_sections = intent.get("sections")
                new_time = intent.get("report_time")
                if new_sections is not None or new_time is not None:
                    supabase.save_preferences(target_phone, sections=new_sections, report_time=new_time)
            reply = intent.get("reply", "Preferências atualizadas!")
            whatsapp.send_message(target_phone, reply)
            return {"status": "ok", "reason": "preference_updated"}

        # Buscar histórico e gerar resposta
        history = supabase.get_history(target_phone, limit=10)
        anthropic_history = [{"role": h["role"], "content": h["content"]} for h in history]

        needs_data = intent.get("needs_data", True)
        sections = current_sections if needs_data else {}

        supabase.save_message(target_phone, "user", text)
        reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"), sections=sections)
        supabase.save_message(target_phone, "assistant", reply)

        whatsapp.send_message(target_phone, reply)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("webhook error")
        return {"status": "error", "detail": str(e)}
