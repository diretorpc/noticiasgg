import os
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException

router = APIRouter()

_CEPEA_URL = "https://www.cepea.esalq.usp.br/br/indicador/cana-de-acucar.aspx"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def _parse_br_float(text: str) -> float | None:
    try:
        cleaned = text.strip().replace(".", "").replace(",", ".").lstrip("+")
        return float(cleaned)
    except Exception:
        return None


def _parse_table(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # CEPEA usa id="imagenet-table" na tabela de indicadores
    table = soup.find("table", {"id": "imagenet-table"}) or soup.find("table")
    if not table:
        return {"erro": "tabela não encontrada na página CEPEA"}

    rows = [r for r in table.find_all("tr") if r.find("td")]
    if not rows:
        return {"erro": "nenhuma linha de dados na tabela"}

    cols = [td.get_text(strip=True) for td in rows[0].find_all("td")]
    # Colunas esperadas: Data | À vista R$/ton | Variação (%)
    if len(cols) < 2:
        return {"erro": f"colunas insuficientes: {cols}"}

    preco = _parse_br_float(cols[1]) if len(cols) > 1 else None
    variacao = _parse_br_float(cols[2]) if len(cols) > 2 else None

    return {
        "ativo": "Cana ATR (ESALQ/CEPEA)",
        "preco": preco,
        "variacao_pct": variacao,
        "unidade": "R$/ton ATR",
        "data_ref": cols[0] if cols else None,
    }


def collect() -> dict:
    """Coleta preço ATR da cana-de-açúcar via scraping do CEPEA/ESALQ."""
    api_key = os.environ.get("SCRAPER_API_KEY", "")

    # Tenta direto primeiro; usa ScraperAPI como fallback
    urls_to_try = [_CEPEA_URL]
    if api_key:
        urls_to_try.append(f"https://api.scraperapi.com/?api_key={api_key}&url={_CEPEA_URL}")

    last_err = "sem tentativas"
    for url in urls_to_try:
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                resp = client.get(url, headers=_HEADERS)
                resp.raise_for_status()
            result = _parse_table(resp.text)
            if "erro" not in result:
                return result
            last_err = result["erro"]
        except Exception as e:
            last_err = str(e)

    return {"erro": last_err}


@router.get("/api/collectors/esalq")
async def get_esalq():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
