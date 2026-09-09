import pytest

from backend.collectors import agro_br

pytestmark = pytest.mark.unit

# Cabeçalhos copiados das páginas reais em 09/09/2026 (primeira tabela de cada).
_ALGODAO_HTML = b"""<table>
<tr><th>Data</th><th>Valor (8 dias) Cent/R$/lb</th><th>Varia\xc3\xa7\xc3\xa3o Di\xc3\xa1ria (%)</th></tr>
<tr><td>08/09/2026</td><td>439,45</td><td>-0,12%</td></tr>
</table>"""
_OVOS_HTML = b"""<table>
<tr><th>Data</th><th>Regi\xc3\xa3o/Tipo</th><th>R$/30 dz</th><th>Varia\xc3\xa7\xc3\xa3o/Semana (%)</th></tr>
<tr><td></td><td>Bastos (SP) - FOB</td><td>***</td><td>***</td></tr>
<tr><td>08/09/2026</td><td>Branco</td><td>134,17</td><td>+0,06</td></tr>
</table>"""


class _Resp:
    def __init__(self, content): self.content = content
    def raise_for_status(self): pass


class _Client:
    def __init__(self, content): self._c = content
    def get(self, url, headers=None): return _Resp(self._c)


def _cfg(tabela: dict, nome: str):
    path, unidade, estado, linha = tabela[nome]
    return path, unidade, estado, linha


@pytest.mark.unit
def test_algodao_sai_com_a_unidade_da_fonte():
    """A 1ª tabela é o indicador Cepea em centavos de real por libra. Colar
    'R$/@ 15kg' nesse número entregava 439 R$/@ (real ~137)."""
    path, unidade, estado, linha = _cfg(agro_br.NOTICIAS_AGRO_COMMODITIES, "Algodao SP")
    out = agro_br._fetch_noticias_agro(_Client(_ALGODAO_HTML), path, unidade, estado, linha)
    assert out.get("erro") is None
    assert out["preco"] == 439.45
    assert out["variacao_pct"] == -0.12  # célula vem como '-0,12%'; o % derrubava o parse
    assert "cent" in out["unidade"].lower() and "lb" in out["unidade"]


@pytest.mark.unit
def test_ovos_sai_com_a_unidade_da_fonte():
    """Tabela Cepea Bastos é R$ por 30 dúzias. 'R$/dz' inflava 30x."""
    path, unidade, estado, linha = _cfg(agro_br.NOTICIAS_AGRO_GADO, "Ovos SP")
    out = agro_br._fetch_noticias_agro(_Client(_OVOS_HTML), path, unidade, estado, linha)
    assert out.get("erro") is None
    assert out["preco"] == 134.17
    assert out["unidade"] == "R$/30 dz"


@pytest.mark.unit
def test_cabecalho_em_centavos_com_unidade_em_reais_vira_erro_e_nao_numero():
    """Se o site trocar a tabela de novo, queremos erro visível, não preço errado."""
    out = agro_br._fetch_noticias_agro(_Client(_ALGODAO_HTML), "/cotacoes/algodao", "R$/@ 15kg", "SP", 1)
    assert out["preco"] is None
    assert "unidade" in out["erro"].lower()


@pytest.mark.unit
def test_cabecalho_por_30_duzias_com_unidade_por_duzia_vira_erro():
    out = agro_br._fetch_noticias_agro(_Client(_OVOS_HTML), "/cotacoes/ovos", "R$/dz", "SP", 2)
    assert out["preco"] is None
    assert "unidade" in out["erro"].lower()


_AMENDOIM_HTML = b"""<table>
<tr><th>Tipo / Unidade medida</th><th>Pre\xc3\xa7o (R$)</th><th>Varia\xc3\xa7\xc3\xa3o (%)</th></tr>
<tr><td>Ceasa - Campinas/ SP</td><td>***</td><td>***</td></tr>
<tr><td>Com casca / kg</td><td>7,00</td><td>0,00</td></tr>
<tr><td>Sem casca / kg</td><td>8,00</td><td>0,00</td></tr>
<tr><td>Ceasa - Belo Horizonte/ MG</td><td>***</td><td>***</td></tr>
<tr><td>Com casca / saca 25 kg</td><td>220,00</td><td>0,00</td></tr>
</table>"""
_FEIJAO_HTML = b"""<table>
<tr><th>Regi\xc3\xa3o</th><th>Valor R$/sc</th><th>Var./Dia (%)</th></tr>
<tr><td>Curitiba</td><td>s/ cota\xc3\xa7\xc3\xa3o</td><td>-</td></tr>
<tr><td>Itapeva</td><td>332,83</td><td>+2,49</td></tr>
</table>"""


@pytest.mark.unit
def test_amendoim_sai_por_quilo_como_na_fonte():
    """Linha lida é 'Com casca / kg' (Campinas/SP). Rotular 'R$/sc 25kg' mentia 31x."""
    path, unidade, estado, linha = _cfg(agro_br.NOTICIAS_AGRO_COMMODITIES, "Amendoim SP")
    out = agro_br._fetch_noticias_agro(_Client(_AMENDOIM_HTML), path, unidade, estado, linha)
    assert out.get("erro") is None
    assert out["preco"] == 7.0
    assert out["unidade"] == "R$/kg"


@pytest.mark.unit
def test_unidade_na_linha_diverge_da_configurada_vira_erro():
    out = agro_br._fetch_noticias_agro(_Client(_AMENDOIM_HTML), "/cotacoes/amendoim", "R$/sc 25kg", "SP", 2)
    assert out["preco"] is None
    assert "unidade" in out["erro"].lower()


@pytest.mark.unit
def test_feijao_le_cabecalho_var_dia_e_linha_com_cotacao():
    """'Var./Dia' não casava com 'varia' e a linha 1 é 's/ cotação': feijão
    estava morto em produção. A praça viva é Itapeva, que é SP."""
    assert "Feijao PR" not in agro_br.NOTICIAS_AGRO_COMMODITIES
    path, unidade, estado, linha = _cfg(agro_br.NOTICIAS_AGRO_COMMODITIES, "Feijao SP")
    out = agro_br._fetch_noticias_agro(_Client(_FEIJAO_HTML), path, unidade, estado, linha)
    assert out.get("erro") is None
    assert out["preco"] == 332.83
    assert out["variacao_pct"] == 2.49
    assert out["estado"] == "SP"


@pytest.mark.unit
def test_guarda_compara_palavra_inteira_nao_substring():
    """'Percentual' contém 'cent' e 'média 30 dias' contém '30 d': não são unidade."""
    html = b"""<table><tr><th>Regi\xc3\xa3o</th><th>Valor R$/sc (m\xc3\xa9dia 30 dias)</th><th>Varia\xc3\xa7\xc3\xa3o Percentual (%)</th></tr>
<tr><td>X</td><td>100,00</td><td>1,00</td></tr></table>"""
    out = agro_br._fetch_noticias_agro(_Client(html), "/x", "R$/sc 60kg", "SP", 1)
    assert out.get("erro") is None
    assert out["preco"] == 100.0


@pytest.mark.unit
def test_erro_de_unidade_nao_carrega_markup_cru_para_o_modelo():
    html = b"""<table><tr><th>Data</th><th>Valor Cent/R$/lb &lt;script&gt;x&lt;/script&gt; """ + b"a" * 300 + b"""</th><th>Varia\xc3\xa7\xc3\xa3o</th></tr>
<tr><td>1</td><td>1,00</td><td>0,00</td></tr></table>"""
    out = agro_br._fetch_noticias_agro(_Client(html), "/x", "R$/@ 15kg", "SP", 1)
    assert "<" not in out["erro"]
    assert len(out["erro"]) < 200
