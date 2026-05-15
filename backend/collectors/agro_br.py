from datetime import datetime, timezone
import math
import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException

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
NA_BASE = "https://www.noticiasagricolas.com.br"  # usado nas categorias de scraping (Tasks 2-3)

# (símbolo, unidade, moeda)
CBOT_SYMBOLS = {
    "Soja CBOT":         ("ZS=F",  "USc/bushel", "USD"),
    "Farelo Soja CBOT":  ("ZM=F",  "USD/ton",    "USD"),
    "Oleo Soja CBOT":    ("ZL=F",  "USc/lb",     "USD"),
    "Milho CBOT":        ("ZC=F",  "USc/bushel", "USD"),
    "Trigo CBOT":        ("ZW=F",  "USc/bushel", "USD"),
    "Algodao ICE":       ("CT=F",  "USc/lb",     "USD"),
    "Cafe Arabica ICE":  ("KC=F",  "USc/lb",     "USD"),
    "Acucar ICE":        ("SB=F",  "USc/lb",     "USD"),
    "Cacau ICE":         ("CC=F",  "USD/ton",    "USD"),
    "Suco Laranja ICE":  ("OJ=F",  "USc/lb",     "USD"),
    "Boi Gordo CME":     ("GF=F",  "USD/cwt",    "USD"),
    "Boi Vivo CME":      ("LE=F",  "USD/cwt",    "USD"),
    "Suino CME":         ("LH=F",  "USD/cwt",    "USD"),
    "Aveia CBOT":        ("ZO=F",  "USc/bushel", "USD"),
    "Arroz CBOT":        ("ZR=F",  "USD/cwt",    "USD"),
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


def _fetch_noticias_agro(
    client: httpx.Client, path: str, unidade: str, estado: str,
    col_preco: int, col_var: int, linha_idx: int
) -> dict:
    try:
        resp = client.get(NA_BASE + path, headers=HEADERS_HTML)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        tabela = soup.find("table")
        if not tabela:
            return {"preco": None, "variacao_pct": None, "erro": "tabela não encontrada", "moeda": "BRL", "unidade": unidade}
        linhas = [row for row in tabela.find_all("tr") if row.find("td")]
        if linha_idx < 1 or linha_idx > len(linhas):
            return {"preco": None, "variacao_pct": None, "erro": "linha não encontrada", "moeda": "BRL", "unidade": unidade}
        cols = [c.get_text(strip=True) for c in linhas[linha_idx - 1].find_all("td")]
        preco = _parse_br_float(cols[col_preco]) if col_preco < len(cols) else None
        variacao = _parse_br_float(cols[col_var]) if col_var < len(cols) else None
        return {"preco": preco, "variacao_pct": variacao, "moeda": "BRL", "unidade": unidade, "estado": estado}
    except Exception as e:
        return {"preco": None, "variacao_pct": None, "erro": str(e), "moeda": "BRL", "unidade": unidade}


# (path, unidade, estado, col_preco, col_var, linha_idx)
# col_preco/col_var: índice da coluna (0-based); linha_idx: linha de dados (1-based)
# URLs 404 removidas: citros, aveia, cevada, canola, girassol
NOTICIAS_AGRO_COMMODITIES = {
    "Soja PR":         ("/cotacoes/soja",           "R$/sc 60kg",  "PR", 1, 2, 1),
    "Milho SP":        ("/cotacoes/milho",           "R$/sc 60kg",  "SP", 1, 2, 1),
    "Trigo PR":        ("/cotacoes/trigo",           "R$/ton",      "PR", 2, 3, 1),
    "Cafe Arabica SP": ("/cotacoes/cafe",            "R$/sc 60kg",  "SP", 1, 2, 1),
    "Algodao SP":      ("/cotacoes/algodao",         "R$/@ 15kg",   "SP", 1, 2, 1),
    "Acucar SP":       ("/cotacoes/sucroenergetico", "R$/sc 50kg",  "SP", 1, 2, 1),
    "Arroz RS":        ("/cotacoes/arroz",           "R$/sc 50kg",  "RS", 1, 2, 1),
    "Feijao PR":       ("/cotacoes/feijao",          "R$/sc 60kg",  "PR", 1, 2, 1),
    "Sorgo RS":        ("/cotacoes/sorgo",           "R$/sc 60kg",  "RS", 1, 2, 1),
    "Mandioca MS":     ("/cotacoes/mandioca",        "R$/ton",      "MS", 2, 3, 1),
    "Amendoim SP":     ("/cotacoes/amendoim",        "R$/sc 25kg",  "SP", 1, 2, 2),
}

# URLs verificadas em 2026-05-15: bezerro/vaca-gorda → 404; boi-gordo/frango/suinos já validados
NOTICIAS_AGRO_GADO = {
    "Boi Gordo SP":  ("/cotacoes/boi-gordo", "R$/@",   "SP", 1, 2, 1),
    "Frango SP":     ("/cotacoes/frango",    "R$/kg",  "SP", 1, 2, 1),
    "Suino PR":      ("/cotacoes/suinos",    "R$/kg",  "PR", 2, 3, 2),
    "Leite SP":      ("/cotacoes/leite",     "R$/L",   "SP", 1, 2, 4),
    "Ovos SP":       ("/cotacoes/ovos",      "R$/dz",  "SP", 2, 3, 2),
}

# URLs verificadas em 2026-05-15: ureia/map/kcl → 404; sem entradas válidas
NOTICIAS_AGRO_FERTILIZANTES: dict = {}

# URLs verificadas em 2026-05-15: glifosato → 404; sem entradas válidas
NOTICIAS_AGRO_DEFENSIVOS: dict = {}


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
            variacao = round(((atual - anterior) / anterior) * 100, 2) if anterior else None
            return {"preco": round(atual, 2), "variacao_pct": variacao, "moeda": moeda, "unidade": unidade}
        except httpx.HTTPStatusError as e:
            last_err = f"HTTP {e.response.status_code}"
        except Exception as e:
            last_err = str(e)
    return {"preco": None, "variacao_pct": None, "erro": last_err, "moeda": moeda, "unidade": unidade}


def collect_commodities_cbot() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for nome, (symbol, unidade, moeda) in CBOT_SYMBOLS.items():
            resultado[nome] = _fetch_yahoo(client, symbol, unidade, moeda)
    return resultado


def collect_commodities_br() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for nome, (path, unidade, estado, col_preco, col_var, linha_idx) in NOTICIAS_AGRO_COMMODITIES.items():
            resultado[nome] = _fetch_noticias_agro(client, path, unidade, estado, col_preco, col_var, linha_idx)
    return resultado


def collect_gado() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for nome, (path, unidade, estado, col_preco, col_var, linha_idx) in NOTICIAS_AGRO_GADO.items():
            resultado[nome] = _fetch_noticias_agro(client, path, unidade, estado, col_preco, col_var, linha_idx)
    return resultado


def collect_fertilizantes() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for nome, (path, unidade, estado, col_preco, col_var, linha_idx) in NOTICIAS_AGRO_FERTILIZANTES.items():
            resultado[nome] = _fetch_noticias_agro(client, path, unidade, estado, col_preco, col_var, linha_idx)
    return resultado


def collect_defensivos() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for nome, (path, unidade, estado, col_preco, col_var, linha_idx) in NOTICIAS_AGRO_DEFENSIVOS.items():
            resultado[nome] = _fetch_noticias_agro(client, path, unidade, estado, col_preco, col_var, linha_idx)
    return resultado


CATEGORIA_MAP = {
    "commodities_cbot": collect_commodities_cbot,
    "commodities_br":   collect_commodities_br,
    "gado":             collect_gado,
    "fertilizantes":    collect_fertilizantes,
    "defensivos":       collect_defensivos,
}


def collect(categoria: str | None = None) -> dict:
    if categoria and categoria in CATEGORIA_MAP:
        return {categoria: CATEGORIA_MAP[categoria]()}
    return {k: fn() for k, fn in CATEGORIA_MAP.items()}


@router.get("/api/collectors/agro-br")
async def get_agro_br(categoria: str | None = None):
    try:
        data = collect(categoria)
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
