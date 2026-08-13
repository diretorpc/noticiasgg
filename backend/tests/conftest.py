"""⚠️ NÃO GUARDE ESTADO NESTE ARQUIVO — contador, cache, lista, classe de exceção.

O pytest o carrega em DUAS cópias distintas em memória (`tests.conftest` e
`backend.tests.conftest`). Metade do sistema enxerga uma, metade a outra. Isso já
custou uma rodada: a primeira versão da trava de rede definia a exceção aqui e
`pytest.raises` não reconhecia o erro, porque eram duas classes diferentes.
Estado vai para módulo próprio, importado por caminho absoluto — ver
`backend/tests/_trava_rede.py`.
"""
import os

import pytest

from backend.tests import _trava_rede

_trava_rede.instalar()


def coleta_unica(rota: str, chave_necessaria: str | None = None):
    """Fábrica de fixture: UMA chamada real por arquivo de teste, reaproveitada
    por todos os testes daquele arquivo.

    Por que existe: cada teste que refazia a mesma chamada multiplicava a batida
    na API do fornecedor (4 testes de cripto = 4 batidas no CoinGecko em ~2s),
    e era isso que disparava o bloqueio por excesso de requisições. A chamada
    REAL continua acontecendo — o que some é a repetição inútil dela, então a
    conferência de contrato (campo renomeado, tipo trocado) segue valendo.

    Efeito colateral aceito: se a única chamada falhar, todos os testes daquele
    arquivo reprovam juntos. Polui a leitura, mas não esconde nada."""
    @pytest.fixture(scope="module")
    def _coleta():
        if chave_necessaria and not os.getenv(chave_necessaria):
            pytest.skip(f"{chave_necessaria} não configurada")
        from fastapi.testclient import TestClient
        from backend.api.main import app
        return TestClient(app).get(rota)

    return _coleta


@pytest.fixture(autouse=True)
def _admin_allowlist(monkeypatch):
    """Allowlist de admin padrão para os testes que exercem rotas /api/admin.
    Testes que precisam do estado 'sem allowlist' sobrescrevem localmente."""
    monkeypatch.setenv("ADMIN_EMAILS", "matheusmouro@hotmail.com")


def pytest_collection_modifyitems(config, items):
    """Anota quais testes prometem 'sem rede'. Roda uma vez, na coleta."""
    for item in items:
        if item.get_closest_marker("unit"):
            _trava_rede.registrar_unit(item.nodeid)


def pytest_runtest_logstart(nodeid, location):
    # Dispara ANTES da fase de preparação — é o que faz a trava valer também
    # para fixture de escopo módulo (ex.: `coleta_unica`), que é montada ali
    # dentro. Uma fixture de escopo função chegaria tarde demais.
    _trava_rede.marcar_inicio(nodeid)


def pytest_runtest_logfinish(nodeid, location):
    _trava_rede.marcar_fim()
