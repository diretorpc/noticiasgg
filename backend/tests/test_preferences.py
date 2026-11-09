import pytest
import os
from dotenv import load_dotenv
load_dotenv()
from backend.services import supabase

PHONE_TEST = "5500000000000"

# `sections`/`report_time` saíram de `save_preferences` em 09/11/2026 (campos mortos,
# ver `test_campo_morto.py`). Os testes de gravação deles e os de `get_users_for_hour`
# (que dependiam de gravar `report_time` para semear o banco; só a rota do n8n, desligado,
# lê aquilo) foram retirados junto.


def teardown_function():
    supabase.delete_preferences(PHONE_TEST)


def test_get_preferences_inexistente():
    supabase.delete_preferences(PHONE_TEST)
    assert supabase.get_preferences(PHONE_TEST) is None


def test_save_and_get_preferences_audio():
    supabase.save_preferences(PHONE_TEST, audio_for_text=True, tts_voice="onyx")
    prefs = supabase.get_preferences(PHONE_TEST)
    assert prefs is not None
    assert prefs["audio_for_text"] is True
    assert prefs["tts_voice"] == "onyx"


def test_save_preferences_upsert():
    supabase.save_preferences(PHONE_TEST, tts_voice="onyx")
    supabase.save_preferences(PHONE_TEST, tts_voice="echo")
    prefs = supabase.get_preferences(PHONE_TEST)
    assert prefs["tts_voice"] == "echo"


def test_delete_preferences():
    supabase.save_preferences(PHONE_TEST, tts_voice="onyx")
    supabase.delete_preferences(PHONE_TEST)
    assert supabase.get_preferences(PHONE_TEST) is None
