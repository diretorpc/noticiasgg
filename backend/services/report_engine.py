import datetime as _dt
import json
import logging
import os

from backend.collectors import (
    market, crypto, indicators_us, indicators_br, news,
    commodities_br, politics_br, polls_br,
)
from backend.services import report_prompts, integrity

logger = logging.getLogger("noticiasgg")

_ANTHROPIC_TIMEOUT = 90.0
TEXT_SECTIONS = ("noticias", "analise", "politica")

_MAX_TOKENS = {
    "commodities": 1024, "bolsas": 1024, "cambio_cripto": 1024,
    "noticias": 1024, "analise": 1500, "politica": 1200,
}


def _safe_dict(val) -> dict:
    return val if isinstance(val, dict) and "erro" not in val else {}


def _safe_list(val) -> list:
    return val if isinstance(val, list) else []


def adapt_bolsas(market_out: dict) -> dict:
    return {"data": {"bolsas": _safe_dict(market_out).get("bolsas", {})}}


def adapt_commodities(comm_out: dict) -> dict:
    return {"data": {"commodities": _safe_dict(comm_out)}}


def adapt_cambio_cripto(market_out: dict, crypto_out: list) -> dict:
    return {"data": {
        "cambio": _safe_dict(market_out).get("cambio", {}),
        "cripto": _safe_list(crypto_out),
    }}


def adapt_noticias(news_out: list) -> dict:
    return {"data": {"noticias": _safe_list(news_out)}}


def adapt_analise(market_out: dict, crypto_out: list, ind_br: dict,
                  ind_us: dict, news_out: list) -> dict:
    m = _safe_dict(market_out)
    return {"data": {
        "bolsas": m.get("bolsas", {}),
        "cambio": m.get("cambio", {}),
        "cripto": _safe_list(crypto_out),
        "indicadores_br": _safe_dict(ind_br),
        "indicadores_us": _safe_dict(ind_us),
        "noticias": _safe_list(news_out),
    }}


def adapt_politica(politics_out: list, polls_out: list) -> dict:
    return {"data": {
        "politica": _safe_list(politics_out),
        "pesquisas": _safe_list(polls_out),
    }}


def _safe_collect(fn):
    try:
        return fn()
    except Exception as e:
        return {"erro": str(e)}


def _collect(section: str) -> dict:
    if section == "bolsas":
        return adapt_bolsas(_safe_collect(market.collect))
    if section == "commodities":
        return adapt_commodities(_safe_collect(commodities_br.collect))
    if section == "cambio_cripto":
        return adapt_cambio_cripto(_safe_collect(market.collect), _safe_collect(crypto.collect))
    if section == "noticias":
        return adapt_noticias(_safe_collect(news.collect))
    if section == "analise":
        return adapt_analise(
            _safe_collect(market.collect), _safe_collect(crypto.collect),
            _safe_collect(indicators_br.collect), _safe_collect(indicators_us.collect),
            _safe_collect(news.collect),
        )
    if section == "politica":
        return adapt_politica(_safe_collect(politics_br.collect), _safe_collect(polls_br.collect))
    raise KeyError(section)


def _render(section: str, ctx: dict, client) -> str:
    prompt = report_prompts.get_prompt(section)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=_MAX_TOKENS[section],
        system=prompt,
        messages=[{"role": "user",
                   "content": json.dumps(ctx, ensure_ascii=False, default=str)}],
    )
    text = ""
    for block in resp.content:
        if hasattr(block, "text"):
            text = block.text
            break
    if section in TEXT_SECTIONS:
        text = integrity.validate_and_fix(text, ctx.get("data", {}), client)
    return text


_SECTION_ORDER = ("commodities", "bolsas", "cambio_cripto", "noticias", "analise", "politica")
DEFAULT_SECTIONS = {s: True for s in _SECTION_ORDER}

_BRT = _dt.timezone(_dt.timedelta(hours=-3))


def _current_greeting() -> str:
    h = _dt.datetime.now(_BRT).hour
    if 5 <= h < 12:
        return "Bom dia"
    if h < 18:
        return "Boa tarde"
    return "Boa noite"


def _greeting_header(user: dict) -> str:
    data = _dt.datetime.now(_BRT).strftime("%d/%m/%Y")
    nome = (user.get("name") or "").strip()
    saud = _current_greeting()
    if nome:
        return f"{saud}, *{nome.split()[0]}*! | {data}"
    return f"{saud}! | {data}"


def generate_sections(sections: dict | None, user: dict, client=None) -> list[str]:
    if client is None:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                           timeout=_ANTHROPIC_TIMEOUT, max_retries=1)
    active = sections if sections is not None else DEFAULT_SECTIONS
    messages: list[str] = []
    for section in _SECTION_ORDER:
        if not active.get(section):
            continue
        try:
            ctx = _collect(section)
            text = _render(section, ctx, client)
            if text and text.strip():
                messages.append(text.strip())
        except Exception:
            logger.exception("report_engine: seção falhou: %s", section)
    if messages:
        messages[0] = f"{_greeting_header(user)}\n\n{messages[0]}"
    return messages
