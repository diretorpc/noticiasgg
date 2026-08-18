import pytest

from backend.services import report_engine, integrity

pytestmark = pytest.mark.unit

# Simula indicators_us.collect() com FRED 4/4 fora do ar: nenhuma série
# individualmente derruba o dict (degrada por série), então o TOPO não tem
# "erro" — só `_safe_dict`/`_safe_collect` (checagem de topo) deixava passar
# o texto de erro HTTP direto pro prompt e pro corpus do validador.
_IND_US_TODO_CAIDO = {
    "CPI (inflação EUA)": {"erro": "Server error 500 for url https://api.stlouisfed.org/..."},
    "PPI (preços ao produtor)": {"erro": "Server error 500 for url https://api.stlouisfed.org/..."},
    "Taxa de desemprego EUA": {"erro": "Server error 500 for url https://api.stlouisfed.org/..."},
    "Fed Funds Rate (juros EUA)": {"erro": "Server error 500 for url https://api.stlouisfed.org/..."},
}

_IND_US_PARCIAL = {
    "CPI (inflação EUA)": {"valor": 3.1, "data": "2026-07-01", "variacao": 0.1},
    "PPI (preços ao produtor)": {"erro": "Server error 500 for url https://api.stlouisfed.org/..."},
}


class _Corte:
    """Achado 5, revisão 18/08/2026 (4ª rodada): antes deste fix,
    `report_engine._safe_dict` e `integrity.build_fact_corpus` só olhavam
    "erro" no TOPO do dicionário. Coletor que degrada POR SÉRIE (indicators_us,
    indicators_br) não bate nesse teste — a série com erro HTTP entrava crua
    no prompt do relatório e no corpus do validador anti-alucinação."""


def test_safe_dict_descarta_serie_individual_com_erro():
    filtrado = report_engine._safe_dict(_IND_US_TODO_CAIDO)
    assert filtrado == {}, "todas as 4 séries falharam — nenhuma deveria sobrar"


def test_safe_dict_preserva_series_saudaveis_ao_lado_de_falhas():
    filtrado = report_engine._safe_dict(_IND_US_PARCIAL)
    assert "CPI (inflação EUA)" in filtrado
    assert "PPI (preços ao produtor)" not in filtrado


def test_safe_dict_continua_descartando_erro_de_topo():
    """Comportamento antigo preservado: coletor que falhou por completo
    ({"erro": ...} no topo, ex: exceção que escapou de _safe_collect)."""
    assert report_engine._safe_dict({"erro": "boom"}) == {}


def test_build_fact_corpus_nao_vaza_texto_de_erro_de_serie():
    data = {"indicators_us": _IND_US_TODO_CAIDO}
    corpus = integrity.build_fact_corpus(data)
    assert "Server error" not in corpus
    assert "stlouisfed" not in corpus


def test_build_fact_corpus_preserva_series_saudaveis():
    data = {"indicators_us": _IND_US_PARCIAL}
    corpus = integrity.build_fact_corpus(data)
    assert "3.1" in corpus
    assert "Server error" not in corpus
