import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException

load_dotenv()

logger = logging.getLogger("noticiasgg")
router = APIRouter()

EIA_SERIESID = "https://api.eia.gov/v2/seriesid/{sid}"

# Série EIA → (nome legível, unidade)
SERIES = {
    "PET.WCESTUS1.W": ("Estoques Petróleo EUA (exc. SPR)", "mil barris"),
    "PET.WGTSTUS1.W": ("Estoques Gasolina EUA", "mil barris"),
    "NG.NW2_EPG0_SWO_R48_BCF.W": ("Estoques Gás Natural EUA", "Bcf"),
}

_MISSING = "."  # EIA usa "." como sentinel para dado ausente (igual ao FRED)


def _fetch_series(sid: str, api_key: str, client: httpx.Client) -> dict:
    params = {
        "api_key": api_key,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 2,
    }
    resp = client.get(EIA_SERIESID.format(sid=sid), params=params)
    resp.raise_for_status()
    rows = resp.json().get("response", {}).get("data", [])

    # garante ordem decrescente por período mesmo se a API ignorar o sort
    rows = sorted(rows, key=lambda r: r.get("period", ""), reverse=True)[:2]
    if not rows:
        return {"valor": None, "data": None, "variacao_pct": None}

    atual = rows[0]
    raw_atual = atual.get("value")
    valor = float(raw_atual) if raw_atual is not None and raw_atual != _MISSING else None

    variacao_pct = None
    if valor is not None and len(rows) >= 2:
        raw_anterior = rows[1].get("value")
        if raw_anterior is not None and raw_anterior != _MISSING:
            anterior = float(raw_anterior)
            if anterior:
                variacao_pct = round((valor - anterior) / anterior * 100, 2)

    return {"valor": valor, "data": atual.get("period"), "variacao_pct": variacao_pct}


def collect() -> dict:
    api_key = os.getenv("EIA_API_KEY", "")
    if not api_key:
        raise ValueError("EIA_API_KEY não configurada")

    resultado = {}
    with httpx.Client(timeout=20) as client:
        with ThreadPoolExecutor(max_workers=len(SERIES)) as ex:
            futures = {
                ex.submit(_fetch_series, sid, api_key, client): (sid, nome, unidade)
                for sid, (nome, unidade) in SERIES.items()
            }
            try:
                for future in as_completed(futures, timeout=25):
                    sid, nome, unidade = futures[future]
                    try:
                        data = future.result()
                        data["unidade"] = unidade
                        resultado[nome] = data
                    except Exception as e:
                        resultado[nome] = {"erro": str(e)}
            except TimeoutError:
                logger.warning("eia: timeout waiting for series, returning partial results")

    return resultado


@router.get("/api/collectors/eia")
async def get_eia():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
