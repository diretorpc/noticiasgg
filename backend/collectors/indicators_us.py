import logging
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

from backend.services.secrets_mask import sanitize_error

load_dotenv()

logger = logging.getLogger("noticiasgg")
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

    # Por série, não pro loop inteiro: uma série com problema (rate limit,
    # instabilidade pontual do FRED) não pode derrubar as outras 3 nem, pior,
    # deixar `httpx.HTTPStatusError` (que carrega a FRED_API_KEY na URL) subir
    # cru até `_safe_collect` — daí ela vazaria pro contexto do agente em toda
    # conversa (achado extra, 18/08/2026 — não estava na lista original;
    # antes deste fix o loop nem tinha try/except nenhum).
    resultado = {}
    for series_id, nome in SERIES.items():
        try:
            resultado[nome] = _fetch_series(series_id, api_key)
        except Exception as e:
            # Sem log, FRED caído 4/4 não deixava uma linha sequer — a
            # degradação era invisível até alguém notar o relatório manco
            # (achado 5, revisão 18/08/2026 — 4ª rodada).
            err = sanitize_error(e)
            logger.warning("indicators_us: série '%s' falhou: %s", nome, err)
            resultado[nome] = {"erro": err}
    return resultado


@router.get("/api/collectors/indicators-us")
async def get_indicators_us():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
