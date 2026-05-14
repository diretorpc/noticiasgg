from datetime import datetime, timezone
import math
from fastapi import APIRouter, HTTPException
import httpx
from bs4 import BeautifulSoup

router = APIRouter()

HEADERS_JSON = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}

YF_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
YF_URL_FALLBACK = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"

# (url, unidade, estado, coluna_preco, coluna_variacao, linha_idx)
# coluna_preco/variacao: índice da coluna na tabela (0-based)
# linha_idx: qual linha de dados pegar (1-based)
NOTICIAS_AGRO = {
    "Boi Gordo SP":        ("https://www.noticiasagricolas.com.br/cotacoes/boi-gordo",       "R$/@",       "SP", 1, 2, 1),
    "Soja PR":             ("https://www.noticiasagricolas.com.br/cotacoes/soja",             "R$/sc 60kg", "PR", 1, 2, 1),
    "Milho SP":            ("https://www.noticiasagricolas.com.br/cotacoes/milho",            "R$/sc 60kg", "SP", 1, 2, 1),
    "Cafe Arabica SP":     ("https://www.noticiasagricolas.com.br/cotacoes/cafe",             "R$/sc 60kg", "SP", 1, 2, 1),
    "Trigo PR":            ("https://www.noticiasagricolas.com.br/cotacoes/trigo",            "R$/ton",     "PR", 2, 3, 1),
    "Frango congelado SP": ("https://www.noticiasagricolas.com.br/cotacoes/frango",           "R$/kg",      "SP", 1, 2, 1),
    "Suino vivo PR":       ("https://www.noticiasagricolas.com.br/cotacoes/suinos",           "R$/kg",      "PR", 2, 3, 2),
    "Arroz tipo 1 RS":     ("https://www.noticiasagricolas.com.br/cotacoes/arroz",            "R$/sc 50kg", "RS", 1, 2, 1),
    "Acucar Cristal SP":   ("https://www.noticiasagricolas.com.br/cotacoes/sucroenergetico",  "R$/sc 50kg", "SP", 1, 2, 1),
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
            variacao = None
            if anterior:
                variacao = round(((atual - anterior) / anterior) * 100, 2)
            return {"preco": round(atual, 2), "variacao_pct": variacao, "moeda": moeda, "unidade": unidade}
        except httpx.HTTPStatusError as e:
            last_err = f"HTTP {e.response.status_code}"
        except Exception as e:
            last_err = str(e)
    return {"preco": None, "variacao_pct": None, "erro": last_err, "moeda": moeda, "unidade": unidade}


def _fetch_noticias_agro(client: httpx.Client, url: str, unidade: str, estado: str,
                          col_preco: int, col_var: int, linha_idx: int) -> dict:
    try:
        resp = client.get(url, headers=HEADERS_HTML, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        tabela = soup.find("table")
        if not tabela:
            return {"preco": None, "variacao_pct": None, "erro": "tabela não encontrada", "moeda": "BRL", "unidade": unidade}

        linhas = [l for l in tabela.find_all("tr") if l.find("td")]
        if linha_idx > len(linhas):
            return {"preco": None, "variacao_pct": None, "erro": "linha não encontrada", "moeda": "BRL", "unidade": unidade}

        cols = [c.get_text(strip=True) for c in linhas[linha_idx - 1].find_all("td")]
        preco = _parse_br_float(cols[col_preco]) if col_preco < len(cols) else None
        variacao = _parse_br_float(cols[col_var]) if col_var < len(cols) else None

        return {"preco": preco, "variacao_pct": variacao, "moeda": "BRL", "unidade": unidade, "estado": estado}
    except Exception as e:
        return {"preco": None, "variacao_pct": None, "erro": str(e), "moeda": "BRL", "unidade": unidade}


def collect() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        resultado["Petroleo Brent"] = _fetch_yahoo(client, "BZ=F", "USD/barril", "USD")

        for nome, (url, unidade, estado, col_preco, col_var, linha_idx) in NOTICIAS_AGRO.items():
            resultado[nome] = _fetch_noticias_agro(client, url, unidade, estado, col_preco, col_var, linha_idx)

    return resultado


@router.get("/api/collectors/commodities-br")
async def get_commodities_br():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
