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
