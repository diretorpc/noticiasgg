"""Coletor da mensagem diária "Soja Disponível" — 3 blocos independentes:

- porto: indicador CEPEA/Esalq de soja disponível no Porto de Paranaguá,
  raspado do Notícias Agrícolas (o CEPEA direto devolve 500/403 sempre —
  medido em 04/09/2026, ver ESTADO.md).
- cbot: contrato futuro de soja mais próximo no CBOT (Chicago), via Yahoo
  Finance, reaproveitando os fetchers de collectors/market.py.
- dolar: cotação USD/BRL, mesma fonte do bloco cbot.

A formatação da mensagem para o usuário NÃO é responsabilidade deste módulo
— ele devolve números crus (ou {"erro": ...} por bloco, nunca levanta).
"""
import os
from datetime import date, datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException

from backend.collectors import market
from backend.collectors._br_num import parse_br_float as _parse_br_float
from backend.services.secrets_mask import sanitize_error

router = APIRouter()

_URL_PORTO_DEDICADA = "https://www.noticiasagricolas.com.br/cotacoes/soja/soja-indicador-cepea-esalq-porto-paranagua"
_URL_PORTO_GERAL = "https://www.noticiasagricolas.com.br/cotacoes/soja"

_TITULO_PORTO = "Indicador da Soja ESALQ/B3 - Paranaguá"
_FONTE_PORTO = "CEPEA/Esalq via Notícias Agrícolas"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Ciclo de meses da soja na CBOT: F=jan, H=mar, K=mai, N=jul, Q=ago, U=set,
# X=nov. Não existe contrato de fev/abr/jun/dez para soja.
_MESES_SOJA = [
    ("F", 1, "Janeiro"),
    ("H", 3, "Março"),
    ("K", 5, "Maio"),
    ("N", 7, "Julho"),
    ("Q", 8, "Agosto"),
    ("U", 9, "Setembro"),
    ("X", 11, "Novembro"),
]
_NOME_MES_POR_CODIGO = {codigo: nome for codigo, _, nome in _MESES_SOJA}


# ---------------------------------------------------------------------------
# Bloco 1: porto (Notícias Agrícolas)
# ---------------------------------------------------------------------------


def _titulo_bloco(bloco) -> str | None:
    """Título do próprio div.cotacao (só existe na página GERAL: h2 > a
    dentro de div.title-descricao). Na página DEDICADA o título mora fora do
    bloco, num <h1> único que vale para todos os blocos abaixo dele."""
    h2 = bloco.find("h2")
    if not h2:
        return None
    alvo = h2.find("a") or h2
    texto = alvo.get_text(strip=True)
    return texto or None


def _fonte_bloco(bloco) -> str:
    fonte_div = bloco.find("div", class_="fonte")
    if not fonte_div:
        return ""
    return fonte_div.get_text(strip=True)


# Faixa de sanidade do preço em R$/saca de 60 kg — recusa em vez de aceitar
# um valor de outra coluna/unidade que por acaso "colou" (ex.: dólar, ou uma
# variação percentual lida como se fosse preço).
_PRECO_MIN = 50.0
_PRECO_MAX = 500.0


def _indices_colunas(tabela) -> tuple[int | None, int | None, int | None]:
    """Índices (data, valor, variação) casados pelo NOME do cabeçalho no
    <thead> — nunca por posição fixa. 'Valor' precisa vir junto de 'R$' na
    MESMA célula (a Insoy também usa 'Valor US$' em outras tabelas da mesma
    página; pegar a 1ª coluna que contém só 'Valor' pegaria a errada)."""
    thead = tabela.find("thead")
    if not thead:
        return None, None, None
    cabecalhos = [th.get_text(strip=True).casefold() for th in thead.find_all("th")]

    idx_data = idx_valor = idx_variacao = None
    for i, cab in enumerate(cabecalhos):
        if idx_data is None and "data" in cab:
            idx_data = i
        if idx_valor is None and "valor" in cab and "r$" in cab:
            idx_valor = i
        if idx_variacao is None and "variaç" in cab:
            idx_variacao = i
    return idx_data, idx_valor, idx_variacao


def _linhas_tabela(tabela) -> list[tuple[str, float, float | None]]:
    """Todas as linhas válidas do tbody: (data, preço, variação), casadas por
    NOME de coluna. Sem coluna 'Data' ou 'Valor R$' no cabeçalho, ou preço
    fora da faixa de sanidade (50–500 R$/sc), a linha é descartada."""
    idx_data, idx_valor, idx_variacao = _indices_colunas(tabela)
    if idx_data is None or idx_valor is None:
        return []

    tbody = tabela.find("tbody")
    if not tbody:
        return []

    linhas: list[tuple[str, float, float | None]] = []
    for tr in tbody.find_all("tr"):
        celulas = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(celulas) <= idx_data or len(celulas) <= idx_valor:
            continue
        data_ref = celulas[idx_data]
        preco = _parse_br_float(celulas[idx_valor])
        if preco is None or not (_PRECO_MIN <= preco <= _PRECO_MAX):
            continue
        variacao = (
            _parse_br_float(celulas[idx_variacao])
            if idx_variacao is not None and len(celulas) > idx_variacao
            else None
        )
        linhas.append((data_ref, preco, variacao))
    return linhas


def _linha_mais_recente(tabela) -> tuple[str, float, float | None] | None:
    """A linha de DATA mais recente do tbody — nunca a primeira: fontes já
    publicaram tabela com os dias em ordem crescente."""
    linhas = _linhas_tabela(tabela)
    if not linhas:
        return None
    return max(linhas, key=lambda linha: _chave_data_br(linha[0]))


def _chave_data_br(data_ref: str) -> tuple[int, int, int]:
    """'dd/mm/aaaa' -> chave ordenável (aaaa, mm, dd). Formato inesperado
    ordena por último (nunca vence uma data real)."""
    try:
        dia, mes, ano = data_ref.split("/")
        return (int(ano), int(mes), int(dia))
    except Exception:
        return (0, 0, 0)


def parse_porto(html: str) -> dict:
    """Funciona nas duas páginas do Notícias Agrícolas (dedicada e geral).
    Casa o bloco pelo NOME do indicador (título + fonte) quando o bloco TEM
    título próprio (página geral) — a página geral tem outras tabelas
    `cot-fisicas` (ex.: Insoy Commodities) que não podem ser confundidas com
    o indicador CEPEA/Esalq.

    Na página DEDICADA nenhum bloco tem h2 próprio — todos herdam o mesmo
    <h1> da página, então casar por título ali é NO-OP: um bloco de OUTRA
    fonte de soja (ex.: Cepea/Esalq Paraná) passaria pelo mesmo filtro. Por
    isso, quando dois ou mais blocos empatam na data mais recente com preços
    diferentes, o resultado é ambíguo — nunca escolhe um dos dois."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    titulo_global = h1.get_text(strip=True) if h1 else None

    candidatos: list[tuple[str, float, float | None]] = []
    for bloco in soup.find_all("div", class_="cotacao"):
        fonte = _fonte_bloco(bloco)
        if "cepea/esalq" not in fonte.casefold():
            continue

        # Título específico do bloco (página geral) tem prioridade; só cai
        # para o título global (página dedicada) quando o bloco não tem um.
        titulo = _titulo_bloco(bloco) or titulo_global
        if not titulo or _TITULO_PORTO not in titulo:
            continue

        tabela = bloco.find("table", class_="cot-fisicas")
        if not tabela:
            continue

        linha = _linha_mais_recente(tabela)
        if not linha:
            continue
        candidatos.append(linha)

    if not candidatos:
        return {"erro": f"bloco '{_TITULO_PORTO}' não encontrado na página"}

    data_mais_recente = max(_chave_data_br(c[0]) for c in candidatos)
    no_topo = [c for c in candidatos if _chave_data_br(c[0]) == data_mais_recente]
    precos_distintos = {c[1] for c in no_topo}
    if len(precos_distintos) > 1:
        return {
            "erro": (
                f"ambíguo: {len(no_topo)} blocos com data mais recente e preços "
                f"diferentes {sorted(precos_distintos)}"
            )
        }

    data_ref, preco, variacao = no_topo[0]
    return {
        "preco": preco,
        "data_ref": data_ref,
        "variacao_pct": variacao,
        "fonte": _FONTE_PORTO,
        "unidade": "R$/sc 60 kg",
    }


def fetch_porto() -> dict:
    """Tenta, em ordem: página geral direto, página dedicada direto, página
    dedicada via ScraperAPI (só se houver chave). Devolve o primeiro parse
    sem erro; senão o último erro (sanitizado)."""
    api_key = os.environ.get("SCRAPER_API_KEY", "")

    tentativas: list[tuple[str, int]] = [
        # Geral PRIMEIRO: lá cada bloco tem título próprio e o casamento por nome
        # é real. Na dedicada todos herdam o <h1>; um bloco intruso (ex.: Paraná)
        # com data mais nova venceria calado (cenário executado na revisão).
        (_URL_PORTO_GERAL, 20),
        (_URL_PORTO_DEDICADA, 20),
    ]
    if api_key:
        url_scraper = f"https://api.scraperapi.com/?api_key={api_key}&url={_URL_PORTO_DEDICADA}"
        tentativas.append((url_scraper, 60))

    ultimo_erro = "sem tentativas"
    for url, timeout in tentativas:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=_HEADERS)
                resp.raise_for_status()
            resultado = parse_porto(resp.text)
            if "erro" not in resultado:
                return resultado
            ultimo_erro = resultado["erro"]
        except Exception as e:
            ultimo_erro = sanitize_error(e)

    return {"erro": ultimo_erro}


# ---------------------------------------------------------------------------
# Bloco 2: cbot (Yahoo Finance, via collectors/market.py)
# ---------------------------------------------------------------------------


def _ultimo_dia_util_antes_de(ano: int, mes: int, dia_limite: int = 15) -> date:
    """Último dia útil (seg-sex, sem feriados) ANTES do dia `dia_limite` do
    mês. É o último dia de negociação do contrato, na regra combinada."""
    d = date(ano, mes, dia_limite) - timedelta(days=1)
    while d.weekday() >= 5:  # 5=sábado, 6=domingo
        d -= timedelta(days=1)
    return d


def contratos_candidatos(hoje: date, n: int = 3) -> list[str]:
    """Próximos `n` contratos de soja da CBOT ainda não vencidos, em ordem
    cronológica, como símbolos Yahoo (ex.: "ZSU26.CBT")."""
    candidatos: list[str] = []
    ano = hoje.year
    while len(candidatos) < n:
        for codigo, mes, _nome in _MESES_SOJA:
            vencimento = _ultimo_dia_util_antes_de(ano, mes)
            if hoje > vencimento:
                continue
            candidatos.append(f"ZS{codigo}{ano % 100:02d}.CBT")
            if len(candidatos) >= n:
                break
        ano += 1
    return candidatos


def rotulo(simbolo: str) -> str:
    """"ZSU26.CBT" -> "ZSU6 Setembro26". "ZSF27.CBT" -> "ZSF7 Janeiro27"."""
    corpo = simbolo.split(".")[0]  # "ZSU26"
    codigo = corpo[2]
    ano2 = corpo[3:5]
    ano1 = ano2[-1]
    nome_mes = _NOME_MES_POR_CODIGO[codigo]
    return f"ZS{codigo}{ano1} {nome_mes}{ano2}"


def _hoje_brt() -> date:
    """Data de HOJE em Brasília — nunca `date.today()`: a Vercel roda em UTC,
    e perto da meia-noite BRT isso já daria o dia errado. Offset fixo -3 como
    o resto do backend (cron_report, alert_checker...): o Brasil não tem
    horário de verão desde 2019, e `ZoneInfo` exigiria `tzdata` na Vercel."""
    return datetime.now(timezone(timedelta(hours=-3))).date()


def _resultado_cbot(simbolo: str, dados: dict) -> dict:
    atual = dados["atual"]
    anterior = dados.get("anterior")
    return {
        "simbolo": simbolo,
        "rotulo": rotulo(simbolo),
        # Yahoo devolve em USX (centavo de dólar) por bushel — /100 sem
        # arredondar, para não perder precisão na conversão.
        "preco_usd_bushel": atual / 100,
        "anterior_usd_bushel": (anterior / 100) if anterior is not None else None,
        # Epoch de `regularMarketTime` — o passo 3 usa para marcar dado
        # defasado (fim de semana/feriado sem pregão novo).
        "atualizado_em": dados.get("atualizado_em"),
    }


def fetch_cbot(hoje: date | None = None) -> dict:
    """Busca o contrato mais próximo com preço disponível — todos os
    candidatos tentam DIRETO primeiro; só se TODOS falharem, UMA chamada ao
    ScraperAPI (premium) no candidato mais próximo. Cada candidato indo pro
    ScraperAPI (até 4, pior caso ~147s) somado ao resto do bloco encostava
    nos 300s de `maxDuration` da Vercel."""
    hoje = hoje or _hoje_brt()
    candidatos = contratos_candidatos(hoje)
    ultimo_erro = "nenhum contrato candidato"

    def _registrar_erro(simbolo: str, dados: dict | None) -> None:
        nonlocal ultimo_erro
        if dados and dados.get("erro"):
            ultimo_erro = dados["erro"]
        else:
            ultimo_erro = f"sem preço para {simbolo}"

    for simbolo in candidatos:
        _, dados = market._fetch_direct_one(simbolo)
        if dados and dados.get("atual") is not None:
            return _resultado_cbot(simbolo, dados)
        _registrar_erro(simbolo, dados)

    if not candidatos:
        return {"erro": ultimo_erro}

    simbolo = candidatos[0]  # o mais próximo — não repete a chamada premium por candidato
    dados = market._fetch_via_scraperapi(simbolo)
    if dados and dados.get("atual") is not None:
        return _resultado_cbot(simbolo, dados)
    _registrar_erro(simbolo, dados)

    return {"erro": ultimo_erro}


# ---------------------------------------------------------------------------
# Bloco 3: dolar (Yahoo Finance, via collectors/market.py)
# ---------------------------------------------------------------------------


def fetch_dolar() -> dict:
    simbolo = "BRL=X"
    _, dados = market._fetch_direct_one(simbolo)
    if dados is None:
        dados = market._fetch_via_scraperapi(simbolo)

    if not dados or dados.get("atual") is None:
        erro = (dados or {}).get("erro") or f"sem preço para {simbolo}"
        return {"erro": erro}

    return {
        "simbolo": simbolo,
        "preco": dados["atual"],
        "anterior": dados.get("anterior"),
        "atualizado_em": dados.get("atualizado_em"),
    }


# ---------------------------------------------------------------------------
# Agregador
# ---------------------------------------------------------------------------


def collect() -> dict:
    """Nunca levanta — cada bloco falha sozinho como {"erro": ...}."""
    resultado: dict = {}
    for chave, fn in (("porto", fetch_porto), ("cbot", fetch_cbot), ("dolar", fetch_dolar)):
        try:
            resultado[chave] = fn()
        except Exception as e:
            resultado[chave] = {"erro": sanitize_error(e)}
    return resultado


@router.get("/api/collectors/soja_disponivel")
async def get_soja_disponivel():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_error(e))
