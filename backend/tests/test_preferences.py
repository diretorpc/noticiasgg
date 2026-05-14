import pytest
import os
from dotenv import load_dotenv
load_dotenv()
from backend.services import supabase

PHONE_TEST = "5500000000000"


def teardown_function():
    supabase.delete_preferences(PHONE_TEST)


def test_get_preferences_inexistente():
    supabase.delete_preferences(PHONE_TEST)
    assert supabase.get_preferences(PHONE_TEST) is None


def test_save_and_get_preferences_sections():
    sections = {"market": True, "crypto": False, "indicators_us": True, "indicators_br": True,
                "news": True, "commodities_br": False, "politics_br": False, "polls_br": False}
    supabase.save_preferences(PHONE_TEST, sections=sections, report_time=None)
    prefs = supabase.get_preferences(PHONE_TEST)
    assert prefs is not None
    assert prefs["sections"]["crypto"] is False
    assert prefs["sections"]["market"] is True
    assert prefs["report_time"] is None


def test_save_and_get_preferences_horario():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    prefs = supabase.get_preferences(PHONE_TEST)
    assert prefs["report_time"] == "08:00"
    assert prefs["sections"] is None


def test_save_preferences_upsert():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="19:00")
    prefs = supabase.get_preferences(PHONE_TEST)
    assert prefs["report_time"] == "19:00"


def test_delete_preferences():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    supabase.delete_preferences(PHONE_TEST)
    assert supabase.get_preferences(PHONE_TEST) is None


def test_get_users_for_hour_retorna_usuario_com_horario():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    users = supabase.get_users_for_hour("08:00")
    phones = [u["phone"] for u in users]
    assert PHONE_TEST in phones


def test_get_users_for_hour_nao_retorna_outros_horarios():
    supabase.save_preferences(PHONE_TEST, sections=None, report_time="08:00")
    users = supabase.get_users_for_hour("19:00")
    phones = [u["phone"] for u in users]
    assert PHONE_TEST not in phones
