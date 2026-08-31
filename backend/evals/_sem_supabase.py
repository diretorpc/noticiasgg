"""Trava que impede um eval de ler o Supabase de PRODUÇÃO.

Por que existe (31/08/2026): os evals se descrevem como "fixtures
DETERMINÍSTICOS" e mockavam as quatro ferramentas que existiam quando foram
escritos — `agro_br`, `stocks`, `web_search`, `agro_search`. A Story 2
acrescentou uma quinta, `get_sent_news`, que lê `news_log` no Supabase, e ela
é oferecida em TODA conversa. A pergunta canônica destes evals ("me fale mais
sobre essa notícia") é o gatilho literal da regra que manda chamá-la.

Sem esta trava o eval passaria a ler produção: o resultado dependeria de quais
alertas saíram naquela hora, e o determinismo — que é a razão de ser do
arquivo de fixtures — ia embora sem ninguém perceber.

A trava é de FALHAR, não de silenciar: `_client` levanta com mensagem clara em
vez de devolver vazio. Mock que devolve vazio esconde o acoplamento novo; mock
que estoura obriga quem acrescentar a próxima ferramenta a decidir o que ela
deve responder no eval.

Diferente de `backend/tests/_trava_rede.py`, que barra QUALQUER conexão: aqui a
rede tem que continuar aberta, porque o eval chama a API da Anthropic de
verdade — é isso que ele mede.
"""
import contextlib
from unittest.mock import patch

from backend.services import supabase

# Notícia congelada que a ferramenta `get_sent_news` devolve dentro do eval.
# Os números batem com o artigo dos fixtures: quem inventar 67% ou 2025 está
# inventando, não copiando.
NEWS_LOG_PADRAO = [{
    "news_id": "fixture001",
    "titulo_pt": "Milho dos EUA perde qualidade, aponta USDA",
    "titulo_original": "Corn Rated 61% Good to Excellent",
    "fonte": "Reuters",
    "url": "https://www.usda.gov/nass/crop-progress-2026-08-17",
    "url_final": "https://www.usda.gov/nass/crop-progress-2026-08-17",
    "categoria": "OFERTA/CLIMA",
    "resumo": "Condição boa/excelente do milho em 61%.",
    "direcao": "alta",
    "score": 7,
    "ativos": ["milho", "soja"],
    "publicado_em": "2026-08-17T14:00:00+00:00",
    "sent_at": "2026-08-17T14:05:00+00:00",
}]


@contextlib.contextmanager
def supabase_congelado(news_log: list[dict] | None = None):
    """`get_sent_news` responde a fixture; qualquer outro acesso ao banco estoura.

    O formato de retorno acompanha o contrato real de `get_news_log`
    (`{"itens": [...], "truncado": bool}`) — devolver uma lista crua, como o
    plano escrito sugeria, faz `_get_sent_news` estourar em `registro.get`.
    """
    linhas = NEWS_LOG_PADRAO if news_log is None else news_log
    registro = {"itens": list(linhas), "truncado": False}

    def _proibido(*a, **k):
        raise RuntimeError(
            "eval tentou abrir conexão com o Supabase de produção. "
            "Se uma ferramenta nova passou a ler o banco, congele a resposta "
            "dela em backend/evals/_sem_supabase.py — não solte o eval no dado real."
        )

    with patch.object(supabase, "_client", _proibido), \
         patch.object(supabase, "get_news_log", lambda *a, **k: dict(registro)):
        yield
