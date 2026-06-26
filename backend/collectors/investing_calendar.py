import json
import logging
import os
import re

import httpx

logger = logging.getLogger("noticiasgg.investing")

_SCRAPER_URL = "https://api.scraperapi.com/"
_PAGE_URL = "https://br.investing.com/economic-calendar/"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def fetch() -> str:
    key = os.environ.get("SCRAPER_API_KEY", "")
    if not key:
        raise ValueError("SCRAPER_API_KEY não configurada")
    with httpx.Client(timeout=60) as client:
        r = client.get(_SCRAPER_URL, params={"api_key": key, "url": _PAGE_URL})
        r.raise_for_status()
        return r.text


def _flag_emoji(country_code: str) -> str:
    cc = (country_code or "").strip().upper()
    if len(cc) != 2 or not cc.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in cc)


def _next_data(html: str) -> dict:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("investing: __NEXT_DATA__ não encontrado (bloqueio ou layout mudou)")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"investing: __NEXT_DATA__ inválido: {e}") from e


def _events_by_date(html: str) -> dict:
    data = _next_data(html)
    try:
        return data["props"]["pageProps"]["state"]["economicCalendarStore"]["calendarEventsByDate"]
    except (KeyError, TypeError) as e:
        raise ValueError(f"investing: estrutura do calendário ausente: {e}") from e


def parse(html: str) -> list[dict]:
    by_date = _events_by_date(html)
    events: list[dict] = []
    for day_events in by_date.values():
        for e in day_events:
            actual = (e.get("actual") or "").strip()
            if str(e.get("importance")) != "3" or not actual:
                continue
            if not e.get("eventId"):
                logger.warning("investing: evento sem eventId, pulando: %s", e.get("event"))
                continue
            name = (e.get("event") or "").strip()
            period = (e.get("period") or "").strip()
            if period:
                name = f"{name} {period}"
            events.append({
                "event_id": str(e["eventId"]),
                "country": (e.get("country") or "").strip(),
                "flag_emoji": _flag_emoji(e.get("currencyFlag")),
                "name": name,
                "importance": 3,
                "previous": (e.get("previous") or "").strip(),
                "forecast": (e.get("forecast") or "").strip(),
                "actual": actual,
            })
    return events
