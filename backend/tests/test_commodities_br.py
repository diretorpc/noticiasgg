import pytest
from bs4 import BeautifulSoup

from backend.collectors import commodities_br as cb

# HTML espelhando a estrutura real do noticiasagricolas (capturada 2026-07-12).
_SOJA = b"""<table>
<tr><th>Data</th><th>Valor R$</th><th>Variacao (%)</th></tr>
<tr><td>10/07/2026</td><td>140,44</td><td>+0,14</td></tr>
<tr><td>Ver historico</td></tr>
</table>"""

# Mesma tabela com as colunas REORDENADAS (variacao antes do preco). A deteccao por
# cabecalho deve continuar lendo o preco certo; o antigo indice fixo pegaria a variacao.
_SOJA_REORDER = b"""<table>
<tr><th>Data</th><th>Variacao (%)</th><th>Valor R$</th></tr>
<tr><td>10/07/2026</td><td>+0,14</td><td>140,44</td></tr>
</table>"""

# Tabela com coluna extra (Estado) e varias pracas — linha_idx seleciona a UF.
_SUINOS = b"""<table>
<tr><th>Data</th><th>Estado</th><th>R$/Kg</th><th>Variacao (%)</th></tr>
<tr><td>10/07/2026</td><td>MG - posto</td><td>5,88</td><td>0,00</td></tr>
<tr><td>10/07/2026</td><td>PR - a retirar</td><td>4,86</td><td>0,00</td></tr>
</table>"""

_SEM_CABECALHO = b"""<table>
<tr><td>10/07/2026</td><td>140,44</td><td>+0,14</td></tr>
</table>"""

_CABECALHO_IRRECONHECIVEL = b"""<table>
<tr><th>Data</th><th>Coluna X</th><th>Coluna Y</th></tr>
<tr><td>10/07/2026</td><td>140,44</td><td>+0,14</td></tr>
</table>"""


class _FakeResp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class _FakeClient:
    def __init__(self, content):
        self._content = content

    def get(self, *a, **k):
        return _FakeResp(self._content)


def _fetch(content, estado="PR", linha_idx=1):
    return cb._fetch_noticias_agro(_FakeClient(content), "http://x", "R$/sc", estado, linha_idx)


@pytest.mark.unit
def test_preco_lido_pelo_cabecalho():
    r = _fetch(_SOJA)
    assert r["preco"] == 140.44
    assert r["variacao_pct"] == 0.14
    assert "erro" not in r


@pytest.mark.unit
def test_robusto_a_reordenacao_de_colunas():
    # O ponto central do fix: colunas trocadas, preco continua correto.
    r = _fetch(_SOJA_REORDER)
    assert r["preco"] == 140.44
    assert r["variacao_pct"] == 0.14


@pytest.mark.unit
def test_seleciona_linha_por_indice_multi_estado():
    r = _fetch(_SUINOS, estado="PR", linha_idx=2)
    assert r["preco"] == 4.86
    assert r["variacao_pct"] == 0.0


@pytest.mark.unit
def test_cabecalho_ausente_retorna_erro_nao_preco_errado():
    r = _fetch(_SEM_CABECALHO)
    assert r["preco"] is None
    assert "erro" in r


@pytest.mark.unit
def test_cabecalho_irreconhecivel_falha_alto():
    # Prefere gritar (erro) a reportar um numero de coluna desconhecida como preco.
    r = _fetch(_CABECALHO_IRRECONHECIVEL)
    assert r["preco"] is None
    assert r["erro"] == "cabeçalho não reconhecido"


@pytest.mark.unit
def test_header_columns_encontra_indices():
    tabela = BeautifulSoup(_SUINOS, "html.parser").find("table")
    assert cb._header_columns(tabela) == (2, 3)
