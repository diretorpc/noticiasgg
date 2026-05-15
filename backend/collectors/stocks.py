import math
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


def get_stock_data(ticker: str) -> dict:
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
                    "volume": meta.get("regularMarketVolume"),
                    "max_dia": _safe_float(meta.get("regularMarketDayHigh")),
                    "min_dia": _safe_float(meta.get("regularMarketDayLow")),
                    "max_52s": _safe_float(meta.get("fiftyTwoWeekHigh")),
                    "min_52s": _safe_float(meta.get("fiftyTwoWeekLow")),
                    "market_cap": meta.get("marketCap"),
                }
            except Exception:
                continue

    return {"ticker": ticker, "erro": "Ativo não encontrado ou indisponível"}
