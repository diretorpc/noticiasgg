from datetime import datetime, timezone
import math
from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter()

SYMBOLS = {
    "^BVSP":    ("bolsas", "IBOVESPA"),
    "SPY":      ("bolsas", "S&P 500"),
    "^IXIC":    ("bolsas", "NASDAQ"),
    "^NYA":     ("bolsas", "NYSE"),
    "000001.SS":("bolsas", "Shanghai (SSE)"),
    "^N100":    ("bolsas", "Euronext 100"),
    "^N225":    ("bolsas", "JPX (Nikkei 225)"),
    "USDBRL=X": ("cambio", "USD/BRL"),
    "EURBRL=X": ("cambio", "EUR/BRL"),
}

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


def _fetch_symbol(client: httpx.Client, symbol: str) -> dict:
    last_err = None
    for url_template in YF_URLS:
        try:
            url = url_template.format(symbol=symbol)
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
            variacao = None
            if anterior:
                variacao = round(((atual - anterior) / anterior) * 100, 2)
            return {"preco": round(atual, 2), "variacao_pct": variacao}
        except httpx.HTTPStatusError as e:
            last_err = f"HTTP {e.response.status_code}"
        except Exception as e:
            last_err = str(e)
    return {"preco": None, "variacao_pct": None, "erro": last_err}


def collect() -> dict:
    resultado: dict = {"bolsas": {}, "cambio": {}, "commodities": {}}
    with httpx.Client(timeout=15) as client:
        for symbol, (categoria, nome) in SYMBOLS.items():
            try:
                resultado[categoria][nome] = _fetch_symbol(client, symbol)
            except Exception as e:
                resultado[categoria][nome] = {"preco": None, "variacao_pct": None, "erro": str(e)}
    return resultado


@router.get("/api/collectors/market")
async def get_market():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
