import json
from unittest.mock import MagicMock, patch

import pytest

from backend.services import alert_checker, supabase


def _fake_client(response):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)
    client.get = MagicMock(return_value=response)
    return client


@pytest.mark.unit
def test_log_sent_news_envia_campos_ricos():
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({
            "news_id": "abc123",
            "titulo_pt": "USDA mostra queda na qualidade do milho",
            "titulo_original": "Corn Rated 61% Good to Excellent",
            "fonte": "Farm Progress",
            "feed": "GN USDA/WASDE",
            "url": "https://news.google.com/rss/articles/abc",
            "url_publisher": "https://www.farmprogress.com",
            "categoria": "OFERTA/CLIMA",
            "resumo": "Condição boa/excelente do milho cai.",
            "resumo_fonte": "Corn conditions dropped to 61% good/excellent, USDA says.",
            "direcao": "alta",
            "score": 7,
            "ativos": ["milho", "soja"],
            "publicado_em": "2026-08-18T10:00:00+00:00",
        })
    path = client.post.call_args[0][0]
    enviado = client.post.call_args[1]["json"]
    assert path == "/news_log"
    assert enviado["news_id"] == "abc123"
    assert enviado["url"] == "https://news.google.com/rss/articles/abc"
    assert enviado["url_publisher"] == "https://www.farmprogress.com"
    assert enviado["fonte"] == "Farm Progress"
    assert enviado["feed"] == "GN USDA/WASDE"
    # resumo (análise da IA) e resumo_fonte (texto do RSS) são colunas separadas —
    # não podem se misturar (achado A3, revisão 18/08/2026)
    assert enviado["resumo"] == "Condição boa/excelente do milho cai."
    assert enviado["resumo_fonte"] == "Corn conditions dropped to 61% good/excellent, USDA says."
    assert enviado["ativos"] == ["milho", "soja"]
    assert enviado["score"] == 7
    assert "sent_at" in enviado


@pytest.mark.unit
def test_log_sent_news_publicado_em_invalido_e_descartado():
    """O caminho RSS sempre entrega ISO ou None (_parse_rss_date), mas o
    NewsAPI copia `publishedAt` cru. Um valor que o Postgres rejeita fazia a
    linha INTEIRA se perder — melhor descartar só o campo (achado A11)."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123", "publicado_em": "ontem de manha"})
    enviado = client.post.call_args[1]["json"]
    assert "publicado_em" not in enviado
    assert enviado["news_id"] == "abc123"


@pytest.mark.unit
def test_log_sent_news_publicado_em_valido_e_preservado():
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123", "publicado_em": "2026-08-18T10:00:00Z"})
    enviado = client.post.call_args[1]["json"]
    assert enviado["publicado_em"] == "2026-08-18T10:00:00Z"


@pytest.mark.unit
def test_log_sent_news_falha_registra_warning_sem_estourar(caplog):
    """A4: não pode ficar mudo. `caplog` prova que o warning saiu, sem imprimir
    nenhum segredo (o erro aqui é sintético, sem chave nenhuma envolvida)."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        with caplog.at_level("WARNING", logger="noticiasgg.supabase"):
            supabase.log_sent_news({"news_id": "abc123"})  # não deve levantar
    assert any("news_log write failed" in r.message for r in caplog.records)


@pytest.mark.unit
def test_log_sent_news_ignora_campo_desconhecido():
    """Chave fora do contrato não pode virar coluna inexistente no POST —
    o PostgREST devolve 400 e o registro se perde em silêncio."""
    resp = MagicMock(status_code=201)
    resp.raise_for_status = MagicMock()
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123", "coluna_que_nao_existe": "x"})
    enviado = client.post.call_args[1]["json"]
    assert "coluna_que_nao_existe" not in enviado
    assert enviado["news_id"] == "abc123"


@pytest.mark.unit
def test_log_sent_news_nunca_estoura_para_o_chamador():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(side_effect=RuntimeError("banco fora do ar"))
    with patch.object(supabase, "_client", return_value=client):
        supabase.log_sent_news({"news_id": "abc123"})  # não deve levantar


@pytest.mark.unit
def test_get_news_log_filtra_por_janela_e_ordena():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[{"news_id": "abc123", "titulo_pt": "t"}])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        resultado = supabase.get_news_log(hours=48, limit=5)
    url = client.get.call_args[0][0]
    assert url.startswith("/news_log?")
    assert "order=sent_at.desc" in url
    assert "limit=5" in url
    assert "sent_at=gte." in url
    assert resultado == {"itens": [{"news_id": "abc123", "titulo_pt": "t"}]}


@pytest.mark.unit
def test_get_news_log_falha_devolve_aviso_nao_lista_vazia_muda():
    """Lista vazia sozinha não distingue 'sem notícia' de 'banco fora do ar' —
    a Story 2 vai usar isto como ferramenta do Claude, e confundir os dois
    vira negativa autoritária errada (achado A5)."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=RuntimeError("timeout"))
    with patch.object(supabase, "_client", return_value=client):
        resultado = supabase.get_news_log()
    assert resultado == {"itens": [], "aviso": "registro indisponível"}


@pytest.mark.unit
def test_get_news_log_nao_houve_noticia_e_soh_lista_vazia_sem_aviso():
    """Dia calmo (consulta funcionou, zero linhas) não pode carregar 'aviso' —
    isso confundiria o consumidor com uma falha que não aconteceu."""
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        resultado = supabase.get_news_log()
    assert resultado == {"itens": []}
    assert "aviso" not in resultado


@pytest.mark.unit
def test_get_news_log_falha_registra_warning_sem_estourar(caplog):
    """A6: o irmão log_sent_news loga a própria falha e tem teste com caplog;
    get_news_log ficava mudo — o dono não teria como saber que a LEITURA
    quebrou sem olhar o `aviso` no retorno."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=RuntimeError("timeout"))
    with patch.object(supabase, "_client", return_value=client):
        with caplog.at_level("WARNING", logger="noticiasgg.supabase"):
            resultado = supabase.get_news_log()
    assert resultado == {"itens": [], "aviso": "registro indisponível"}
    assert any("get_news_log failed" in r.message for r in caplog.records)


@pytest.mark.unit
def test_get_news_log_trava_limit_malicioso():
    """`limit` entra CRU na URL (`_f()` só protege `cutoff`). Na Story 2 vem de
    texto interpretado pelo modelo — sem trava, `limit="5&titulo_pt=eq.x"` é
    injeção de filtro (achado A10)."""
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.get_news_log(limit="5&titulo_pt=eq.x")
    url = client.get.call_args[0][0]
    assert "titulo_pt=eq.x" not in url
    assert "limit=20" in url  # não convertível → cai no default


@pytest.mark.unit
def test_get_news_log_limit_acima_do_teto_e_cortado():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.get_news_log(limit=99999)
    assert "limit=100" in client.get.call_args[0][0]


@pytest.mark.unit
def test_get_news_log_hours_malicioso_ou_negativo_cai_no_piso():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=[])
    client = _fake_client(resp)
    with patch.object(supabase, "_client", return_value=client):
        supabase.get_news_log(hours=-5)
    # hours=-5 vira 1 → cutoff é ~agora, não estoura nem é ignorado
    assert client.get.call_args[0][0].count("sent_at=gte.") == 1


@pytest.mark.unit
def test_format_news_alert_inclui_link():
    result = {"categoria": "OFERTA/CLIMA", "ativos": ["milho"], "direcao": "alta"}
    msg = alert_checker._format_news_alert(
        result, "Reuters", "Milho perde qualidade nos EUA", 7, False,
        url="https://example.com/usda",
    )
    assert "https://example.com/usda" in msg
    assert "Milho perde qualidade nos EUA" in msg


@pytest.mark.unit
def test_format_news_alert_sem_url_nao_quebra():
    msg = alert_checker._format_news_alert({}, "Reuters", "Título", 7, False, url="")
    assert "Título" in msg
    assert "http" not in msg


@pytest.mark.unit
def test_format_news_alert_rejeita_url_sem_esquema_http():
    """Link de terceiro sem checagem entra na mensagem de graça — 6 dos 20 feeds
    são busca aberta do Google Notícias (achado A7)."""
    msg = alert_checker._format_news_alert(
        {}, "Reuters", "Título", 7, False, url="javascript:alert(1)"
    )
    assert "javascript:" not in msg


@pytest.mark.unit
def test_format_news_alert_rejeita_url_absurdamente_longa():
    msg = alert_checker._format_news_alert(
        {}, "Reuters", "Título", 7, False, url="https://example.com/" + "a" * 400
    )
    assert "🔗" not in msg


def _prepara_check_news(monkeypatch, artigo, classificacao, sent: int = 1):
    """Isola _check_news de rede, banco e IA. Devolve o dict onde o log cai
    e a lista de mensagens que teriam ido ao WhatsApp.

    `sent`: quantas entregas _broadcast finge ter feito — 0 simula a Evolution
    fora do ar (usado pelo teste irmão do A8: entrega falhou, log não roda)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste")
    gravado: dict = {}
    enviadas: list[str] = []

    monkeypatch.setattr(alert_checker.supabase, "log_sent_news", gravado.update)
    monkeypatch.setattr(alert_checker.supabase, "mark_news_sent", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "set_alert_triggered", lambda *a, **k: None)
    monkeypatch.setattr(alert_checker.supabase, "is_news_sent", lambda *a, **k: False)
    monkeypatch.setattr(alert_checker.supabase, "get_recent_sent_titles", lambda *a, **k: [])
    monkeypatch.setattr(alert_checker, "_cooldown_ok", lambda *a, **k: True)
    monkeypatch.setattr(
        alert_checker, "_broadcast",
        lambda msg, recipients, errors=None: (enviadas.append(msg) if sent else None, sent)[1],
    )
    monkeypatch.setattr("backend.collectors.news.collect", lambda *a, **k: [artigo])

    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=json.dumps(classificacao))]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_msg)
    monkeypatch.setattr(alert_checker, "Anthropic", lambda *a, **k: fake_client)
    return gravado, enviadas


_ARTIGO = {
    "titulo": "Corn Rated 61% Good to Excellent",
    "fonte": "Farm Progress",
    "feed": "GN USDA/WASDE",
    "url": "https://news.google.com/rss/articles/abc",
    "url_publisher": "https://www.farmprogress.com",
    "publicado_em": "2026-08-18T10:00:00+00:00",
    "resumo": "Corn conditions dropped to 61% good/excellent, USDA says.",
}

_CLASSIFICACAO = {
    "score": 7,
    "categoria": "OFERTA/CLIMA",
    "titulo_pt": "Milho dos EUA perde qualidade",
    "resumo": "Condição boa/excelente cai para 61%.",
    "ativos": ["milho"],
    "direcao": "alta",
    "duplicada": False,
}


@pytest.mark.unit
def test_check_news_grava_no_log_apos_entregar(monkeypatch):
    gravado, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert gravado["url"] == "https://news.google.com/rss/articles/abc"
    assert gravado["titulo_pt"] == "Milho dos EUA perde qualidade"
    assert gravado["titulo_original"] == "Corn Rated 61% Good to Excellent"
    assert gravado["fonte"] == "Farm Progress"
    assert gravado["publicado_em"] == "2026-08-18T10:00:00+00:00"
    assert gravado["categoria"] == "OFERTA/CLIMA"
    assert gravado["score"] == 7
    # resumo (análise do Haiku) x resumo_fonte (descrição crua do RSS) não podem
    # se misturar — ancorar o agente na paráfrase de outro LLM é a mesma doença
    # que este log existe para curar (achado A3, revisão 18/08/2026)
    assert gravado["resumo"] == "Condição boa/excelente cai para 61%."
    assert gravado["resumo_fonte"] == "Corn conditions dropped to 61% good/excellent, USDA says."
    # publisher real (do <source> do Google Notícias) e apelido do feed de busca
    # vão em campos separados — sem isso "fonte" seria "GN USDA/WASDE" (achados A2/A6)
    assert gravado["url_publisher"] == "https://www.farmprogress.com"
    assert gravado["feed"] == "GN USDA/WASDE"


@pytest.mark.unit
def test_check_news_nao_grava_no_log_quando_entrega_falha(monkeypatch):
    """Par de test_nao_queima_a_noticia_quando_a_entrega_falha (test_alert_checker.py),
    aplicado a log_sent_news: sem isto, mover a chamada para fora do `if sent > 0`
    passaria nos 267 testes e criaria registro de notícia que ninguém recebeu
    (achado A8)."""
    gravado, enviadas = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO, sent=0)

    total = alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert total == 0
    assert enviadas == []
    assert gravado == {}


@pytest.mark.unit
def test_check_news_manda_o_link_na_mensagem(monkeypatch):
    _, enviadas = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news([{"phone": "5534999945010", "name": "Matheus"}])

    assert len(enviadas) == 1
    assert "https://news.google.com/rss/articles/abc" in enviadas[0]


@pytest.mark.unit
def test_check_news_em_test_mode_nao_grava_no_log(monkeypatch):
    """test_mode existe para conferência visual sem sujar o estado — o log
    não pode virar a exceção que suja."""
    gravado, _ = _prepara_check_news(monkeypatch, _ARTIGO, _CLASSIFICACAO)

    alert_checker._check_news(
        [{"phone": "5534999945010", "name": "Matheus"}], test_mode=True
    )

    assert gravado == {}
