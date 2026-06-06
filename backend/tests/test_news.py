import pytest
import os
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.collectors.news import (
    _parse_rss_date, _collect_rss, _is_fresh,
    SOURCES_FINANCE, SOURCES_TECH, _AI_QUERY, _RSS_FEEDS_AI,
)

client = TestClient(app)


def _fresh_rss() -> bytes:
    now = datetime.now(timezone.utc)
    d1 = format_datetime(now - timedelta(hours=1))
    d2 = format_datetime(now - timedelta(hours=2))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Global economy slows</title>
      <link>https://example.com/article-1</link>
      <pubDate>{d1}</pubDate>
      <description>Economy slowdown hits markets.</description>
    </item>
    <item>
      <title>Markets rally on Fed pause</title>
      <link>https://example.com/article-2</link>
      <pubDate>{d2}</pubDate>
      <description>Fed holds rates steady.</description>
    </item>
  </channel>
</rss>""".encode()


def test_news_sem_chave_retorna_500():
    with patch.dict(os.environ, {"NEWS_API_KEY": ""}):
        resp = client.get("/api/collectors/news")
        assert resp.status_code == 500


def test_news_schema_com_chave():
    if not os.getenv("NEWS_API_KEY"):
        pytest.skip("NEWS_API_KEY não configurada")
    resp = client.get("/api/collectors/news")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "collected_at" in body


def test_news_retorna_lista_com_chave():
    if not os.getenv("NEWS_API_KEY"):
        pytest.skip("NEWS_API_KEY não configurada")
    data = client.get("/api/collectors/news").json()["data"]
    assert isinstance(data, list)


def test_news_campos_obrigatorios_com_chave():
    if not os.getenv("NEWS_API_KEY"):
        pytest.skip("NEWS_API_KEY não configurada")
    artigos = client.get("/api/collectors/news").json()["data"]
    for a in artigos:
        assert "titulo" in a
        assert "fonte" in a
        assert "url" in a


def test_parse_rss_date_rfc2822():
    result = _parse_rss_date("Mon, 02 Jun 2026 10:00:00 +0000")
    assert result is not None
    assert "2026" in result


def test_parse_rss_date_none():
    assert _parse_rss_date(None) is None


def test_parse_rss_date_invalid():
    # data inválida → retorna None
    assert _parse_rss_date("not-a-date") is None


def test_collect_rss_parses_items():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = _fresh_rss()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    feeds = [("Test Source", "https://example.com/rss")]
    vistos: set = set()
    artigos = _collect_rss(mock_client, feeds, vistos)

    assert len(artigos) == 2
    assert artigos[0]["fonte"] == "Test Source"
    assert artigos[0]["titulo"] == "Global economy slows"
    assert artigos[0]["url"] == "https://example.com/article-1"


def test_collect_rss_deduplicates():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = _fresh_rss()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    feeds = [("Test Source", "https://example.com/rss")]
    vistos = {"https://example.com/article-1"}  # já visto
    artigos = _collect_rss(mock_client, feeds, vistos)

    assert len(artigos) == 1
    assert artigos[0]["url"] == "https://example.com/article-2"


def test_collect_rss_ignora_erro_http():
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    artigos = _collect_rss(mock_client, [("Bad Feed", "https://bad.url/rss")], set())
    assert artigos == []


def test_collect_rss_ignora_xml_invalido():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"not xml at all"

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    artigos = _collect_rss(mock_client, [("Bad XML", "https://bad.url/rss")], set())
    assert artigos == []


def test_sources_finance_contem_novas_fontes():
    for source in ("associated-press", "the-washington-post", "business-insider", "politico"):
        assert source in SOURCES_FINANCE


def test_sources_tech_contem_fontes_ia():
    for source in ("techcrunch", "wired", "the-verge", "ars-technica"):
        assert source in SOURCES_TECH


def test_ai_query_contem_termos_relevantes():
    for term in ("artificial intelligence", "OpenAI", "Anthropic", "LLM"):
        assert term in _AI_QUERY


def test_rss_feeds_ai_contem_mit_e_venturebeat():
    nomes = [nome for nome, _ in _RSS_FEEDS_AI]
    assert "MIT Technology Review" in nomes
    assert "VentureBeat AI" in nomes


def test_collect_rss_multiplos_feeds_deduplicados():
    """Dois feeds com a mesma URL em artigos distintos — sem duplicata."""
    now = datetime.now(timezone.utc)
    d = format_datetime(now - timedelta(hours=1))

    def _rss(link: str, title: str) -> bytes:
        return f"""<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>{title}</title><link>{link}</link><pubDate>{d}</pubDate></item>
        </channel></rss>""".encode()

    responses = [
        MagicMock(status_code=200, content=_rss("https://example.com/a1", "AI news 1")),
        MagicMock(status_code=200, content=_rss("https://example.com/a1", "AI news 1")),  # duplicada
        MagicMock(status_code=200, content=_rss("https://example.com/a2", "AI news 2")),
    ]
    mock_client = MagicMock()
    mock_client.get.side_effect = responses

    feeds = [
        ("Feed A", "https://feed-a.com/rss"),
        ("Feed B", "https://feed-b.com/rss"),
        ("Feed C", "https://feed-c.com/rss"),
    ]
    artigos = _collect_rss(mock_client, feeds, set())
    urls = [a["url"] for a in artigos]
    assert len(urls) == len(set(urls)), "URLs duplicadas encontradas"
