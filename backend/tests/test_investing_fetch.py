import os

import httpx
import pytest

from backend.collectors import investing_calendar


@pytest.mark.skipif(not os.getenv("SCRAPER_API_KEY"), reason="SCRAPER_API_KEY não configurada")
def test_fetch_returns_parseable_calendar():
    html = investing_calendar.fetch()
    # Não deve levantar: ou tem eventos de alto impacto agora, ou lista vazia (normal).
    events = investing_calendar.parse(html)
    assert isinstance(events, list)


def test_fetch_without_key_raises(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    with pytest.raises(ValueError):
        investing_calendar.fetch()


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass


def _fake_client_factory(behaviors: list, calls: list):
    """behaviors: exceção a levantar ou texto a devolver, um por chamada."""

    class _FakeClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, params=None):
            behavior = behaviors[len(calls) - 1]
            if isinstance(behavior, Exception):
                raise behavior
            return _FakeResponse(behavior)

    return _FakeClient


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(investing_calendar.time, "sleep", lambda _: None)


def test_fetch_retries_once_after_timeout(monkeypatch, no_sleep):
    monkeypatch.setenv("SCRAPER_API_KEY", "k")
    calls: list = []
    monkeypatch.setattr(investing_calendar.httpx, "Client", _fake_client_factory(
        [httpx.ReadTimeout("The read operation timed out"), "<html>ok</html>"], calls))

    assert investing_calendar.fetch() == "<html>ok</html>"
    assert len(calls) == 2


def test_fetch_raises_after_second_timeout(monkeypatch, no_sleep):
    monkeypatch.setenv("SCRAPER_API_KEY", "k")
    calls: list = []
    monkeypatch.setattr(investing_calendar.httpx, "Client", _fake_client_factory(
        [httpx.ReadTimeout("timeout 1"), httpx.ReadTimeout("timeout 2")], calls))

    with pytest.raises(httpx.TimeoutException):
        investing_calendar.fetch()
    assert len(calls) == 2


def test_fetch_does_not_retry_on_http_error(monkeypatch, no_sleep):
    """403/500 do ScraperAPI não é lentidão — repetir só gasta crédito."""
    monkeypatch.setenv("SCRAPER_API_KEY", "k")
    calls: list = []
    monkeypatch.setattr(investing_calendar.httpx, "Client", _fake_client_factory(
        [httpx.HTTPStatusError("403", request=None, response=None)], calls))

    with pytest.raises(httpx.HTTPStatusError):
        investing_calendar.fetch()
    assert len(calls) == 1


def test_fetch_waits_at_least_70s(monkeypatch, no_sleep):
    """ScraperAPI pede até 70s para devolver a página; 60s ficava abaixo disso."""
    monkeypatch.setenv("SCRAPER_API_KEY", "k")
    calls: list = []
    monkeypatch.setattr(investing_calendar.httpx, "Client",
                        _fake_client_factory(["<html>ok</html>"], calls))

    investing_calendar.fetch()
    assert calls[0]["timeout"] >= 70
