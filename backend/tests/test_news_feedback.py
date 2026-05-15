import pytest
import os
from dotenv import load_dotenv
load_dotenv()
from backend.services import supabase

PHONE_TEST = "5500000000001"


def teardown_function():
    supabase.delete_news_feedback(PHONE_TEST)


def test_save_and_get_news_feedback():
    supabase.save_news_feedback(
        PHONE_TEST,
        important=["Fed", "juros"],
        unimportant=["eleições"],
        raw="só a notícia do Fed foi boa",
    )
    records = supabase.get_news_feedback(PHONE_TEST)
    assert len(records) == 1
    assert "Fed" in records[0]["important_topics"]
    assert "eleições" in records[0]["unimportant_topics"]


def test_get_news_feedback_vazio():
    supabase.delete_news_feedback(PHONE_TEST)
    records = supabase.get_news_feedback(PHONE_TEST)
    assert records == []


def test_delete_news_feedback():
    supabase.save_news_feedback(PHONE_TEST, ["SELIC"], [], "boa notícia sobre SELIC")
    supabase.delete_news_feedback(PHONE_TEST)
    assert supabase.get_news_feedback(PHONE_TEST) == []


def test_save_multiplos_feedbacks_acumula():
    supabase.save_news_feedback(PHONE_TEST, ["Fed"], [], "feedback 1")
    supabase.save_news_feedback(PHONE_TEST, ["SELIC"], ["política"], "feedback 2")
    records = supabase.get_news_feedback(PHONE_TEST)
    assert len(records) == 2
