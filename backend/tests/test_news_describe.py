from backend.collectors import news


def test_news_describe_config_sources_and_feeds():
    cfg = news.describe_config()
    assert "reuters" in cfg["sources_finance"]
    assert "techcrunch" in cfg["sources_tech"]
    assert isinstance(cfg["finance_query"], str) and "inflation" in cfg["finance_query"]
    assert cfg["rss_feeds"][0]["nome"] and cfg["rss_feeds"][0]["url"].startswith("http")
    assert any(f["nome"] == "MIT Technology Review" for f in cfg["rss_feeds_ai"])
