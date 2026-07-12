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

# (url, unidade, estado, linha_idx)
# As colunas de preço/variação são detectadas pelo TEXTO do cabeçalho (robusto a
# reordenação). linha_idx: qual linha de dados pegar (1-based) — seleciona a praça/UF.
NOTICIAS_AGRO = {
    "Boi Gordo SP":        ("https://www.noticiasagricolas.com.br/cotacoes/boi-gordo",       "R$/@",       "SP", 1),
    "Soja PR":             ("https://www.noticiasagricolas.com.br/cotacoes/soja",             "R$/sc 60kg", "PR", 1),
    "Milho SP":            ("https://www.noticiasagricolas.com.br/cotacoes/milho",            "R$/sc 60kg", "SP", 1),
    "Cafe Arabica SP":     ("https://www.noticiasagricolas.com.br/cotacoes/cafe",             "R$/sc 60kg", "SP", 1),
    "Trigo PR":            ("https://www.noticiasagricolas.com.br/cotacoes/trigo",            "R$/ton",     "PR", 1),
    "Frango congelado SP": ("https://www.noticiasagricolas.com.br/cotacoes/frango",           "R$/kg",      "SP", 1),
    "Suino vivo PR":       ("https://www.noticiasagricolas.com.br/cotacoes/suinos",           "R$/kg",      "PR", 2),
    "Arroz tipo 1 RS":     ("https://www.noticiasagricolas.com.br/cotacoes/arroz",            "R$/sc 50kg", "RS", 1),
    "Acucar Cristal SP":   ("https://www.noticiasagricolas.com.br/cotacoes/sucroenergetico",  "R$/sc 50kg", "SP", 1),
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


def _header_columns(tabela) -> tuple[int | None, int | None]:
    """Localiza os índices das colunas de preço e variação pelo TEXTO do cabeçalho
    (<th>), em vez de posição fixa. Se o site reordena as colunas, lemos a coluna
    certa em vez de reportar um número errado em silêncio."""
    header_row = next((tr for tr in tabela.find_all("tr") if tr.find("th")), None)
    if header_row is None:
        return None, None
    headers = [th.get_text(strip=True).lower() for th in header_row.find_all("th")]
    col_preco = next((i for i, h in enumerate(headers) if "r$" in h or "preço" in h or "valor" in h), None)
    col_var = next((i for i, h in enumerate(headers) if "varia" in h), None)
    return col_preco, col_var


def _fetch_noticias_agro(client: httpx.Client, url: str, unidade: str, estado: str,
                          linha_idx: int) -> dict:
    base = {"preco": None, "variacao_pct": None, "moeda": "BRL", "unidade": unidade}
    try:
        resp = client.get(url, headers=HEADERS_HTML, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        tabela = soup.find("table")
        if not tabela:
            return {**base, "erro": "tabela não encontrada"}

        col_preco, col_var = _header_columns(tabela)
        if col_preco is None or col_var is None:
            return {**base, "erro": "cabeçalho não reconhecido"}

        linhas = [l for l in tabela.find_all("tr") if l.find("td")]
        if linha_idx < 1 or linha_idx > len(linhas):
            return {**base, "erro": "linha não encontrada"}

        cols = [c.get_text(strip=True) for c in linhas[linha_idx - 1].find_all("td")]
        preco = _parse_br_float(cols[col_preco]) if col_preco < len(cols) else None
        variacao = _parse_br_float(cols[col_var]) if col_var < len(cols) else None

        return {**base, "preco": preco, "variacao_pct": variacao, "estado": estado}
    except Exception as e:
        return {**base, "erro": str(e)}


def collect() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        resultado["Petroleo Brent"] = _fetch_yahoo(client, "BZ=F", "USD/barril", "USD")

        for nome, (url, unidade, estado, linha_idx) in NOTICIAS_AGRO.items():
            resultado[nome] = _fetch_noticias_agro(client, url, unidade, estado, linha_idx)

    return resultado


@router.get("/api/collectors/commodities-br")
async def get_commodities_br():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
