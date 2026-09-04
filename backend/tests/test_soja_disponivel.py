from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from backend.collectors import soja_disponivel as sd

pytestmark = pytest.mark.unit

_FIXTURES = Path(__file__).parent / "fixtures"
_HTML_PARANAGUA = (_FIXTURES / "na_soja_paranagua_20260904.html").read_text(encoding="utf-8")
_HTML_GERAL = (_FIXTURES / "na_soja_geral_20260904.html").read_text(encoding="utf-8")

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


# ---------------------------------------------------------------------------
# parse_porto
# ---------------------------------------------------------------------------


def test_parse_porto_pagina_dedicada():
    result = sd.parse_porto(_HTML_PARANAGUA)
    assert result["preco"] == 160.14
    assert result["data_ref"] == "03/09/2026"
    assert result["variacao_pct"] == -0.53
    assert result["fonte"] == "CEPEA/Esalq via Notícias Agrícolas"
    assert result["unidade"] == "R$/sc 60 kg"


def test_parse_porto_fonte_casefold():
    """'Fonte: CEPEA/ESALQ' (variação de caixa) tem que casar igual — a
    comparação é por casefold(), não substring exata sensível a maiúsculas."""
    html_variante = _HTML_PARANAGUA.replace("Fonte: Cepea/Esalq", "Fonte: CEPEA/ESALQ")
    assert "Fonte: CEPEA/ESALQ" in html_variante
    result = sd.parse_porto(html_variante)
    assert result["preco"] == 160.14


def test_parse_porto_pagina_geral():
    result = sd.parse_porto(_HTML_GERAL)
    assert result["preco"] == 160.14
    # a Insoy Commodities também cota "Porto Paranaguá (disponível)" a 162,00
    # numa tabela `cot-fisicas` diferente — nunca pode ser confundida com o
    # indicador CEPEA/Esalq.
    assert result["preco"] != 162.0


def test_parse_porto_sem_bloco_cepea_da_erro():
    """Remove o bloco 'Indicador da Soja ESALQ/B3 - Paranaguá' da página geral
    (via BeautifulSoup, não string slicing manual) e confere que o parser
    não inventa número nenhum."""
    soup = BeautifulSoup(_HTML_GERAL, "html.parser")
    removido = False
    for bloco in soup.find_all("div", class_="cotacao"):
        h2 = bloco.find("h2")
        if h2 and "Paranaguá" in h2.get_text() and "ESALQ/B3" in h2.get_text():
            bloco.decompose()
            removido = True
            break
    assert removido, "fixture não continha o bloco esperado — teste não prova nada"

    result = sd.parse_porto(str(soup))
    assert "erro" in result
    assert "preco" not in result


def test_parse_porto_nao_e_posicional():
    """Injeta uma tabela `cot-fisicas` extra ANTES do bloco CEPEA real, com
    fonte 'Cepea/Esalq' mas título diferente — se o parser fosse posicional
    (pegasse a primeira tabela da página), acertaria o valor errado (999,99)."""
    bloco_falso = """
    <div class="cotacao">
      <div class="info">
        <div class="text-infos">
          <div class="title-descricao">
            <h2><a href="/x" title="Outro Indicador">Outro Indicador</a></h2>
          </div>
          <div class="fonte"><span>Fonte: Cepea/Esalq</span></div>
        </div>
      </div>
      <div class="table-content">
        <table class="cot-fisicas">
          <thead class="head-box"><tr><th>Data</th><th>Valor R$</th><th>Variação (%)</th></tr></thead>
          <tbody class="body-box"><tr><td>03/09/2026</td><td>999,99</td><td>0,00</td></tr></tbody>
        </table>
      </div>
    </div>
    """
    html_com_intruso = _HTML_GERAL.replace(
        '<div class="tables">', '<div class="tables">' + bloco_falso, 1
    )
    assert bloco_falso.strip()[:30] in html_com_intruso  # garante que a injeção aconteceu

    result = sd.parse_porto(html_com_intruso)
    assert result["preco"] == 160.14


def test_parse_porto_coluna_por_nome_nao_posicional():
    """Injeta 'Valor US$' ANTES de 'Valor R$' na tabela real. Um parser
    posicional (índice fixo `celulas[1]`) pegaria o dólar como preço e o
    real como variação — casar pelo NOME da coluna no <thead> resolve."""
    html_com_coluna_extra = _HTML_GERAL.replace(
        "<th>Valor R$</th>", "<th>Valor US$</th><th>Valor R$</th>", 1
    ).replace(
        "<td>160,14</td>", "<td>29,55</td><td>160,14</td>", 1
    )
    assert "<th>Valor US$</th><th>Valor R$</th>" in html_com_coluna_extra
    result = sd.parse_porto(html_com_coluna_extra)
    assert result["preco"] == 160.14
    assert result["variacao_pct"] == -0.53


def test_parse_porto_cabecalho_sem_rs_da_erro():
    """Sem uma coluna que combine 'Valor' + 'R$', não há como saber qual
    célula é o preço — e inventar por posição é o defeito que este teste
    proíbe voltar."""
    html_sem_rs = _HTML_GERAL.replace("<th>Valor R$</th>", "<th>Valor</th>", 1)
    assert "<th>Valor</th>" in html_sem_rs
    result = sd.parse_porto(html_sem_rs)
    assert "erro" in result
    assert "preco" not in result


def test_parse_porto_dedicada_bloco_intruso_da_erro_ambiguo():
    """Na página DEDICADA todo `div.cotacao` herda o mesmo <h1> — casar por
    título é NO-OP ali (nenhum bloco tem h2 próprio). Um bloco de OUTRA fonte
    de soja (Cepea/Esalq Paraná), sem h2 e com a MESMA data do bloco real,
    empataria com o Porto Paranaguá — e o parser escolhia um dos dois sem
    critério (foi assim que 151,68 saiu rotulado como Paranaguá). Tem que
    dar erro, nunca escolher."""
    soup_geral = BeautifulSoup(_HTML_GERAL, "html.parser")
    bloco_parana = None
    for bloco in soup_geral.find_all("div", class_="cotacao"):
        h2 = bloco.find("h2")
        if h2 and "Paraná" in h2.get_text():
            bloco_parana = bloco
            break
    assert bloco_parana is not None, "fixture não tem mais o bloco Paraná — teste não prova nada"
    bloco_parana.find("h2").decompose()  # como na página dedicada: sem h2 próprio

    html_com_intruso = _HTML_PARANAGUA.replace(
        '<div class="tables">', '<div class="tables">' + str(bloco_parana), 1
    )
    result = sd.parse_porto(html_com_intruso)
    assert "erro" in result
    assert "preco" not in result


def test_parse_porto_linha_mais_recente_por_data_nao_pela_ordem_da_tabela():
    """Três dias fundidos numa única tabela, em ordem CRESCENTE (formato que
    a fonte já usou). Pegar a primeira <tr> do tbody dá 161,14 de 01/09 — o
    dia mais VELHO. Tem que escolher pela DATA, nunca pela posição na tabela."""
    html = f"""
    <html><body>
    <h1>{sd._TITULO_PORTO}</h1>
    <div class="tables">
      <div class="cotacao">
        <div class="info"><div class="text-infos">
          <div class="fonte"><span>Fonte: Cepea/Esalq</span></div>
        </div></div>
        <div class="table-content">
          <table class="cot-fisicas">
            <thead class="head-box"><tr><th>Data</th><th>Valor R$</th><th>Variação (%)</th></tr></thead>
            <tbody class="body-box">
              <tr><td>01/09/2026</td><td>161,14</td><td>+1,07</td></tr>
              <tr><td>02/09/2026</td><td>160,99</td><td>-0,09</td></tr>
              <tr><td>03/09/2026</td><td>160,14</td><td>-0,53</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
    </body></html>
    """
    result = sd.parse_porto(html)
    assert result["preco"] == 160.14
    assert result["data_ref"] == "03/09/2026"
    assert result["variacao_pct"] == -0.53


# ---------------------------------------------------------------------------
# contratos_candidatos / rotulo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hoje,esperado",
    [
        (date(2026, 9, 4), ["ZSU26.CBT", "ZSX26.CBT", "ZSF27.CBT"]),
        (date(2026, 9, 15), ["ZSX26.CBT", "ZSF27.CBT", "ZSH27.CBT"]),
        (date(2026, 9, 14), ["ZSU26.CBT", "ZSX26.CBT", "ZSF27.CBT"]),
        (date(2026, 11, 14), ["ZSF27.CBT", "ZSH27.CBT", "ZSK27.CBT"]),
        (date(2026, 12, 20), ["ZSF27.CBT", "ZSH27.CBT", "ZSK27.CBT"]),
    ],
)
def test_contratos_candidatos(hoje, esperado):
    assert sd.contratos_candidatos(hoje) == esperado


@pytest.mark.parametrize(
    "simbolo,esperado",
    [
        ("ZSU26.CBT", "ZSU6 Setembro26"),
        ("ZSF27.CBT", "ZSF7 Janeiro27"),
    ],
)
def test_rotulo(simbolo, esperado):
    assert sd.rotulo(simbolo) == esperado


# ---------------------------------------------------------------------------
# fetch_cbot / fetch_dolar
# ---------------------------------------------------------------------------


def test_fetch_cbot_pula_candidato_sem_preco(monkeypatch):
    """1º candidato (ZSU26) não tem preço (404/None) direto; 2º (ZSX26) tem
    1310.25 direto — escolhe o 2º, converte USX -> USD/bushel sem arredondar
    (13.1025) e ZERO chamadas ao ScraperAPI (o direto do 2º já resolveu)."""
    monkeypatch.setattr(sd, "contratos_candidatos", lambda hoje, n=3: ["ZSU26.CBT", "ZSX26.CBT", "ZSF27.CBT"])

    respostas = {
        "ZSU26.CBT": None,
        "ZSX26.CBT": {
            "preco": 13.1, "variacao_pct": -0.5, "atual": 1310.25, "anterior": 1317.0,
            "atualizado_em": 1725480000,
        },
    }

    def _fake_fetch_direct_one(sym):
        return sym, respostas.get(sym)

    mock_scraperapi = MagicMock()
    with patch.object(sd.market, "_fetch_direct_one", side_effect=_fake_fetch_direct_one), \
         patch.object(sd.market, "_fetch_via_scraperapi", mock_scraperapi):
        result = sd.fetch_cbot(hoje=date(2026, 9, 4))

    assert result["simbolo"] == "ZSX26.CBT"
    assert result["rotulo"] == "ZSX6 Novembro26"
    assert result["preco_usd_bushel"] == pytest.approx(13.1025)
    assert result["anterior_usd_bushel"] == pytest.approx(13.17)
    assert result["atualizado_em"] == 1725480000
    mock_scraperapi.assert_not_called()


def test_fetch_cbot_todos_diretos_falham_uma_so_chamada_scraperapi(monkeypatch):
    """Se TODOS os candidatos falharem direto, só o mais próximo (1º da
    lista) vai pro ScraperAPI — não um por candidato. Antes: até 4 chamadas
    premium por rodada (até 147s), encostando no maxDuration de 300s da
    Vercel junto com o resto do bloco."""
    monkeypatch.setattr(sd, "contratos_candidatos", lambda hoje, n=3: ["ZSU26.CBT", "ZSX26.CBT", "ZSF27.CBT"])

    mock_scraperapi = MagicMock(return_value={"preco": None, "variacao_pct": None, "erro": "sem chave ScraperAPI"})
    with patch.object(sd.market, "_fetch_direct_one", return_value=("x", None)), \
         patch.object(sd.market, "_fetch_via_scraperapi", mock_scraperapi):
        result = sd.fetch_cbot(hoje=date(2026, 9, 4))

    assert "erro" in result
    assert mock_scraperapi.call_count == 1
    assert mock_scraperapi.call_args.args[0] == "ZSU26.CBT"  # o candidato mais próximo


def test_fetch_cbot_usa_data_de_sao_paulo_quando_hoje_nao_informado(monkeypatch):
    """Sem `hoje` explícito, `fetch_cbot` não pode usar `date.today()` — a
    Vercel roda em UTC, e perto da meia-noite BRT isso já daria o dia errado."""
    chamada = {}

    def _fake_contratos(hoje, n=3):
        chamada["hoje"] = hoje
        return []

    monkeypatch.setattr(sd, "_hoje_brt", lambda: date(2026, 9, 4))
    monkeypatch.setattr(sd, "contratos_candidatos", _fake_contratos)
    result = sd.fetch_cbot()
    assert chamada["hoje"] == date(2026, 9, 4)
    assert "erro" in result


def test_hoje_brt_usa_fuso_de_brasilia():
    """Offset fixo -3 como o resto do backend — sem `ZoneInfo`, que exigiria
    `tzdata` instalado na Vercel (achado do Apolo, 04/09)."""
    with patch.object(sd, "datetime") as mock_datetime:
        mock_datetime.now.return_value.date.return_value = date(2026, 9, 4)
        resultado = sd._hoje_brt()

    mock_datetime.now.assert_called_once()
    fuso = mock_datetime.now.call_args.args[0]
    assert fuso.utcoffset(None) == timedelta(hours=-3)
    assert resultado == date(2026, 9, 4)


def test_fetch_dolar_ok():
    dados = {
        "preco": 5.13, "variacao_pct": 0.57, "atual": 5.1273, "anterior": 5.0981,
        "atualizado_em": 1725480000,
    }
    with patch.object(sd.market, "_fetch_direct_one", return_value=("BRL=X", dados)):
        result = sd.fetch_dolar()
    assert result == {
        "simbolo": "BRL=X", "preco": 5.1273, "anterior": 5.0981, "atualizado_em": 1725480000,
    }


def test_fetch_dolar_erro():
    with patch.object(sd.market, "_fetch_direct_one", return_value=("BRL=X", None)), \
         patch.object(sd.market, "_fetch_via_scraperapi", return_value={"preco": None, "variacao_pct": None, "erro": "sem chave ScraperAPI"}):
        result = sd.fetch_dolar()
    assert "erro" in result


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


def test_collect_nunca_levanta_mesmo_com_tudo_estourando():
    with patch.object(sd, "fetch_porto", side_effect=RuntimeError("boom porto")), \
         patch.object(sd, "fetch_cbot", side_effect=RuntimeError("boom cbot")), \
         patch.object(sd, "fetch_dolar", side_effect=RuntimeError("boom dolar")):
        result = sd.collect()

    assert set(result.keys()) == {"porto", "cbot", "dolar"}
    for bloco in result.values():
        assert "erro" in bloco


# ---------------------------------------------------------------------------
# Vazamento de chave
# ---------------------------------------------------------------------------


def _erro_com_chave_na_url() -> Exception:
    request = httpx.Request(
        "GET", f"https://api.scraperapi.com/?api_key={_CHAVE_FALSA}&url=https://www.noticiasagricolas.com.br/"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


def test_fetch_porto_nao_vaza_chave_em_erro(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.collectors.soja_disponivel.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.get.side_effect = _erro_com_chave_na_url()
        result = sd.fetch_porto()
    assert "erro" in result
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]
