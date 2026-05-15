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
