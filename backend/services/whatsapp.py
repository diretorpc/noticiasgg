import base64
import os
import httpx


def _headers() -> dict:
    return {"apikey": os.environ["EVOLUTION_API_KEY"], "Content-Type": "application/json"}


def _base_url() -> str:
    return os.environ["EVOLUTION_API_URL"]


def _instance() -> str:
    return os.environ["EVOLUTION_INSTANCE"]


def send_message(number: str, text: str) -> dict:
    endpoint = f"{_base_url()}/message/sendText/{_instance()}"
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
    payload = {"message": full_message_data}
    with httpx.Client(timeout=45) as client:
        resp = client.post(endpoint, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def send_audio(number: str, audio_bytes: bytes) -> dict:
    """Envia áudio como PTT (voice note) via Evolution API.
    audio_bytes deve ser MP3; Evolution converte para OGG/OPUS internamente.
    """
    endpoint = f"{_base_url()}/message/sendWhatsAppAudio/{_instance()}"
    audio_b64 = base64.b64encode(audio_bytes).decode()
    payload = {
        "number": number,
        "options": {"delay": 0, "presence": "recording"},
        "audioMessage": {"audio": audio_b64, "encoding": True},
    }
    with httpx.Client(timeout=45) as client:
        resp = client.post(endpoint, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()
