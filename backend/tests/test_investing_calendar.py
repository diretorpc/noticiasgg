from pathlib import Path

import pytest

from backend.collectors import investing_calendar

FIXTURES = Path(__file__).parent / "fixtures"


def _page():
    return (FIXTURES / "investing_next_data.html").read_text(encoding="utf-8")


def test_parse_keeps_only_high_impact_with_actual():
    events = investing_calendar.parse(_page())
    names = [e["name"] for e in events]
    # FDI (alta+atual) e PIB Espanha (alta+atual) entram;
    # Desemprego (alta, sem atual) e Produção Industrial (baixa) ficam de fora.
    assert names == [
        "Investimento Estrangeiro Direto (USD) (Mai)",
        "PIB da Espanha (trimestral) (Q1)",
    ]


def test_parse_extracts_fields_and_flag():
    events = investing_calendar.parse(_page())
    fdi = events[0]
    assert fdi["event_id"] == "862"
    assert fdi["flag_emoji"] == "🇧🇷"
    assert fdi["importance"] == 3
    assert fdi["previous"] == "8,91B"
    assert fdi["forecast"] == "5,75B"
    assert fdi["actual"] == "7,97B"


def test_parse_blank_forecast_is_empty_string():
    events = investing_calendar.parse(_page())
    espanha = events[1]
    assert espanha["flag_emoji"] == "🇪🇸"
    assert espanha["forecast"] == ""
    assert espanha["actual"] == "0,6%"


def test_parse_missing_next_data_raises():
    with pytest.raises(ValueError):
        investing_calendar.parse("<html><body>Just a moment... Cloudflare</body></html>")


def test_parse_next_data_without_store_raises():
    body = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"state":{}}}}</script>'
    with pytest.raises(ValueError):
        investing_calendar.parse(body)


def test_parse_empty_calendar_is_normal_empty_list():
    body = ('<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"state":{"economicCalendarStore":{"calendarEventsByDate":{"2026-06-26":[]}}}}}}'
            '</script>')
    assert investing_calendar.parse(body) == []


def test_parse_skips_event_without_id():
    body = ('<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"state":{"economicCalendarStore":{"calendarEventsByDate":{"2026-06-26":'
            '[{"importance":"3","country":"Brazil","currencyFlag":"BR","event":"Sem ID","period":"(Mai)",'
            '"previous":"1%","forecast":"2%","actual":"3%"}]}}}}}}'
            '</script>')
    assert investing_calendar.parse(body) == []


def test_flag_emoji_edge_cases():
    assert investing_calendar._flag_emoji("") == ""
    assert investing_calendar._flag_emoji("USA") == ""
    assert investing_calendar._flag_emoji(None) == ""
