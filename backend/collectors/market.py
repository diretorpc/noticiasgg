from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import yfinance as yf

router = APIRouter()

TICKERS = {
    "bolsas": {
        "IBOVESPA": "^BVSP",
        "S&P 500": "SPY",
        "NASDAQ": "QQQ",
        "Dow Jones": "DIA",
    },
    "cambio": {
        "USD/BRL": "USDBRL=X",
        "EUR/BRL": "EURBRL=X",
    },
    "commodities": {
        "Ouro": "GC=F",
        "Petroleo": "CL=F",
        "Soja": "ZS=F",
    },
}


def _fetch_ticker(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    hist = t.history(period="2d")
    if hist.empty:
        return {"preco": None, "variacao_pct": None}

    closes = hist["Close"].dropna()
    if len(closes) < 2:
        return {"preco": round(float(closes.iloc[-1]), 2), "variacao_pct": None}

    atual = float(closes.iloc[-1])
    anterior = float(closes.iloc[-2])
    variacao = ((atual - anterior) / anterior) * 100
    return {"preco": round(atual, 2), "variacao_pct": round(variacao, 2)}


def collect() -> dict:
    resultado = {}
    for categoria, ativos in TICKERS.items():
        resultado[categoria] = {}
        for nome, symbol in ativos.items():
            resultado[categoria][nome] = _fetch_ticker(symbol)
    return resultado


@router.get("/api/collectors/market")
async def get_market():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
