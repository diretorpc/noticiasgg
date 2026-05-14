import os
import re
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.collectors import market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br
from backend.services import reporter, whatsapp, supabase
from backend.api import send_report

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

        # Buscar histórico e gerar resposta
        history = supabase.get_history(target_phone, limit=10)
        # Converte histórico para formato Anthropic (sem o turno atual)
        anthropic_history = [{"role": h["role"], "content": h["content"]} for h in history]

        supabase.save_message(target_phone, "user", text)
        reply = reporter.generate_report(text, history=anthropic_history, user_name=authorized.get("name"))
        supabase.save_message(target_phone, "assistant", reply)

        whatsapp.send_message(target_phone, reply)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("webhook error")
        return {"status": "error", "detail": str(e)}
