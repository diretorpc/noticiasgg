from types import SimpleNamespace
from unittest.mock import patch

from backend.collectors import news

_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Manchete A</title><link>https://x.com/a</link></item>
<item><title>Manchete B</title><link>https://x.com/b</link></item>
</channel></rss>"""

_RSS_EMPTY = b"""<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""

_ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom Title</title></entry></feed>"""


def test_parse_feed_valid_rss():
    r = news._parse_feed(_RSS)
    assert r["valid"] is True
    assert r["item_count"] == 2
    assert r["sample_title"] == "Manchete A"
    assert r["error"] is None


def test_parse_feed_atom_entry():
    r = news._parse_feed(_ATOM)
    assert r["valid"] is True
    assert r["item_count"] == 1
    assert r["sample_title"] == "Atom Title"


def test_parse_feed_empty_is_invalid():
    r = news._parse_feed(_RSS_EMPTY)
    assert r["valid"] is False
    assert r["item_count"] == 0


def test_parse_feed_non_xml_is_invalid():
    r = news._parse_feed(b"definitely not xml")
    assert r["valid"] is False
    assert r["error"]


def test_validate_feed_handles_http_error():
    with patch("backend.collectors.news.httpx.get",
               return_value=SimpleNamespace(status_code=404, content=b"")):
        r = news.validate_feed("https://nope.com/rss")
    assert r["valid"] is False
    assert "404" in r["error"]


def test_validate_feed_valid_url():
    with patch("backend.collectors.news.httpx.get",
               return_value=SimpleNamespace(status_code=200, content=_RSS)):
        r = news.validate_feed("https://x.com/rss")
    assert r["valid"] is True
    assert r["item_count"] == 2
