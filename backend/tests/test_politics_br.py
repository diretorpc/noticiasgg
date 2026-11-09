import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from backend.collectors import politics_br


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


_TERMOS_DE_CAMPANHA = ("eleic", "eleit", "candidat", "pesquisa", "campanha", "turno")


@pytest.mark.unit
@pytest.mark.parametrize("query", politics_br.QUERIES)
def test_query_nao_mira_a_campanha(query):
    """As eleições de 2026 acabaram (polls_br aposentado no PR #36). Busca de
    campanha trazia análise de derrota e pesquisa pós-eleição para a seção de
    política, que nem tem mais o bloco de pesquisas."""
    q = _sem_acento(query)
    for termo in _TERMOS_DE_CAMPANHA:
        assert termo not in q, f"{query!r} ainda mira a campanha ({termo!r})"


@pytest.mark.unit
@pytest.mark.parametrize("query", politics_br.QUERIES)
def test_query_nao_crava_ano(query):
    """Ano dentro da busca apodrece calado: foi assim que "eleições 2026"
    sobreviveu à eleição. Tema que dura o mandato, sem data."""
    assert not re.search(r"\b(19|20)\d{2}\b", query), f"{query!r} crava um ano"


def _cliente_falso(respostas_por_query: dict):
    chamadas = []

    def get(url, params):
        chamadas.append(params)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"articles": respostas_por_query.get(params["q"], [])}
        return resp

    cliente = MagicMock()
    cliente.get.side_effect = get
    ctx = MagicMock()
    ctx.__enter__.return_value = cliente
    ctx.__exit__.return_value = False
    return ctx, chamadas


@pytest.mark.unit
def test_collect_manda_cada_query_para_a_newsapi():
    ctx, chamadas = _cliente_falso({})
    with patch.dict(os.environ, {"NEWS_API_KEY": "k"}), \
         patch("backend.collectors.politics_br.httpx.Client", return_value=ctx):
        politics_br.collect()
    assert [c["q"] for c in chamadas] == politics_br.QUERIES
    assert all(c["language"] == "pt" for c in chamadas)


@pytest.mark.unit
def test_collect_descarta_noticia_velha_e_repetida():
    agora = datetime.now(timezone.utc)
    fresca = {"url": "https://x/1", "title": "Fresca", "source": {"name": "F"},
              "publishedAt": (agora - timedelta(hours=2)).isoformat().replace("+00:00", "Z")}
    velha = {"url": "https://x/2", "title": "Velha", "source": {"name": "F"},
             "publishedAt": (agora - timedelta(hours=100)).isoformat().replace("+00:00", "Z")}
    q1, q2 = politics_br.QUERIES[0], politics_br.QUERIES[1]
    ctx, _ = _cliente_falso({q1: [fresca, velha], q2: [fresca]})
    with patch.dict(os.environ, {"NEWS_API_KEY": "k"}), \
         patch("backend.collectors.politics_br.httpx.Client", return_value=ctx):
        artigos = politics_br.collect()
    assert [a["titulo"] for a in artigos] == ["Fresca"]
