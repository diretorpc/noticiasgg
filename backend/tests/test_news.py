import pytest
import os
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.collectors.news import (
    _parse_rss_date, _collect_rss, _is_fresh, _fetch_newsapi,
    SOURCES_FINANCE, SOURCES_TECH, _AI_QUERY, _RSS_FEEDS_AI,
)
from backend.tests.conftest import coleta_unica

client = TestClient(app)


def _fresh_rss() -> bytes:
    now = datetime.now(timezone.utc)
    d1 = format_datetime(now - timedelta(hours=1))
    d2 = format_datetime(now - timedelta(hours=2))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Global economy slows</title>
      <link>https://example.com/article-1</link>
      <pubDate>{d1}</pubDate>
      <description>Economy slowdown hits markets.</description>
    </item>
    <item>
      <title>Markets rally on Fed pause</title>
      <link>https://example.com/article-2</link>
      <pubDate>{d2}</pubDate>
      <description>Fed holds rates steady.</description>
    </item>
  </channel>
</rss>""".encode()


@pytest.mark.unit
def test_news_sem_chave_retorna_500():
    with patch.dict(os.environ, {"NEWS_API_KEY": ""}):
        resp = client.get("/api/collectors/news")
        assert resp.status_code == 500


# Uma coleta real por rodada, reaproveitada pelos 3 testes de contrato.
# Antes eram 3 coletas completas (15 conexões cada = 45 por rodada), e cada
# uma varre NewsAPI + Google News + todos os feeds internacionais.
resposta_news = coleta_unica("/api/collectors/news", "NEWS_API_KEY")


def test_news_schema_com_chave(resposta_news):
    assert resposta_news.status_code == 200
    body = resposta_news.json()
    assert "data" in body
    assert "collected_at" in body


def test_news_retorna_lista_com_chave(resposta_news):
    assert isinstance(resposta_news.json()["data"], list)


def test_news_campos_obrigatorios_com_chave(resposta_news):
    for a in resposta_news.json()["data"]:
        assert "titulo" in a
        assert "fonte" in a
        assert "url" in a


@pytest.mark.unit
def test_parse_rss_date_rfc2822():
    result = _parse_rss_date("Mon, 02 Jun 2026 10:00:00 +0000")
    assert result is not None
    assert "2026" in result


@pytest.mark.unit
def test_parse_rss_date_none():
    assert _parse_rss_date(None) is None


@pytest.mark.unit
def test_parse_rss_date_invalid():
    # data inválida → retorna None
    assert _parse_rss_date("not-a-date") is None


def _feeds_usados(include_ai: bool) -> list[str]:
    """Roda collect() e devolve os NOMES dos feeds RSS que ele mandou coletar."""
    import os
    from backend.collectors import news as news_mod
    capturado: list[str] = []

    def fake_collect_rss(client, feeds, vistos):
        capturado.extend(nome for nome, _ in feeds)
        return []

    with patch.dict(os.environ, {"NEWS_API_KEY": "k"}), \
         patch("backend.collectors.news._collect_rss", side_effect=fake_collect_rss), \
         patch("backend.collectors.news.httpx.Client"):
        news_mod.collect(include_ai=include_ai, include_newsapi=False)
    return capturado


@pytest.mark.unit
def test_collect_sem_ai_exclui_feeds_rss_de_ia():
    """include_ai=False tem que valer para o RSS também, não só para o NewsAPI.

    Regressão do caso real de 21/07/2026: o alert_checker pedia include_ai=False e
    mesmo assim recebia MIT Technology Review/VentureBeat, que entupiam as 5 vagas
    de classificação com artigos de nota 1 — a notícia de mundo/economia ficava na
    fila sem nunca ser olhada.
    """
    nomes = _feeds_usados(include_ai=False)
    nomes_ai = [n for n, _ in _RSS_FEEDS_AI]
    assert nomes, "os feeds internacionais têm que continuar sendo coletados"
    for n in nomes_ai:
        assert n not in nomes, f"feed de IA '{n}' não deveria estar presente"


@pytest.mark.unit
def test_collect_com_ai_mantem_feeds_rss_de_ia():
    """Guarda: o boletim/chat (include_ai padrão=True) segue recebendo IA."""
    nomes = _feeds_usados(include_ai=True)
    for n, _ in _RSS_FEEDS_AI:
        assert n in nomes, f"feed de IA '{n}' deveria estar presente"


@pytest.mark.unit
def test_collect_rss_parses_items():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = _fresh_rss()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    feeds = [("Test Source", "https://example.com/rss")]
    vistos: set = set()
    artigos = _collect_rss(mock_client, feeds, vistos)

    assert len(artigos) == 2
    assert artigos[0]["fonte"] == "Test Source"
    assert artigos[0]["titulo"] == "Global economy slows"
    assert artigos[0]["url"] == "https://example.com/article-1"


@pytest.mark.unit
def test_collect_rss_deduplicates():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = _fresh_rss()

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    feeds = [("Test Source", "https://example.com/rss")]
    vistos = {"https://example.com/article-1"}  # já visto
    artigos = _collect_rss(mock_client, feeds, vistos)

    assert len(artigos) == 1
    assert artigos[0]["url"] == "https://example.com/article-2"


@pytest.mark.unit
def test_collect_rss_ignora_erro_http():
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    artigos = _collect_rss(mock_client, [("Bad Feed", "https://bad.url/rss")], set())
    assert artigos == []


@pytest.mark.unit
def test_collect_rss_ignora_xml_invalido():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"not xml at all"

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    artigos = _collect_rss(mock_client, [("Bad XML", "https://bad.url/rss")], set())
    assert artigos == []


@pytest.mark.unit
def test_sources_finance_contem_novas_fontes():
    for source in ("associated-press", "the-washington-post", "business-insider", "politico"):
        assert source in SOURCES_FINANCE


@pytest.mark.unit
def test_sources_tech_contem_fontes_ia():
    for source in ("techcrunch", "wired", "the-verge", "ars-technica"):
        assert source in SOURCES_TECH


@pytest.mark.unit
def test_ai_query_contem_termos_relevantes():
    for term in ("artificial intelligence", "OpenAI", "Anthropic", "LLM"):
        assert term in _AI_QUERY


@pytest.mark.unit
def test_rss_feeds_ai_contem_mit_e_venturebeat():
    nomes = [nome for nome, _ in _RSS_FEEDS_AI]
    assert "MIT Technology Review" in nomes
    assert "VentureBeat AI" in nomes


@pytest.mark.unit
def test_fetch_newsapi_429_reporta_erro():
    errors: list[str] = []
    mock_client = MagicMock()
    mock_client.get.return_value = MagicMock(status_code=429)
    artigos = _fetch_newsapi(mock_client, "https://newsapi.org/v2/everything", {}, set(), errors, "finance")
    assert artigos == []
    assert errors == ["newsapi finance: HTTP 429"]


@pytest.mark.unit
def test_fetch_newsapi_429_sem_lista_de_erros_nao_quebra():
    mock_client = MagicMock()
    mock_client.get.return_value = MagicMock(status_code=429)
    artigos = _fetch_newsapi(mock_client, "https://newsapi.org/v2/everything", {}, set(), None, "br")
    assert artigos == []


@pytest.mark.unit
def test_collect_sem_newsapi_busca_apenas_rss():
    with patch.dict(os.environ, {"NEWS_API_KEY": "fake-key"}), \
         patch("backend.collectors.news._fetch_newsapi") as mock_newsapi, \
         patch("backend.collectors.news._collect_rss", return_value=[]) as mock_rss:
        from backend.collectors import news
        news.collect(include_newsapi=False)
    mock_newsapi.assert_not_called()
    mock_rss.assert_called_once()


@pytest.mark.unit
def test_collect_sem_ai_faz_apenas_duas_chamadas_newsapi():
    with patch.dict(os.environ, {"NEWS_API_KEY": "fake-key"}), \
         patch("backend.collectors.news._fetch_newsapi", return_value=[]) as mock_newsapi, \
         patch("backend.collectors.news._collect_rss", return_value=[]):
        from backend.collectors import news
        news.collect(include_ai=False)
    assert mock_newsapi.call_count == 2


@pytest.mark.unit
def test_collect_rss_multiplos_feeds_deduplicados():
    """Dois feeds com a mesma URL em artigos distintos — sem duplicata."""
    now = datetime.now(timezone.utc)
    d = format_datetime(now - timedelta(hours=1))

    def _rss(link: str, title: str) -> bytes:
        return f"""<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>{title}</title><link>{link}</link><pubDate>{d}</pubDate></item>
        </channel></rss>""".encode()

    responses = [
        MagicMock(status_code=200, content=_rss("https://example.com/a1", "AI news 1")),
        MagicMock(status_code=200, content=_rss("https://example.com/a1", "AI news 1")),  # duplicada
        MagicMock(status_code=200, content=_rss("https://example.com/a2", "AI news 2")),
    ]
    mock_client = MagicMock()
    mock_client.get.side_effect = responses

    feeds = [
        ("Feed A", "https://feed-a.com/rss"),
        ("Feed B", "https://feed-b.com/rss"),
        ("Feed C", "https://feed-c.com/rss"),
    ]
    artigos = _collect_rss(mock_client, feeds, set())
    urls = [a["url"] for a in artigos]
    assert len(urls) == len(set(urls)), "URLs duplicadas encontradas"


@pytest.mark.unit
def test_is_fresh_data_sem_fuso_horario_e_tratada_como_utc():
    """Data sem fuso derrubava a comparação com TypeError, e o 'except: return True'
    engolia o erro — notícia de 10 dias entrava como fresca, para sempre e em silêncio."""
    velha = (datetime.now(timezone.utc) - timedelta(days=10)).replace(tzinfo=None)
    assert _is_fresh(velha.isoformat()) is False

    recente = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(tzinfo=None)
    assert _is_fresh(recente.isoformat()) is True


@pytest.mark.unit
def test_is_fresh_com_fuso_continua_igual():
    """Guarda de regressão: o caminho que já funcionava não pode mudar."""
    velha = datetime.now(timezone.utc) - timedelta(days=10)
    recente = datetime.now(timezone.utc) - timedelta(hours=2)
    assert _is_fresh(velha.isoformat()) is False
    assert _is_fresh(recente.isoformat()) is True


@pytest.mark.unit
def test_is_fresh_ilegivel_continua_passando():
    """Comportamento NÃO alterado de propósito: data ilegível ou ausente segue passando.
    Só o caso 'sem fuso' foi consertado."""
    assert _is_fresh(None) is True
    assert _is_fresh("ontem de manha") is True


def _artigo(fonte: str, horas_atras: float) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(hours=horas_atras)
    return {"titulo": f"{fonte} h{horas_atras}", "fonte": fonte,
            "url": f"https://{fonte}.com/{horas_atras}", "publicado_em": dt.isoformat(),
            "resumo": None}


@pytest.mark.unit
def test_ordena_por_data_mais_recente_primeiro():
    """A ordem da lista de fontes decidia quem era lido: o robô varre só os 20
    primeiros e classifica 5. Fonte no fim da lista morria de fome, por mais
    recente que fosse a notícia dela."""
    from backend.collectors.news import _ordena_por_recencia
    bruto = [_artigo("velha", 40), _artigo("nova", 0.5), _artigo("media", 10)]
    out = _ordena_por_recencia(bruto)
    assert [a["fonte"] for a in out] == ["nova", "media", "velha"]


@pytest.mark.unit
def test_ordena_sem_data_vai_para_o_fim():
    """Data ausente/ilegível é o dado menos confiável — não pode furar a fila."""
    from backend.collectors.news import _ordena_por_recencia
    sem_data = {"titulo": "x", "fonte": "sem_data", "url": "u", "publicado_em": None}
    ilegivel = {"titulo": "y", "fonte": "ilegivel", "url": "v", "publicado_em": "ontem"}
    out = _ordena_por_recencia([sem_data, _artigo("com_data", 30), ilegivel])
    assert out[0]["fonte"] == "com_data"
    assert {a["fonte"] for a in out[1:]} == {"sem_data", "ilegivel"}


@pytest.mark.unit
def test_ordena_nao_perde_nem_duplica_artigo():
    from backend.collectors.news import _ordena_por_recencia
    bruto = [_artigo(f"f{i}", i) for i in range(10)]
    out = _ordena_por_recencia(bruto)
    assert len(out) == 10
    assert {a["url"] for a in out} == {a["url"] for a in bruto}


@pytest.mark.unit
def test_google_news_url_forca_janela_de_48h():
    """Sem 'when:2d' o Google ordena por relevância e devolve notícia velha: medido
    em 11/08/2026, 'OPEC oil production' voltou 0 itens frescos sem o parâmetro e 2 com."""
    from backend.collectors.news import _google_news
    url = _google_news("OPEC oil production")
    assert "when%3A2d" in url or "when:2d" in url
    assert url.startswith("https://news.google.com/rss/search?q=")
    assert "ceid=" in url and "hl=" in url


@pytest.mark.unit
def test_google_news_url_escapa_a_busca():
    from backend.collectors.news import _google_news
    url = _google_news("soja & milho")
    assert " " not in url
    assert "%26" in url  # o & virou escape, não separador de parâmetro


@pytest.mark.unit
def test_feeds_padrao_sem_url_duplicada():
    """Duas entradas com a mesma URL gastariam tempo de rede coletando o mesmo."""
    from backend.collectors.news import _RSS_FEEDS
    urls = [u for _, u in _RSS_FEEDS]
    assert len(urls) == len(set(urls))
    nomes = [n for n, _ in _RSS_FEEDS]
    assert len(nomes) == len(set(nomes))


@pytest.mark.unit
def test_fonte_tagarela_nao_engole_a_janela():
    """Ordenar só por data fazia fonte que publica muito engolir a janela: medido em
    11/08/2026, 6 fontes de 20 ocupavam as 20 vagas que o alert_checker examina.
    Guarda a propriedade, não a implementação: nenhuma fonte repete antes de todas
    terem tido a primeira vaga."""
    from backend.collectors.news import _ordena_por_recencia
    tagarela = [_artigo("G1", h) for h in (0.1, 0.2, 0.3, 0.4, 0.5)]
    quietas = [_artigo("OPEP", 3), _artigo("USDA", 4)]
    out = _ordena_por_recencia(tagarela + quietas)
    assert set(a["fonte"] for a in out[:3]) == {"G1", "OPEP", "USDA"}


@pytest.mark.unit
def test_limite_por_fonte_nao_descarta_artigo():
    """O excedente é rebaixado, não jogado fora — o relatório diário usa a lista toda."""
    from backend.collectors.news import _ordena_por_recencia
    bruto = [_artigo("G1", h) for h in (0.1, 0.2, 0.3, 0.4, 0.5)] + [_artigo("OPEP", 3)]
    out = _ordena_por_recencia(bruto)
    assert len(out) == 6
    assert {a["url"] for a in out} == {a["url"] for a in bruto}


@pytest.mark.unit
def test_excedente_mantem_ordem_de_data_entre_si():
    from backend.collectors.news import _ordena_por_recencia
    out = _ordena_por_recencia([_artigo("G1", h) for h in (0.5, 0.1, 0.3, 0.2, 0.4)])
    assert [a["titulo"] for a in out] == [f"G1 h{h}" for h in (0.1, 0.2, 0.3, 0.4, 0.5)]


@pytest.mark.unit
def test_source_health_separa_vivas_de_mortas():
    """O boletim diário conferia só se a chave EXISTE, nunca se a fonte TRAZ algo.
    Foi por isso que 5 feeds ficaram meses mortos sem ninguém ver."""
    from backend.collectors.news import source_health
    def _fake(client, feeds, vistos):
        return [_artigo("Viva A", 1), _artigo("Viva A", 2), _artigo("Viva B", 3)]
    feeds = [("Viva A", "u1"), ("Viva B", "u2"), ("Morta", "u3")]
    with patch("backend.collectors.news._collect_rss", _fake), \
         patch("backend.collectors.news._feeds", return_value=feeds):
        out = source_health()
    assert out["total"] == 3
    assert out["vivas"] == 2
    assert out["mortas"] == ["Morta"]


@pytest.mark.unit
def test_source_health_falha_de_rede_nao_estoura():
    from backend.collectors.news import source_health
    with patch("backend.collectors.news._collect_rss", side_effect=RuntimeError("rede caiu")):
        out = source_health()
    assert out["erro"]
    assert out["vivas"] == 0


@pytest.mark.unit
def test_rodizio_da_uma_vaga_a_cada_fonte_antes_de_repetir():
    """Teto de 2 ainda deixava fonte tagarela comer a janela: medido 11/08/2026,
    11 fontes de 20 ocupavam as 20 vagas e as 6 buscas do Google ficavam fora."""
    from backend.collectors.news import _ordena_por_recencia
    tagarela = [_artigo("G1", h) for h in (0.1, 0.2, 0.3, 0.4)]
    quietas = [_artigo("OPEP", 5), _artigo("USDA", 9)]
    out = _ordena_por_recencia(tagarela + quietas)
    assert [a["fonte"] for a in out[:3]] == ["G1", "OPEP", "USDA"]
    assert out[3]["fonte"] == "G1"  # a 2ª do G1 só depois de todo mundo ter a 1ª


@pytest.mark.unit
def test_rodizio_ordena_por_data_dentro_de_cada_rodada():
    from backend.collectors.news import _ordena_por_recencia
    bruto = [_artigo("A", 5), _artigo("B", 1), _artigo("A", 6), _artigo("B", 2)]
    out = _ordena_por_recencia(bruto)
    assert [a["fonte"] for a in out] == ["B", "A", "B", "A"]
    assert out[0]["titulo"] == "B h1" and out[1]["titulo"] == "A h5"
