from unittest.mock import patch

from backend.collectors import news


def test_describe_config_reflects_override():
    def fake_get(key, default=None):
        overrides = {
            "news.sources_finance": ["reuters", "cnbc"],
            "news.finance_query": "custom query",
            "news.rss_feeds": [{"nome": "Meu Feed", "url": "https://x.com/rss"}],
        }
        return overrides.get(key, default)

    with patch("backend.collectors.news.config.get", side_effect=fake_get):
        cfg = news.describe_config()

    assert cfg["sources_finance"] == ["reuters", "cnbc"]
    assert cfg["finance_query"] == "custom query"
    assert cfg["rss_feeds"] == [{"nome": "Meu Feed", "url": "https://x.com/rss"}]


def test_describe_config_uses_defaults_when_no_override():
    with patch("backend.collectors.news.config.get", side_effect=lambda k, d=None: d):
        cfg = news.describe_config()
    assert "reuters" in cfg["sources_finance"]
    assert "inflation" in cfg["finance_query"]
    assert any(f["nome"] == "MIT Technology Review" for f in cfg["rss_feeds_ai"])


def test_feeds_helper_converts_config_dicts_to_tuples():
    with patch("backend.collectors.news.config.get",
               return_value=[{"nome": "F", "url": "https://f.com/rss"}]):
        assert news._feeds("rss_feeds", []) == [("F", "https://f.com/rss")]


def test_feeds_helper_falls_back_on_empty_config():
    with patch("backend.collectors.news.config.get", return_value=None):
        assert news._feeds("rss_feeds", [("D", "https://d.com")]) == [("D", "https://d.com")]
