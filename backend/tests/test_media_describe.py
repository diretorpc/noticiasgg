from backend.services import media
import pytest

# Arquivo sem nenhuma chamada de rede (medido rodando o arquivo isolado).
# O marcador vale para todos os testes abaixo e coloca este arquivo no
# portao do CI, que roda `pytest backend -m unit`.
pytestmark = pytest.mark.unit


def test_media_describe_config_defaults():
    cfg = media.describe_config()
    assert cfg["tts_voice"] == "nova"
    assert cfg["tts_speed"] == 0.85
    assert cfg["tts_model"] == "tts-1"
    assert cfg["transcribe_model"] == "whisper-1"
    assert "nova" in cfg["voices_disponiveis"]
