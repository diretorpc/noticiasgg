# Agro Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capacitar o agente a responder qualquer pergunta sobre agronegócio usando `get_agro_data` (dados estruturados CBOT + CEPEA) e `search_agro_web` (busca ScraperAPI como fallback), ambas como tools Claude invocadas sob demanda.

**Architecture:** Novo `agro_br.py` coleta 5 categorias de dados estruturados (CBOT futures via Yahoo Finance + scraping Notícias Agrícolas). Novo `agro_search.py` usa ScraperAPI structured Google Search. Ambas registradas como tools em `reporter.py`, expandindo o loop `while True` de tool use já existente para `get_stock_data`.

**Tech Stack:** Python 3.12, httpx, BeautifulSoup4, Yahoo Finance API (query2.finance.yahoo.com), Notícias Agrícolas scraping, ScraperAPI structured search, Anthropic tool use (claude-sonnet-4-6)

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `backend/collectors/agro_br.py` | Criar | Coleta estruturada: CBOT + CEPEA/NA scraping, 5 categorias |
| `backend/services/agro_search.py` | Criar | Busca web via ScraperAPI structured Google Search |
| `backend/services/reporter.py` | Modificar | Registrar 2 tools + handlers no loop + system prompts |
| `backend/api/main.py` | Modificar | Incluir router de agro_br |
| `backend/tests/test_agro_br.py` | Criar | Testes de integração do collector (real API) |
| `backend/tests/test_agro_search.py` | Criar | Testes do serviço de busca (real ScraperAPI) |

---

### Task 1: agro_br.py — CBOT futures

**Files:**
- Create: `backend/collectors/agro_br.py`
- Create: `backend/tests/test_agro_br.py`
- Modify: `backend/api/main.py`

- [ ] **Step 1: Criar test_agro_br.py com teste de CBOT**

```python
# backend/tests/test_agro_br.py
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)


def test_agro_br_cbot_status_200():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    assert resp.status_code == 200


def test_agro_br_cbot_schema():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    body = resp.json()
    assert "data" in body
    assert "collected_at" in body
    assert "commodities_cbot" in body["data"]


def test_agro_br_cbot_campos():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_cbot")
    data = resp.json()["data"]["commodities_cbot"]
    assert len(data) > 0
    for ativo in data.values():
        assert "preco" in ativo
        assert "moeda" in ativo
        assert "unidade" in ativo
```

- [ ] **Step 2: Verificar que o teste falha**

```
pytest backend/tests/test_agro_br.py -v
```
Esperado: FAIL — `ImportError` ou `404`

- [ ] **Step 3: Criar agro_br.py com CBOT**

```python
# backend/collectors/agro_br.py
from datetime import datetime, timezone
import math
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter()

HEADERS_JSON = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}
HEADERS_HTML = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}

YF_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
YF_URL_FALLBACK = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
NA_BASE = "https://www.noticiasagricolas.com.br"

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


CATEGORIA_MAP = {
    "commodities_cbot": collect_commodities_cbot,
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
```

- [ ] **Step 4: Incluir router em main.py**

Em `backend/api/main.py`, linha 9, adicionar `agro_br` ao import:

```python
from backend.collectors import market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br, agro_br
```

Logo após `app.include_router(polls_br.router)` (linha 32), adicionar:

```python
app.include_router(agro_br.router)
```

- [ ] **Step 5: Rodar testes**

```
pytest backend/tests/test_agro_br.py -v
```
Esperado: 3 testes PASS

- [ ] **Step 6: Commit**

```bash
git add backend/collectors/agro_br.py backend/tests/test_agro_br.py backend/api/main.py
git commit -m "feat: add agro_br collector with CBOT futures"
```

---

### Task 2: agro_br.py — BR commodities (Notícias Agrícolas / CEPEA)

**Files:**
- Modify: `backend/collectors/agro_br.py`
- Modify: `backend/tests/test_agro_br.py`

- [ ] **Step 1: Adicionar teste de commodities_br em test_agro_br.py**

Adicionar ao final de `backend/tests/test_agro_br.py`:

```python
def test_agro_br_commodities_br_status_200():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_br")
    assert resp.status_code == 200


def test_agro_br_commodities_br_schema():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_br")
    body = resp.json()
    assert "data" in body
    assert "commodities_br" in body["data"]


def test_agro_br_commodities_br_campos():
    resp = client.get("/api/collectors/agro-br?categoria=commodities_br")
    data = resp.json()["data"]["commodities_br"]
    assert len(data) > 0
    # Pelo menos metade deve ter preço (tolerância a falhas de scraping)
    com_preco = [v for v in data.values() if v.get("preco") is not None]
    assert len(com_preco) >= len(data) // 2
```

- [ ] **Step 2: Verificar que o teste falha**

```
pytest backend/tests/test_agro_br.py::test_agro_br_commodities_br_status_200 -v
```
Esperado: FAIL — `404` (categoria não existe ainda)

- [ ] **Step 3: Adicionar _fetch_noticias_agro e NOTICIAS_AGRO_COMMODITIES em agro_br.py**

Após o bloco de imports, adicionar a função de scraping e o dicionário de commodities.
Inserir logo após a definição de `_parse_br_float`:

```python
from bs4 import BeautifulSoup


def _fetch_noticias_agro(
    client: httpx.Client, path: str, unidade: str, estado: str,
    col_preco: int, col_var: int, linha_idx: int
) -> dict:
    try:
        resp = client.get(NA_BASE + path, headers=HEADERS_HTML, timeout=15)
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


# (path, unidade, estado, col_preco, col_var, linha_idx)
# col_preco/col_var: índice da coluna (0-based); linha_idx: linha de dados (1-based)
# ⚠️ Verificar estrutura HTML de cada página antes de assumir índices padrão
NOTICIAS_AGRO_COMMODITIES = {
    "Soja PR":         ("/cotacoes/soja",          "R$/sc 60kg",  "PR", 1, 2, 1),
    "Milho SP":        ("/cotacoes/milho",          "R$/sc 60kg",  "SP", 1, 2, 1),
    "Trigo PR":        ("/cotacoes/trigo",          "R$/ton",      "PR", 2, 3, 1),
    "Cafe Arabica SP": ("/cotacoes/cafe",           "R$/sc 60kg",  "SP", 1, 2, 1),
    "Algodao SP":      ("/cotacoes/algodao",        "R$/@ 15kg",   "SP", 1, 2, 1),
    "Acucar SP":       ("/cotacoes/sucroenergetico","R$/sc 50kg",  "SP", 1, 2, 1),
    "Arroz RS":        ("/cotacoes/arroz",          "R$/sc 50kg",  "RS", 1, 2, 1),
    "Feijao SP":       ("/cotacoes/feijao",         "R$/sc 60kg",  "SP", 1, 2, 1),
    "Sorgo MG":        ("/cotacoes/sorgo",          "R$/sc 60kg",  "MG", 1, 2, 1),
    "Mandioca SP":     ("/cotacoes/mandioca",       "R$/ton",      "SP", 1, 2, 1),
    "Amendoim SP":     ("/cotacoes/amendoim",       "R$/sc 25kg",  "SP", 1, 2, 1),
    "Laranja SP":      ("/cotacoes/citros",         "R$/cx 40kg",  "SP", 1, 2, 1),
    "Aveia RS":        ("/cotacoes/aveia",          "R$/sc 40kg",  "RS", 1, 2, 1),
    "Cevada PR":       ("/cotacoes/cevada",         "R$/sc 60kg",  "PR", 1, 2, 1),
    "Canola RS":       ("/cotacoes/canola",         "R$/sc 60kg",  "RS", 1, 2, 1),
    "Girassol MT":     ("/cotacoes/girassol",       "R$/sc 60kg",  "MT", 1, 2, 1),
}
```

- [ ] **Step 4: Adicionar collect_commodities_br e registrar em CATEGORIA_MAP**

Adicionar a função após `collect_commodities_cbot`:

```python
def collect_commodities_br() -> dict:
    resultado = {}
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        for nome, (path, unidade, estado, col_preco, col_var, linha_idx) in NOTICIAS_AGRO_COMMODITIES.items():
            resultado[nome] = _fetch_noticias_agro(client, path, unidade, estado, col_preco, col_var, linha_idx)
    return resultado
```

Atualizar `CATEGORIA_MAP`:

```python
CATEGORIA_MAP = {
    "commodities_cbot": collect_commodities_cbot,
    "commodities_br":   collect_commodities_br,
}
```

- [ ] **Step 5: Verificar URLs e índices de coluna manualmente**

Para cada entrada em `NOTICIAS_AGRO_COMMODITIES`, abrir a URL no browser e inspecionar a tabela HTML:
- Confirmar que a página existe e tem `<table>`
- Confirmar qual coluna tem o preço (0-based) e qual tem a variação
- Confirmar qual linha (1-based) tem o dado mais relevante
- Ajustar `col_preco`, `col_var`, `linha_idx` se necessário

Remover entradas cujas URLs não existirem (retornar erro no JSON é ok, mas evitar 404s em toda chamada).

- [ ] **Step 6: Rodar testes**

```
pytest backend/tests/test_agro_br.py -v
```
Esperado: todos os testes PASS (incluindo os 3 anteriores de CBOT)

- [ ] **Step 7: Commit**

```bash
git add backend/collectors/agro_br.py backend/tests/test_agro_br.py
git commit -m "feat: add BR commodities scraping to agro_br collector"
```

---

### Task 3: agro_br.py — gado, fertilizantes, defensivos

**Files:**
- Modify: `backend/collectors/agro_br.py`
- Modify: `backend/tests/test_agro_br.py`

- [ ] **Step 1: Adicionar testes de gado, fertilizantes e defensivos**

Adicionar ao final de `backend/tests/test_agro_br.py`:

```python
def test_agro_br_gado_schema():
    resp = client.get("/api/collectors/agro-br?categoria=gado")
    assert resp.status_code == 200
    body = resp.json()
    assert "gado" in body["data"]
    assert len(body["data"]["gado"]) > 0


def test_agro_br_fertilizantes_schema():
    resp = client.get("/api/collectors/agro-br?categoria=fertilizantes")
    assert resp.status_code == 200
    assert "fertilizantes" in resp.json()["data"]


def test_agro_br_defensivos_schema():
    resp = client.get("/api/collectors/agro-br?categoria=defensivos")
    assert resp.status_code == 200
    assert "defensivos" in resp.json()["data"]


def test_agro_br_all_categorias():
    resp = client.get("/api/collectors/agro-br")
    assert resp.status_code == 200
    data = resp.json()["data"]
    for cat in ["commodities_cbot", "commodities_br", "gado", "fertilizantes", "defensivos"]:
        assert cat in data
```

- [ ] **Step 2: Verificar que testes falham**

```
pytest backend/tests/test_agro_br.py::test_agro_br_gado_schema -v
```
Esperado: FAIL — categoria `gado` não existe

- [ ] **Step 3: Adicionar dicionários e funções de gado, fertilizantes, defensivos**

Adicionar após `NOTICIAS_AGRO_COMMODITIES` em `agro_br.py`:

```python
# ⚠️ Verificar URLs e índices de coluna no browser antes de finalizar
NOTICIAS_AGRO_GADO = {
    "Boi Gordo SP":   ("/cotacoes/boi-gordo",   "R$/@",     "SP", 1, 2, 1),
    "Bezerro SP":     ("/cotacoes/bezerro",      "R$/cab",   "SP", 1, 2, 1),
    "Vaca Gorda SP":  ("/cotacoes/vaca-gorda",   "R$/@",     "SP", 1, 2, 1),
    "Frango SP":      ("/cotacoes/frango",        "R$/kg",    "SP", 1, 2, 1),
    "Suino PR":       ("/cotacoes/suinos",        "R$/kg",    "PR", 2, 3, 2),
    "Leite SP":       ("/cotacoes/leite",         "R$/L",     "SP", 1, 2, 1),
    "Ovos SP":        ("/cotacoes/ovos",          "R$/dz",    "SP", 1, 2, 1),
}

NOTICIAS_AGRO_FERTILIZANTES = {
    "Ureia SP":  ("/cotacoes/ureia", "R$/sc 50kg", "SP", 1, 2, 1),
    "MAP SP":    ("/cotacoes/map",   "R$/sc 50kg", "SP", 1, 2, 1),
    "KCl SP":    ("/cotacoes/kcl",   "R$/sc 50kg", "SP", 1, 2, 1),
}

NOTICIAS_AGRO_DEFENSIVOS = {
    "Glifosato SP": ("/cotacoes/glifosato", "R$/L", "SP", 1, 2, 1),
}
```

Adicionar funções após `collect_commodities_br`:

```python
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
```

Atualizar `CATEGORIA_MAP`:

```python
CATEGORIA_MAP = {
    "commodities_cbot": collect_commodities_cbot,
    "commodities_br":   collect_commodities_br,
    "gado":             collect_gado,
    "fertilizantes":    collect_fertilizantes,
    "defensivos":       collect_defensivos,
}
```

- [ ] **Step 4: Verificar URLs do Notícias Agrícolas para cada novo item**

Abrir no browser cada URL abaixo e confirmar que existe e tem tabela com cotações. Remover do dicionário se a URL retornar 404 ou não tiver tabela:
- `https://www.noticiasagricolas.com.br/cotacoes/bezerro`
- `https://www.noticiasagricolas.com.br/cotacoes/vaca-gorda`
- `https://www.noticiasagricolas.com.br/cotacoes/leite`
- `https://www.noticiasagricolas.com.br/cotacoes/ovos`
- `https://www.noticiasagricolas.com.br/cotacoes/ureia`
- `https://www.noticiasagricolas.com.br/cotacoes/map`
- `https://www.noticiasagricolas.com.br/cotacoes/kcl`
- `https://www.noticiasagricolas.com.br/cotacoes/glifosato`

Para URLs que existem, confirmar `col_preco`, `col_var`, `linha_idx` inspecionando o HTML da tabela.

- [ ] **Step 5: Rodar testes**

```
pytest backend/tests/test_agro_br.py -v
```
Esperado: todos PASS

- [ ] **Step 6: Commit**

```bash
git add backend/collectors/agro_br.py backend/tests/test_agro_br.py
git commit -m "feat: add gado, fertilizantes, defensivos to agro_br collector"
```

---

### Task 4: agro_search.py — busca web via ScraperAPI

**Files:**
- Create: `backend/services/agro_search.py`
- Create: `backend/tests/test_agro_search.py`

- [ ] **Step 1: Criar test_agro_search.py**

```python
# backend/tests/test_agro_search.py
import os
import pytest
from backend.services import agro_search


@pytest.mark.skipif(not os.getenv("SCRAPER_API_KEY"), reason="SCRAPER_API_KEY não configurada")
def test_search_retorna_resultados():
    resultado = agro_search.search("preço soja hoje Brasil")
    assert "resultados" in resultado
    assert isinstance(resultado["resultados"], list)


@pytest.mark.skipif(not os.getenv("SCRAPER_API_KEY"), reason="SCRAPER_API_KEY não configurada")
def test_search_resultados_tem_campos():
    resultado = agro_search.search("cotação ureia Brasil 2026")
    resultados = resultado["resultados"]
    if resultados:
        for r in resultados:
            assert "titulo" in r
            assert "snippet" in r


def test_search_sem_chave_retorna_erro(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    resultado = agro_search.search("qualquer coisa")
    assert "erro" in resultado
```

- [ ] **Step 2: Verificar que testes falham**

```
pytest backend/tests/test_agro_search.py -v
```
Esperado: FAIL — `ImportError` (módulo não existe)

- [ ] **Step 3: Criar agro_search.py**

```python
# backend/services/agro_search.py
import os
import urllib.parse
import httpx


SCRAPER_API_URL = "https://api.scraperapi.com/structured/google/search"


def search(query: str) -> dict:
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return {"erro": "SCRAPER_API_KEY não configurada"}
    try:
        params = {
            "api_key": api_key,
            "query": query + " agronegócio Brasil",
            "country": "br",
            "num_results": 5,
        }
        resp = httpx.get(SCRAPER_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        organic = data.get("organic_results", [])
        resultados = [
            {"titulo": r.get("title", ""), "snippet": r.get("snippet", ""), "link": r.get("link", "")}
            for r in organic
        ]
        return {"resultados": resultados, "query": query}
    except httpx.TimeoutException:
        return {"erro": "timeout na busca", "resultados": []}
    except Exception as e:
        return {"erro": str(e), "resultados": []}
```

- [ ] **Step 4: Rodar testes**

```
pytest backend/tests/test_agro_search.py -v
```
Esperado: testes com `SCRAPER_API_KEY` passam se a chave estiver configurada; `test_search_sem_chave_retorna_erro` sempre passa.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agro_search.py backend/tests/test_agro_search.py
git commit -m "feat: add agro_search service via ScraperAPI"
```

---

### Task 5: reporter.py — registrar tools + handlers + system prompts

**Files:**
- Modify: `backend/services/reporter.py`

- [ ] **Step 1: Adicionar definições das duas novas tools**

Em `reporter.py`, após `_STOCK_TOOL` (linha ~78), adicionar:

```python
_AGRO_DATA_TOOL = {
    "name": "get_agro_data",
    "description": (
        "Busca dados estruturados do agronegócio brasileiro. "
        "Use para qualquer pergunta sobre commodities agrícolas (soja, milho, trigo, café, algodão, açúcar, cacau, arroz, feijão, sorgo, mandioca, amendoim, laranja, aveia, cevada, canola, girassol), "
        "pecuária (boi gordo, bezerro, vaca gorda, frango, suíno, leite, ovos), "
        "fertilizantes (ureia, MAP, KCl) ou defensivos agrícolas (glifosato). "
        "Para cotações internacionais use categoria 'commodities_cbot', "
        "para preços BR use 'commodities_br', "
        "para pecuária use 'gado', para insumos use 'fertilizantes', para agroquímicos use 'defensivos'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "categoria": {
                "type": "string",
                "enum": ["commodities_cbot", "commodities_br", "gado", "fertilizantes", "defensivos"],
                "description": "Categoria de dados agro a buscar.",
            }
        },
        "required": ["categoria"],
    },
}

_AGRO_SEARCH_TOOL = {
    "name": "search_agro_web",
    "description": (
        "Busca na web dados do agronegócio não cobertos pelas categorias estruturadas. "
        "Use para: preço de arrendamento de terras, preço de maquinários agrícolas, "
        "estimativas de safra (CONAB), dados climáticos, notícias setoriais, "
        "defensivos agrícolas específicos (fungicidas, inseticidas além do glifosato), "
        "crédito rural, dados regionais específicos, ou qualquer outra informação agro "
        "não disponível em get_agro_data."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Consulta em linguagem natural para buscar no Google.",
            }
        },
        "required": ["query"],
    },
}
```

- [ ] **Step 2: Atualizar system prompts para incluir instrução de agro**

Em `_SYSTEM_MARKET` (linha ~17), substituir a última linha da regra de get_stock_data por:

```python
_SYSTEM_MARKET = """Você é um analista financeiro brasileiro especialista em mercados, indicadores macroeconômicos, geopolítica e agronegócio.

Você recebe dados estruturados (JSON) com cotações de bolsas, câmbio, criptomoedas, indicadores econômicos (BR/EUA) e notícias. Sua tarefa é gerar um resumo claro, conciso e acionável em português, formatado para WhatsApp (use *negrito*, _itálico_, emojis com moderação, sem markdown de código).

Regras:
- Comece com um resumo de 1-2 linhas do dia
- Destaque variações relevantes (>1%) em bolsas, câmbio e cripto
- Mencione indicadores econômicos novos
- Cite as 2-3 notícias mais relevantes
- Termine com uma análise breve do cenário
- Máximo 1500 caracteres
- Se o usuário fizer pergunta específica, responda diretamente sem o formato de resumo
- OBRIGATÓRIO: se o usuário perguntar sobre cotação ou preço de uma ação específica (ex: RAIZ4, PETR4, VALE3, AAPL) que não esteja nos dados recebidos, chame IMEDIATAMENTE get_stock_data antes de responder. NUNCA diga que não tem o dado sem antes usar a ferramenta.
- OBRIGATÓRIO: se o usuário perguntar sobre qualquer dado do agronegócio (commodities agrícolas, pecuária, fertilizantes, defensivos, glifosato, ureia, soja, milho, boi gordo, etc.), chame get_agro_data com a categoria mais relevante. Se a informação não estiver nas categorias estruturadas (ex: preço de terra, maquinário, estimativa de safra), use search_agro_web."""
```

Em `_SYSTEM_CHAT` (linha ~31), adicionar ao final:

```python
_SYSTEM_CHAT = """Você é um assistente financeiro brasileiro, inteligente e próximo — como um amigo que entende muito de economia, mercado, política e agronegócio.

Responda de forma natural e humana, como numa conversa de WhatsApp. Sem formatação de relatório, sem seções, sem bullets obrigatórios. Use *negrito* só quando realmente precisar destacar algo. Emojis com moderação e só quando ficarem naturais.

Se for uma saudação ou bate-papo casual, responda de forma leve e amigável.
Se for uma pergunta sobre qualquer assunto (política, economia, geografia, história, curiosidade), explique de forma clara e direta como se estivesse conversando — não como se fosse um documento ou automação.
Seja conciso: máximo 3-4 parágrafos curtos.
Se o usuário perguntar sobre cotação ou preço de uma ação específica, use a ferramenta get_stock_data para buscar os dados em tempo real.
Se o usuário perguntar sobre qualquer dado do agronegócio (commodities, pecuária, fertilizantes, defensivos, terras, maquinários, safra, etc.), use get_agro_data com a categoria mais relevante ou search_agro_web para dados não cobertos estruturalmente."""
```

- [ ] **Step 3: Atualizar lista de tools na chamada da API**

Na linha 147 de `reporter.py`, atualizar a lista `tools`:

```python
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=system,
            messages=messages,
            tools=[_STOCK_TOOL, _AGRO_DATA_TOOL, _AGRO_SEARCH_TOOL],
        )
```

- [ ] **Step 4: Adicionar handlers das novas tools no loop while True**

No bloco `if response.stop_reason == "tool_use":` (linha ~150), dentro do `for block in response.content:`, após o handler de `get_stock_data`, adicionar:

```python
                elif block.type == "tool_use" and block.name == "get_agro_data":
                    from backend.collectors import agro_br
                    result = agro_br.collect(block.input.get("categoria"))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                elif block.type == "tool_use" and block.name == "search_agro_web":
                    from backend.services import agro_search
                    result = agro_search.search(block.input["query"])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
```

- [ ] **Step 5: Rodar suite completa de testes**

```
pytest backend/tests/ -v
```
Esperado: todos os testes existentes continuam passando + novos testes de agro passam.

- [ ] **Step 6: Commit**

```bash
git add backend/services/reporter.py
git commit -m "feat: register get_agro_data and search_agro_web tools in Claude agent"
```

---

### Task 6: Validação end-to-end e deploy

**Files:** nenhum arquivo novo

- [ ] **Step 1: Subir servidor local**

```
uvicorn backend.api.main:app --reload
```

- [ ] **Step 2: Testar endpoint de agro-br manualmente**

```bash
curl "http://localhost:8000/api/collectors/agro-br?categoria=commodities_cbot"
curl "http://localhost:8000/api/collectors/agro-br?categoria=gado"
curl "http://localhost:8000/api/collectors/agro-br?categoria=fertilizantes"
```
Esperado: JSON com `data` e `collected_at`. Itens podem ter `erro` se a URL do NA não existir — isso é esperado e tolerável.

- [ ] **Step 3: Testar busca web manualmente**

```bash
python -c "
from backend.services import agro_search
import json
r = agro_search.search('preço arrendamento terra Mato Grosso 2026')
print(json.dumps(r, ensure_ascii=False, indent=2))
"
```
Esperado: JSON com lista `resultados` contendo título + snippet.

- [ ] **Step 4: Rodar suite completa**

```
pytest backend/tests/ -v
```
Esperado: todos PASS

- [ ] **Step 5: Deploy**

```
vercel --prod
```

- [ ] **Step 6: Commit final e PR**

```bash
git add .
git commit -m "chore: finalize agro tools feature"
git push origin feature/agro-tools
```

Abrir PR: `feature/agro-tools` → `master`
