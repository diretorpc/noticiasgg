from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import yfinance as yf

router = APIRouter()

# Todos os tickers numa única chamada para minimizar latência
ALL_SYMBOLS = ["^BVSP", "SPY", "QQQ", "DIA", "USDBRL=X", "EURBRL=X", "GC=F", "CL=F", "ZS=F"]

MAPA = {
    "^BVSP":    ("bolsas",      "IBOVESPA"),
    "SPY":      ("bolsas",      "S&P 500"),
    "QQQ":      ("bolsas",      "NASDAQ"),
    "DIA":      ("bolsas",      "Dow Jones"),
    "USDBRL=X": ("cambio",      "USD/BRL"),
    "EURBRL=X": ("cambio",      "EUR/BRL"),
    "GC=F":     ("commodities", "Ouro"),
    "CL=F":     ("commodities", "Petroleo"),
    "ZS=F":     ("commodities", "Soja"),
}


def collect() -> dict:
    # Download em lote — uma única requisição HTTP para todos os tickers
    df = yf.download(
        tickers=" ".join(ALL_SYMBOLS),
        period="2d",
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    resultado: dict = {"bolsas": {}, "cambio": {}, "commodities": {}}

    for symbol in ALL_SYMBOLS:
        categoria, nome = MAPA[symbol]
        try:
            closes = df[symbol]["Close"].dropna() if len(ALL_SYMBOLS) > 1 else df["Close"].dropna()
            if closes.empty:
                resultado[categoria][nome] = {"preco": None, "variacao_pct": None}
                continue
            atual = float(closes.iloc[-1])
            variacao = None
            if len(closes) >= 2:
                anterior = float(closes.iloc[-2])
                variacao = round(((atual - anterior) / anterior) * 100, 2)
            resultado[categoria][nome] = {"preco": round(atual, 2), "variacao_pct": variacao}
        except Exception:
            resultado[categoria][nome] = {"preco": None, "variacao_pct": None}

    return resultado


@router.get("/api/collectors/market")
async def get_market():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
