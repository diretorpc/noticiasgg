from datetime import datetime, timezone
import math
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()

HEADERS_JSON = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}

YF_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
YF_URL_FALLBACK = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
NA_BASE = "https://www.noticiasagricolas.com.br"

# (símbolo, unidade, moeda)
CBOT_SYMBOLS = {
    "Soja CBOT":         ("ZS=F",  "USc/bushel", "USD"),
    "Farelo Soja CBOT":  ("ZM=F",  "USD/ton",    "USD"),
    "Oleo Soja CBOT":    ("ZL=F",  "USc/lb",     "USD"),
    "Milho CBOT":        ("ZC=F",  "USc/bushel", "USD"),
    "Trigo CBOT":        ("ZW=F",  "USc/bushel", "USD"),
    "Algodao ICE":       ("CT=F",  "USc/lb",     "USD"),
    "Cafe Arabica ICE":  ("KC=F",  "USc/lb",     "USD"),
    "Acucar ICE":        ("SB=F",  "USc/lb",     "USD"),
    "Cacau ICE":         ("CC=F",  "USD/ton",    "USD"),
    "Suco Laranja ICE":  ("OJ=F",  "USc/lb",     "USD"),
    "Boi Gordo CME":     ("GF=F",  "USD/cwt",    "USD"),
    "Boi Vivo CME":      ("LE=F",  "USD/cwt",    "USD"),
    "Suino CME":         ("LH=F",  "USD/cwt",    "USD"),
    "Aveia CBOT":        ("ZO=F",  "USc/bushel", "USD"),
    "Arroz CBOT":        ("ZR=F",  "USD/cwt",    "USD"),
}


def _safe_float(val):
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return None


def _parse_br_float(texto: str) -> float | None:
    try:
        return float(texto.strip().replace(".", "").replace(",", ".").replace("+", ""))
    except Exception:
        return None


def _fetch_yahoo(client: httpx.Client, symbol: str, unidade: str, moeda: str) -> dict:
    last_err = None
    for url_tpl in [YF_URL, YF_URL_FALLBACK]:
        try:
            resp = client.get(url_tpl.format(symbol=symbol), headers=HEADERS_JSON, timeout=15)
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
            variacao = round(((atual - anterior) / anterior) * 100, 2) if anterior else None
            return {"preco": round(atual, 2), "variacao_pct": variacao, "moeda": moeda, "unidade": unidade}
        except httpx.HTTPStatusError as e:
            last_err = f"HTTP {e.response.status_code}"
        except Exception as e:
            last_err = str(e)
    return {"preco": None, "variacao_pct": None, "erro": last_err, "moeda": moeda, "unidade": unidade}


def collect_commodities_cbot() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for nome, (symbol, unidade, moeda) in CBOT_SYMBOLS.items():
            resultado[nome] = _fetch_yahoo(client, symbol, unidade, moeda)
    return resultado


CATEGORIA_MAP = {
    "commodities_cbot": collect_commodities_cbot,
}


def collect(categoria: str | None = None) -> dict:
    if categoria and categoria in CATEGORIA_MAP:
        return {categoria: CATEGORIA_MAP[categoria]()}
    return {k: fn() for k, fn in CATEGORIA_MAP.items()}


@router.get("/api/collectors/agro-br")
async def get_agro_br(categoria: str | None = None):
    try:
        data = collect(categoria)
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
