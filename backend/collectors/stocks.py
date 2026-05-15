import math
import os
import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

YF_URLS = [
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d",
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d",
]


def _safe_float(val):
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def _fetch_brapi(ticker: str) -> dict | None:
    token = os.environ.get("BRAPI_TOKEN", "")
    if not token:
        return None
    try:
        url = f"https://brapi.dev/api/quote/{ticker}?fundamental=true&token={token}"
        r = httpx.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return None
        d = results[0]
        preco = _safe_float(d.get("regularMarketPrice"))
        if not preco:
            return None
        anterior = _safe_float(d.get("regularMarketPreviousClose"))
        variacao_pct = _safe_float(d.get("regularMarketChangePercent"))
        variacao_abs = _safe_float(d.get("regularMarketChange"))
        return {
            "ticker": ticker,
            "nome": d.get("longName") or d.get("shortName") or ticker,
            "preco": round(preco, 2),
            "moeda": d.get("currency", "BRL"),
            "variacao_pct": round(variacao_pct, 2) if variacao_pct else None,
            "variacao_abs": round(variacao_abs, 2) if variacao_abs else None,
            "abertura": _safe_float(d.get("regularMarketOpen")),
            "max_dia": _safe_float(d.get("regularMarketDayHigh")),
            "min_dia": _safe_float(d.get("regularMarketDayLow")),
            "max_52s": _safe_float(d.get("fiftyTwoWeekHigh")),
            "min_52s": _safe_float(d.get("fiftyTwoWeekLow")),
            "volume": d.get("regularMarketVolume"),
            "market_cap": d.get("marketCap"),
            "pl": _safe_float(d.get("priceEarnings")),
            "lpa": _safe_float(d.get("earningsPerShare")),
        }
    except Exception:
        return None


def _fetch_yahoo(ticker: str) -> dict | None:
    with httpx.Client(timeout=15) as client:
        for url_template in YF_URLS:
            try:
                url = url_template.format(symbol=ticker)
                resp = client.get(url, headers=HEADERS, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                result = data["chart"]["result"]
                if not result:
                    continue
                meta = result[0]["meta"]
                atual = _safe_float(meta.get("regularMarketPrice"))
                anterior = _safe_float(meta.get("previousClose") or meta.get("chartPreviousClose"))
                if not atual:
                    continue
                variacao_pct = None
                variacao_abs = None
                if anterior:
                    variacao_pct = round(((atual - anterior) / anterior) * 100, 2)
                    variacao_abs = round(atual - anterior, 2)
                return {
                    "ticker": ticker,
                    "nome": meta.get("longName") or meta.get("shortName") or ticker,
                    "preco": round(atual, 2),
                    "moeda": meta.get("currency", ""),
                    "variacao_pct": variacao_pct,
                    "variacao_abs": variacao_abs,
                    "max_dia": _safe_float(meta.get("regularMarketDayHigh")),
                    "min_dia": _safe_float(meta.get("regularMarketDayLow")),
                    "max_52s": _safe_float(meta.get("fiftyTwoWeekHigh")),
                    "min_52s": _safe_float(meta.get("fiftyTwoWeekLow")),
                    "volume": meta.get("regularMarketVolume"),
                    "market_cap": meta.get("marketCap"),
                }
            except Exception:
                continue
    return None


def get_stock_data(ticker: str) -> dict:
    """Busca dados em tempo real de uma ação. Usa brapi.dev para BR, Yahoo Finance para internacionais."""
    # Remove .SA se vier — brapi.dev usa ticker puro (RAIZ4, não RAIZ4.SA)
    clean = ticker.upper().removesuffix(".SA")

    # Tenta brapi.dev primeiro (melhor cobertura para B3)
    result = _fetch_brapi(clean)
    if result:
        return result

    # Fallback: Yahoo Finance com .SA para ações BR (formato LETRAS+DÍGITO)
    import re as _re
    is_br = bool(_re.match(r"^[A-Z]{3,5}\d{1,2}$", clean))
    for yf_ticker in ([f"{clean}.SA", clean] if is_br else [ticker]):
        result = _fetch_yahoo(yf_ticker)
        if result:
            return result

    return {"ticker": ticker, "erro": "Ativo não encontrado ou indisponível"}
