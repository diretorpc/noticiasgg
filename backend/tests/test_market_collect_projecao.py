"""market.collect() é o único caminho que alimenta o relatório diário e o
corpus de integridade (teto de 6.000 chars — `integrity.build_fact_corpus`).
`_parse_v8_meta` ganhou campos extras (`atual`/`anterior`/`atualizado_em`)
para `collectors/soja_disponivel.py` — esses testes provam que `collect()`
continua devolvendo só o formato antigo por símbolo, sem duplicar as
asserções de schema já cobertas (com rede real) em `test_market.py`."""
from unittest.mock import patch

import pytest

from backend.collectors import market

pytestmark = pytest.mark.unit


def test_collect_projeta_so_preco_e_variacao_pct_no_caminho_direto():
    direto = {
        "^BVSP": {
            "preco": 130000.5,
            "variacao_pct": 1.23,
            "atual": 130000.5321,
            "anterior": 128000.111,
            "atualizado_em": 1725480000,
        },
    }
    # _fetch_all_direct só devolve o IBOVESPA — os demais símbolos de SYMBOLS
    # caem no fallback do ScraperAPI, que também precisa ser simulado (senão
    # o teste "unit" sai batendo na rede de verdade pelos outros 9 símbolos).
    with patch.object(market, "_fetch_all_direct", return_value=direto), \
         patch.object(market, "_fetch_all_scraperapi", return_value={}):
        resultado = market.collect()

    assert resultado["bolsas"]["IBOVESPA"] == {"preco": 130000.5, "variacao_pct": 1.23}


def test_collect_projeta_e_preserva_erro_no_caminho_scraperapi():
    """O fallback do ScraperAPI não passa por `_parse_v8_meta` em caso de
    falha — devolve {"preco": None, "variacao_pct": None, "erro": ...} sem
    "atual"/"anterior". A projeção não pode derrubar o campo "erro"."""
    with patch.object(market, "_fetch_all_direct", return_value={}), \
         patch.object(market, "_fetch_all_scraperapi") as mock_fallback:
        mock_fallback.return_value = {
            ("bolsas", "IBOVESPA"): {"preco": None, "variacao_pct": None, "erro": "sem chave ScraperAPI"},
        }
        resultado = market.collect()

    assert resultado["bolsas"]["IBOVESPA"] == {
        "preco": None, "variacao_pct": None, "erro": "sem chave ScraperAPI",
    }
