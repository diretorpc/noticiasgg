import base64
import io
import os

from openai import OpenAI

# O default do SDK OpenAI é 600s (+ retries), o dobro do maxDuration (300s) da função
# na Vercel. Sem timeout próprio, uma chamada pendurada estoura a função com 504 silencioso.
_OPENAI_TIMEOUT = 60.0


def transcribe_audio(audio_b64: str, mime_type: str = "audio/ogg") -> str:
    """Transcreve áudio base64 via OpenAI Whisper. Retorna texto em português."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=_OPENAI_TIMEOUT, max_retries=1)
    audio_bytes = base64.b64decode(audio_b64)

    # Inferir extensão pelo mime_type para nomear o buffer corretamente
    ext = "ogg"
    if "mp4" in mime_type or "m4a" in mime_type:
        ext = "m4a"
    elif "mp3" in mime_type or "mpeg" in mime_type:
        ext = "mp3"
    elif "webm" in mime_type:
        ext = "webm"
    elif "wav" in mime_type:
        ext = "wav"

    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"audio.{ext}"

    transcript = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="pt",
    )
    return transcript.text


def text_to_speech(text: str, voice: str = "nova", speed: float = 0.85) -> bytes:
    """Converte texto em áudio MP3 via OpenAI TTS. Retorna bytes do MP3."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=_OPENAI_TIMEOUT, max_retries=1)

    if len(text) > 4096:
        text = text[:4093] + "..."

    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
        response_format="mp3",
        speed=speed,
    )
    return response.content
