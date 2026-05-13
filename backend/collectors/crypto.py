from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter()

COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=10&page=1"
    "&price_change_percentage=24h"
)


def collect() -> list[dict]:
    with httpx.Client(timeout=15) as client:
        resp = client.get(COINGECKO_URL)
        resp.raise_for_status()
        coins = resp.json()

    return [
        {
            "nome": c["name"],
            "simbolo": c["symbol"].upper(),
            "preco_usd": c["current_price"],
            "variacao_24h_pct": round(c.get("price_change_percentage_24h") or 0, 2),
            "market_cap_usd": c["market_cap"],
        }
        for c in coins
    ]


@router.get("/api/collectors/crypto")
async def get_crypto():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
