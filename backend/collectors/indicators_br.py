from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter()

# BCB — séries do Banco Central do Brasil
BCB_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/2?formato=json"

SERIES = {
    11: "SELIC (% a.a.)",
    433: "IPCA (% mensal)",
}


def _fetch_bcb(codigo: int) -> dict:
    url = BCB_BASE.format(codigo=codigo)
    with httpx.Client(timeout=15) as client:
        resp = client.get(url)
        resp.raise_for_status()
        obs = resp.json()

    if not obs:
        return {"valor": None, "data": None, "variacao": None}

    atual = obs[-1]
    valor_atual = float(atual["valor"].replace(",", "."))

    variacao = None
    if len(obs) >= 2:
        valor_anterior = float(obs[-2]["valor"].replace(",", "."))
        variacao = round(valor_atual - valor_anterior, 4)

    return {
        "valor": valor_atual,
        "data": atual["data"],
        "variacao": variacao,
    }


def collect() -> dict:
    resultado = {}
    for codigo, nome in SERIES.items():
        resultado[nome] = _fetch_bcb(codigo)
    return resultado


@router.get("/api/collectors/indicators-br")
async def get_indicators_br():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
