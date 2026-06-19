import os
from dotenv import load_dotenv
load_dotenv()
from backend.services import supabase


def test_get_all_config_returns_list():
    rows = supabase.get_all_config()
    assert isinstance(rows, list)
    for row in rows:
        assert "key" in row and "value" in row
