"""Regra única do que é valor válido para as preferências de voz/áudio.

Vale para as três portas que gravam `user_preferences`: o WhatsApp (o que o Haiku
manda gravar), a página pessoal `/me` e o painel admin. Antes só o WhatsApp
validava, e o `/me` gravava `tts_speed` 5.0 direto para o TTS (09/11/2026)."""

AUDIO_FIELDS = ("audio_for_text", "audio_for_media", "tts_voice", "tts_speed")
TTS_VOICES = ("alloy", "echo", "fable", "nova", "onyx", "shimmer")
TTS_SPEED_MIN, TTS_SPEED_MAX = 0.5, 1.5


def valid_audio_field(campo: str, valor) -> bool:
    """`tts_speed` gravado como texto fazia `float()` estourar em TODA mensagem
    seguinte do usuário ("Tive um problema" até limpar o banco), e voz fora da lista
    virava "Voz alterada" com TTS caindo calado (achado 3, 4ª revisão do Apolo).
    `bool` antes de número: `True` é `int` em Python."""
    if valor is None:
        return False
    if campo in ("audio_for_text", "audio_for_media"):
        return isinstance(valor, bool)
    if campo == "tts_voice":
        return valor in TTS_VOICES
    if campo == "tts_speed":
        return (isinstance(valor, (int, float)) and not isinstance(valor, bool)
                and TTS_SPEED_MIN <= valor <= TTS_SPEED_MAX)
    return False


def invalid_fields(values: dict) -> list[str]:
    """Campos de áudio presentes (não-None) com valor inválido. `None` é "não mexe"."""
    return [k for k in AUDIO_FIELDS
            if values.get(k) is not None and not valid_audio_field(k, values[k])]
