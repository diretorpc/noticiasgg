import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Série FRED → nome legível
SERIES = {
    "CPIAUCSL": "CPI (inflação EUA)",
    "PPIACO": "PPI (preços ao produtor)",
    "UNRATE": "Taxa de desemprego EUA",
    "DFF": "Fed Funds Rate (juros EUA)",
}


def _fetch_series(series_id: str, api_key: str) -> dict:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 2,
    }
    with httpx.Client(timeout=15) as client:
        resp = client.get(FRED_BASE, params=params)
        resp.raise_for_status()
        obs = resp.json().get("observations", [])

    if not obs:
        return {"valor": None, "data": None, "variacao": None}

    atual = obs[0]
    valor_atual = float(atual["value"]) if atual["value"] != "." else None

    variacao = None
    if len(obs) >= 2 and obs[1]["value"] != ".":
        valor_anterior = float(obs[1]["value"])
        if valor_anterior and valor_atual is not None:
            variacao = round(valor_atual - valor_anterior, 4)

    return {
        "valor": valor_atual,
        "data": atual["date"],
        "variacao": variacao,
    }


def collect() -> dict:
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key:
        raise ValueError("FRED_API_KEY não configurada")

    resultado = {}
    for series_id, nome in SERIES.items():
        resultado[nome] = _fetch_series(series_id, api_key)
    return resultado


@router.get("/api/collectors/indicators-us")
async def get_indicators_us():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
