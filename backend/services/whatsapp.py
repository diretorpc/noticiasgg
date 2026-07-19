import base64
import logging
import os
import httpx

from backend.services import supabase

logger = logging.getLogger("noticiasgg")


def _headers() -> dict:
    return {"apikey": os.environ["EVOLUTION_API_KEY"], "Content-Type": "application/json"}


def _base_url() -> str:
    return os.environ["EVOLUTION_API_URL"]


def _instance() -> str:
    return os.environ["EVOLUTION_INSTANCE"]


def _is_v2() -> bool:
    """True quando a Evolution é a v2 (payload achatado). Controlado por
    EVOLUTION_API_V2; default False = comportamento legado v1.8.2."""
    return os.environ.get("EVOLUTION_API_V2", "").strip().lower() in ("1", "true", "yes", "on")


def _resolve_target(number: str) -> str:
    """Traduz telefone ou JID de telefone → LID antes de enviar.

    A Evolution não entrega para o JID de telefone (`@s.whatsapp.net`) nesta
    conta: a mensagem é aceita mas nunca chega. Só o LID (`@lid`) é roteável —
    verificado em produção 16/07/2026. Por isso o `@s.whatsapp.net` (formato do
    `remoteJid` na v2) também precisa ser traduzido: repassá-lo é o único
    caminho comprovadamente morto.
    Se a tradução falhar, devolve o número puro (não pior que o comportamento
    antigo, e a Evolution ainda pode resolvê-lo).
    """
    if not number:
        return number
    if number.endswith("@lid"):
        return number
    bare = number.split("@")[0]  # número sem o sufixo do JID; fallback quando não há LID
    try:
        if "@" in number:
            user = supabase.get_authorized_by_jid(number)
        else:
            user = supabase.get_authorized_by_phone(number)
        return (user or {}).get("lid") or bare
    except Exception:
        logger.warning("lid lookup falhou para %s — enviando para o número", number)
        return bare


def send_message(number: str, text: str) -> dict:
    number = _resolve_target(number)
    endpoint = f"{_base_url()}/message/sendText/{_instance()}"
    if _is_v2():
        payload = {"number": number, "text": text}
    else:
        payload = {"number": number, "options": {"delay": 0, "presence": "composing"}, "textMessage": {"text": text}}
    with httpx.Client(timeout=30) as client:
        resp = client.post(endpoint, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def download_media(full_message_data: dict) -> dict:
    """Baixa mídia de uma mensagem via Evolution API.
    Retorna {"base64": str, "mimetype": str}.
    full_message_data é o objeto `data` completo do payload do webhook.
    """
    endpoint = f"{_base_url()}/chat/getBase64FromMediaMessage/{_instance()}"
    if _is_v2():
        # v2 espera apenas a key da mensagem, não o objeto `data` inteiro. [verificar ao vivo]
        payload = {"message": {"key": full_message_data.get("key", {})}}
    else:
        payload = {"message": full_message_data}
    with httpx.Client(timeout=45) as client:
        resp = client.post(endpoint, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def connection_state() -> str:
    """Estado da conexão da instância na Evolution API (open/connecting/close).
    Levanta em falha — o caller (health) decide degradar para warn."""
    endpoint = f"{_base_url()}/instance/connectionState/{_instance()}"
    with httpx.Client(timeout=10) as client:
        resp = client.get(endpoint, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        inst = data.get("instance", data)
        return inst.get("state", "unknown")


def send_audio(number: str, audio_bytes: bytes) -> dict:
    """Envia áudio como PTT (voice note) via Evolution API.
    audio_bytes deve ser MP3; Evolution converte para OGG/OPUS internamente.
    """
    number = _resolve_target(number)
    endpoint = f"{_base_url()}/message/sendWhatsAppAudio/{_instance()}"
    audio_b64 = base64.b64encode(audio_bytes).decode()
    if _is_v2():
        payload = {"number": number, "audio": audio_b64}
    else:
        payload = {
            "number": number,
            "options": {"delay": 0, "presence": "recording"},
            "audioMessage": {"audio": audio_b64, "encoding": True},
        }
    with httpx.Client(timeout=45) as client:
        resp = client.post(endpoint, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()
