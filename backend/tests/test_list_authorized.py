from dotenv import load_dotenv
load_dotenv()
from backend.services import supabase


def test_list_authorized_returns_list():
    rows = supabase.list_authorized()
    assert isinstance(rows, list)
    for row in rows:
        assert "phone" in row
