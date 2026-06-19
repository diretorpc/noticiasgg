from unittest.mock import patch

from backend.services import config


def _rows(d):
    return [{"key": k, "value": v} for k, v in d.items()]


def setup_function():
    config.clear_cache()


def test_get_returns_default_when_absent():
    with patch("backend.services.config.supabase.get_all_config", return_value=[]):
        assert config.get("news.x", "fallback") == "fallback"


def test_get_returns_value_when_present():
    with patch("backend.services.config.supabase.get_all_config",
               return_value=_rows({"news.x": ["a", "b"]})):
        assert config.get("news.x", None) == ["a", "b"]


def test_get_list_falls_back_on_type_mismatch():
    with patch("backend.services.config.supabase.get_all_config",
               return_value=_rows({"news.x": "not-a-list"})):
        assert config.get_list("news.x", ["d"]) == ["d"]


def test_get_str_falls_back_on_empty():
    with patch("backend.services.config.supabase.get_all_config",
               return_value=_rows({"news.q": "   "})):
        assert config.get_str("news.q", "default-q") == "default-q"


def test_falls_back_to_default_when_supabase_errors():
    with patch("backend.services.config.supabase.get_all_config",
               side_effect=RuntimeError("supabase down")):
        assert config.get("news.x", "fallback") == "fallback"


def test_cache_avoids_refetch_within_ttl():
    with patch("backend.services.config.supabase.get_all_config",
               return_value=_rows({"news.x": 1})) as m:
        config.get("news.x", None)
        config.get("news.x", None)
    assert m.call_count == 1
