import os

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
