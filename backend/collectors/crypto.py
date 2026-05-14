from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter()

COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&ids=bitcoin,ethereum,tether"
    "&price_change_percentage=24h"
)


def collect() -> list[dict]:
    with httpx.Client(timeout=15) as client:
        resp = client.get(COINGECKO_URL)
        resp.raise_for_status()
        coins = resp.json()

    coins_map = {c["id"]: c for c in coins}
    result = []

    usdt = coins_map.get("tether")
    if usdt:
        result.append({
            "nome": "Tether",
            "simbolo": "USDT",
            "volume_24h_usd": usdt.get("total_volume"),
        })

    for coin_id in ["bitcoin", "ethereum"]:
        c = coins_map.get(coin_id)
        if c:
            result.append({
                "nome": c["name"],
                "simbolo": c["symbol"].upper(),
                "preco_usd": c["current_price"],
                "variacao_24h_pct": round(c.get("price_change_percentage_24h") or 0, 2),
            })

    return result


@router.get("/api/collectors/crypto")
async def get_crypto():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
