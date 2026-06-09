from datetime import datetime, timezone
import math
import os
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
import httpx
from fastapi import APIRouter, HTTPException

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
    "DX-Y.NYB": ("cambio", "DXY (Índice Dólar)"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

YF_V8 = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
YF_V8_ALT = "https://query2.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"


def _safe_float(val):
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def _parse_v8_meta(meta: dict) -> dict | None:
    atual = _safe_float(meta.get("regularMarketPrice"))
    anterior = _safe_float(meta.get("previousClose") or meta.get("chartPreviousClose"))
    if not atual:
        return None
    variacao = round(((atual - anterior) / anterior) * 100, 2) if anterior else None
    return {"preco": round(atual, 2), "variacao_pct": variacao}


def _fetch_direct_one(sym: str) -> tuple[str, dict | None]:
    """Yahoo Finance v8 direto (sem ScraperAPI). Tenta query1 depois query2."""
    sym_enc = urllib.parse.quote(sym, safe="")
    for tpl in (YF_V8, YF_V8_ALT):
        try:
            url = tpl.format(sym=sym_enc)
            r = httpx.get(url, headers=HEADERS, timeout=12)
            if r.status_code != 200:
                continue
            result = r.json().get("chart", {}).get("result") or []
            if not result:
                continue
            data = _parse_v8_meta(result[0]["meta"])
            if data:
                return sym, data
        except Exception:
            continue
    return sym, None


def _fetch_all_direct(symbols: list[str]) -> dict:
    """Busca todos os símbolos via Yahoo Finance v8 em paralelo (sem créditos)."""
    resultado = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_fetch_direct_one, sym): sym for sym in symbols}
        try:
            for future in as_completed(futures, timeout=20):
                sym, data = future.result()
                if data:
                    resultado[sym] = data
        except (FuturesTimeout, Exception):
            pass
    return resultado


def _fetch_via_scraperapi(symbol: str) -> dict:
    """Busca um símbolo via ScraperAPI + Yahoo Finance v8 (premium). Fallback."""
    key = os.environ.get("SCRAPER_API_KEY", "")
    if not key:
        return {"preco": None, "variacao_pct": None, "erro": "sem chave ScraperAPI"}
    sym_enc = urllib.parse.quote(symbol, safe="")
    target = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym_enc}?interval=1d&range=1d"
    url = f"http://api.scraperapi.com?api_key={key}&premium=true&url={urllib.parse.quote(target)}"
    try:
        r = httpx.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        result = r.json().get("chart", {}).get("result") or []
        if not result:
            return {"preco": None, "variacao_pct": None, "erro": "sem dados"}
        data = _parse_v8_meta(result[0]["meta"])
        return data if data else {"preco": None, "variacao_pct": None, "erro": "sem dados"}
    except Exception as e:
        return {"preco": None, "variacao_pct": None, "erro": str(e)}


def _fetch_all_scraperapi(missing_symbols: dict) -> dict:
    """Busca múltiplos símbolos via ScraperAPI em paralelo (máx 3 simultâneos)."""
    resultado = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(_fetch_via_scraperapi, sym): (sym, cat, nom)
            for sym, (cat, nom) in missing_symbols.items()
        }
        for future in as_completed(futures, timeout=50):
            sym, cat, nom = futures[future]
            try:
                resultado[(cat, nom)] = future.result()
            except Exception as e:
                resultado[(cat, nom)] = {"preco": None, "variacao_pct": None, "erro": str(e)}
    return resultado


def collect() -> dict:
    resultado: dict = {"bolsas": {}, "cambio": {}}

    # Tentativa 1: Yahoo Finance v8 direto — regularMarketPrice (tempo real, 0 créditos)
    try:
        direct = _fetch_all_direct(list(SYMBOLS.keys()))
        for sym, data in direct.items():
            categoria, nome = SYMBOLS[sym]
            resultado[categoria][nome] = data
    except Exception:
        pass

    # Tentativa 2: ScraperAPI para símbolos que falharam no direto
    missing = {
        sym: (cat, nom)
        for sym, (cat, nom) in SYMBOLS.items()
        if nom not in resultado[cat]
    }
    if missing:
        fallback = _fetch_all_scraperapi(missing)
        for (cat, nom), data in fallback.items():
            resultado[cat][nom] = data

    return resultado


@router.get("/api/collectors/market")
async def get_market():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
