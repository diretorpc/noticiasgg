from backend.services import media


def test_media_describe_config_defaults():
    cfg = media.describe_config()
    assert cfg["tts_voice"] == "nova"
    assert cfg["tts_speed"] == 0.85
    assert cfg["tts_model"] == "tts-1"
    assert cfg["transcribe_model"] == "whisper-1"
    assert "nova" in cfg["voices_disponiveis"]
