"""Lote 2 da review de 09/09: casos em que o sistema falha e reporta sucesso.

Arquivo sem nenhuma chamada de rede: tudo via mock/MockTransport. O marcador
coloca o arquivo no portao do CI, que roda `pytest backend -m unit`.
"""
import json
import os
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.collectors import market, news
from backend.services import alert_checker, supabase

pytestmark = pytest.mark.unit

client = TestClient(app)
_SECRET = "test-cron-secret"
_ClientReal = httpx.Client  # guardado antes dos monkeypatch de httpx.Client


# -- 1. Cron contava envio mesmo sem gerar nenhuma secao ---------------------

@pytest.mark.unit
def test_cron_report_zero_secoes_geradas_conta_como_falha():
    """generate_sections engole falha por secao e pode devolver []. O laco de
    envio nao roda, mas sent += 1 rodava: manha sem relatorio virava sucesso."""
    rows = [{"phone": "5534999945010", "section": "bolsas"}]
    with patch("backend.api.cron_report.schedules.due_now", return_value=rows), \
         patch("backend.api.cron_report.schedules.phones_with_engine_enabled",
               return_value={"5534999945010"}), \
         patch("backend.api.cron_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "M"}), \
         patch("backend.api.cron_report.report_engine.generate_sections", return_value=[]), \
         patch("backend.api.cron_report.whatsapp.send_message") as send, \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    body = r.json()
    assert send.call_count == 0
    assert body["sent"] == 0
    assert body["failed"] == 1


@pytest.mark.unit
def test_cron_report_relata_secoes_pedidas_e_geradas():
    rows = [{"phone": "555", "section": "bolsas"}, {"phone": "555", "section": "analise"}]
    with patch("backend.api.cron_report.schedules.due_now", return_value=rows), \
         patch("backend.api.cron_report.schedules.phones_with_engine_enabled", return_value={"555"}), \
         patch("backend.api.cron_report.supabase.get_authorized_by_phone",
               return_value={"phone": "555", "name": "M"}), \
         patch("backend.api.cron_report.report_engine.generate_sections", return_value=["so uma"]), \
         patch("backend.api.cron_report.whatsapp.send_message"), \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        body = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET}).json()
    assert body["sections_requested"] == 2
    assert body["sections_generated"] == 1


@pytest.mark.unit
def test_cron_report_loga_aviso_quando_a_falha_e_parcial(caplog):
    """Numero no corpo do JSON da invocacao nao chega a ninguem. Falha parcial
    precisa aparecer no log, que e o que o boletim de saude le."""
    rows = [{"phone": "555", "section": "bolsas"}, {"phone": "555", "section": "analise"}]
    with (
        patch("backend.api.cron_report.schedules.due_now", return_value=rows),
        patch("backend.api.cron_report.schedules.phones_with_engine_enabled", return_value={"555"}),
        patch("backend.api.cron_report.supabase.get_authorized_by_phone",
              return_value={"phone": "555", "name": "M"}),
        patch("backend.api.cron_report.report_engine.generate_sections", return_value=["so uma"]),
        patch("backend.api.cron_report.whatsapp.send_message"),
        patch.dict(os.environ, {"CRON_SECRET": _SECRET}),
        caplog.at_level("WARNING", logger="noticiasgg"),
    ):
        client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    assert any("parcial" in r.message.lower() or "1/2" in r.getMessage()
               for r in caplog.records)


# -- 2. EIA marcava divulgacao como enviada mesmo com zero entregas ----------

_EIA_DATA = {"Petroleo bruto": {"valor": 420000.0, "data": "2026-09-03",
                                "unidade": "mil barris", "variacao_pct": -1.2}}


@pytest.mark.unit
def test_eia_com_zero_entregas_nao_marca_como_enviado():
    """A janela de bloqueio e de 30 dias: marcar sem entregar perde a
    divulgacao da semana inteira. Preco e Copom ja so marcam com sent > 0."""
    with patch.object(alert_checker.eia, "collect", return_value=_EIA_DATA), \
         patch.object(alert_checker, "_cooldown_ok", return_value=True), \
         patch.object(alert_checker, "_broadcast", return_value=0), \
         patch.object(alert_checker.supabase, "set_alert_triggered") as marca:
        enviados = alert_checker._check_eia([{"phone": "555"}], [])
    assert enviados == 0
    assert marca.call_count == 0


@pytest.mark.unit
def test_eia_com_entrega_marca_normalmente():
    with patch.object(alert_checker.eia, "collect", return_value=_EIA_DATA), \
         patch.object(alert_checker, "_cooldown_ok", return_value=True), \
         patch.object(alert_checker, "_broadcast", return_value=1), \
         patch.object(alert_checker.supabase, "set_alert_triggered") as marca:
        enviados = alert_checker._check_eia([{"phone": "555"}], [])
    assert enviados == 1
    assert marca.call_count == 1


# -- 3. Falha da NewsAPI derrubava os RSS gratis -----------------------------

def _rss_fresco() -> bytes:
    """Data relativa ao relogio, nunca cravada: news._MAX_AGE e de 48h, entao
    fixture com data fixa faz o portao do CI ficar vermelho dois dias depois
    por motivo falso. Mesmo padrao de _fresh_rss em test_news.py."""
    quando = format_datetime(datetime.now(timezone.utc) - timedelta(hours=1))
    return (
        '<?xml version="1.0"?><rss><channel>'
        '<item><title>Feed vivo</title><link>https://exemplo.com/a</link>'
        f"<pubDate>{quando}</pubDate><description>ok</description></item>"
        "</channel></rss>"
    ).encode("utf-8")


_RSS_XML = _rss_fresco()


def _transporte_falso(newsapi_erro):
    def handler(request):
        if "newsapi.org" in str(request.url):
            if newsapi_erro:
                raise newsapi_erro
            return httpx.Response(200, json={"articles": []})
        return httpx.Response(200, content=_RSS_XML)
    return httpx.MockTransport(handler)


def _fixar_cliente(monkeypatch, erro):
    transporte = _transporte_falso(erro)
    monkeypatch.setattr(
        news.httpx, "Client",
        lambda **kw: _ClientReal(transport=transporte, timeout=5),
    )


@pytest.mark.unit
def test_timeout_da_newsapi_nao_derruba_os_rss(monkeypatch):
    """Fornecedor pago fora do ar nao pode levar junto os feeds gratis."""
    monkeypatch.setenv("NEWS_API_KEY", "chave-falsa")
    _fixar_cliente(monkeypatch, httpx.ConnectTimeout("estourou"))
    erros = []
    artigos = news.collect(include_ai=False, errors=erros)
    assert len(artigos) > 0
    assert any("newsapi" in e.lower() for e in erros)


@pytest.mark.unit
def test_sem_chave_mas_sem_usar_newsapi_nao_levanta(monkeypatch):
    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    _fixar_cliente(monkeypatch, None)
    artigos = news.collect(include_ai=False, include_newsapi=False)
    assert len(artigos) > 0


# -- 4. Timeout agregado do fallback descartava o que ja tinha chegado -------

@pytest.mark.unit
def test_timeout_agregado_aproveita_cotacao_que_ja_chegou():
    """O bloco `with ThreadPoolExecutor` espera os futures na saida, entao
    quando o prazo agregado estoura eles JA terminaram. Descartar esse
    resultado jogava fora cotacao ja paga e ja entregue."""
    faltando = {"^BVSP": ("bolsas", "IBOVESPA"), "^N225": ("bolsas", "JPX (Nikkei 225)")}
    with (
        patch.object(market, "as_completed", side_effect=FuturesTimeout("agregado")),
        patch.object(market, "_fetch_via_scraperapi", return_value={"preco": 1.0}),
    ):
        out = market._fetch_all_scraperapi(faltando)
    assert set(out.keys()) == {("bolsas", "IBOVESPA"), ("bolsas", "JPX (Nikkei 225)")}
    for dado in out.values():
        assert dado["preco"] == 1.0


@pytest.mark.unit
def test_excecao_no_future_vira_erro_sem_derrubar_os_outros():
    """Defesa em profundidade: hoje _fetch_via_scraperapi tem try/except
    proprio e nunca levanta, entao este ramo so protege contra o dia em que
    alguem tirar aquele except."""
    faltando = {"^BVSP": ("bolsas", "IBOVESPA"), "^N225": ("bolsas", "JPX (Nikkei 225)")}

    def por_simbolo(sym):
        if sym == "^N225":
            raise RuntimeError("fornecedor caiu")
        return {"preco": 1.0}

    with (
        patch.object(market, "as_completed", side_effect=FuturesTimeout("agregado")),
        patch.object(market, "_fetch_via_scraperapi", side_effect=por_simbolo),
    ):
        out = market._fetch_all_scraperapi(faltando)
    assert out[("bolsas", "IBOVESPA")]["preco"] == 1.0
    assert out[("bolsas", "JPX (Nikkei 225)")]["preco"] is None
    assert out[("bolsas", "JPX (Nikkei 225)")]["erro"]


@pytest.mark.unit
def test_collect_preserva_cotacoes_diretas_quando_fallback_estoura():
    direto = {"^GSPC": {"preco": 7600.0, "variacao_pct": 0.5}}
    with patch.object(market, "_fetch_all_direct", return_value=direto), \
         patch.object(market, "as_completed", side_effect=FuturesTimeout("agregado")), \
         patch.object(market, "_fetch_via_scraperapi", return_value={"preco": 1.0}):
        out = market.collect()
    assert out["bolsas"]["S&P 500"]["preco"] == 7600.0


# -- 6. Mudar a voz apagava secoes e horario ---------------------------------

def _capturar_upsert(monkeypatch) -> dict:
    capturado = {}

    def handler(request):
        capturado.update(json.loads(request.content))
        return httpx.Response(201, json=[])

    monkeypatch.setattr(
        supabase, "_client",
        lambda: _ClientReal(base_url="http://fake/rest/v1",
                            transport=httpx.MockTransport(handler)),
    )
    return capturado


@pytest.mark.unit
def test_salvar_so_a_voz_nao_manda_secoes_nem_horario_nulos(monkeypatch):
    """O comando de voz produz sections=None e report_time=None; envia-los no
    upsert apagava o que o usuario tinha configurado no painel."""
    capturado = _capturar_upsert(monkeypatch)
    supabase.save_preferences("555", sections=None, report_time=None, tts_voice="onyx")
    assert capturado["tts_voice"] == "onyx"
    assert "sections" not in capturado
    assert "report_time" not in capturado


@pytest.mark.unit
def test_painel_ainda_consegue_gravar_secoes_e_horario(monkeypatch):
    capturado = _capturar_upsert(monkeypatch)
    supabase.save_preferences("555", sections={"market": True}, report_time="08:00")
    assert capturado["sections"] == {"market": True}
    assert capturado["report_time"] == "08:00"


@pytest.mark.unit
def test_secoes_vazias_do_painel_continuam_gravando(monkeypatch):
    """Desmarcar tudo no painel manda {} - que nao e None e precisa gravar."""
    capturado = _capturar_upsert(monkeypatch)
    supabase.save_preferences("555", sections={}, report_time=None)
    assert capturado["sections"] == {}


# -- Achados da revisao do Apolo sobre este proprio lote ---------------------

def _tudo_falha(erro_newsapi=None, status_newsapi=None, primeira_ok=False):
    """Handler em que os RSS tambem morrem: articles fica [] e _check_news
    volta cedo, sem chamar o classificador. Com primeira_ok, a 1a chamada a
    NewsAPI responde e as seguintes estouram (caso misto)."""
    chamadas = {"n": 0}

    def handler(request):
        if "newsapi.org" in str(request.url):
            chamadas["n"] += 1
            if primeira_ok and chamadas["n"] == 1:
                return httpx.Response(200, json={"articles": []})
            if erro_newsapi:
                raise erro_newsapi
            return httpx.Response(status_newsapi or 200, json={"articles": []})
        raise httpx.ConnectTimeout("rss fora")
    return httpx.MockTransport(handler)


def _rodar_check_news(monkeypatch, transporte):
    monkeypatch.setenv("NEWS_API_KEY", "chave-falsa")
    monkeypatch.setattr(news.httpx, "Client",
                        lambda **kw: _ClientReal(transport=transporte, timeout=5))
    erros = []
    with (
        patch.object(alert_checker, "_cooldown_ok", return_value=True),
        patch.object(alert_checker.supabase, "set_alert_triggered") as marca,
        # Contrato explicito, nao consequencia: se algum dia articles deixar de
        # ficar vazio, o teste falha aqui em vez de chamar o Claude de verdade.
        patch.object(alert_checker, "Anthropic",
                     side_effect=AssertionError("classificador nao pode ser chamado")),
    ):
        alert_checker._check_news([{"phone": "555"}], test_mode=False, errors=erros)
    return [c.args[0] for c in marca.call_args_list], erros


@pytest.mark.unit
def test_contrato_real_sem_resposta_da_newsapi_nao_queima_a_janela(monkeypatch):
    """Roda o produtor (news.collect) e o consumidor (_check_news) de verdade.
    Se a mensagem de erro mudar de forma so num lado, o cooldown quebraria em
    silencio: este teste ancora o contrato nos dois."""
    marcados, erros = _rodar_check_news(
        monkeypatch, _tudo_falha(erro_newsapi=httpx.ConnectTimeout("estourou")))
    assert "newsapi_fetch" not in marcados
    assert erros


@pytest.mark.unit
def test_contrato_real_http_429_freia_o_fornecedor(monkeypatch):
    """429/401 sao o fornecedor RESPONDENDO: a cota foi gasta e a janela de
    45 min tem que valer, senao a tentativa sobe de 1x para 4x por hora."""
    marcados, _ = _rodar_check_news(monkeypatch, _tudo_falha(status_newsapi=429))
    assert "newsapi_fetch" in marcados


@pytest.mark.unit
def test_contrato_real_falha_parcial_ainda_freia_o_fornecedor(monkeypatch):
    """Duas chamadas por coleta. Se a primeira responde (cota gasta) e a
    segunda cai, o freio tem que valer: dispensar por causa de UMA falha fazia
    o ciclo de 15 min bater de novo com a cota ja consumida."""
    marcados, _ = _rodar_check_news(
        monkeypatch,
        _tudo_falha(erro_newsapi=httpx.ConnectTimeout("estourou"), primeira_ok=True))
    assert "newsapi_fetch" in marcados


@pytest.mark.unit
def test_payload_da_newsapi_com_forma_inesperada_nao_derruba_os_rss(monkeypatch):
    """200 com lista no lugar de objeto, ou articles nulo, tambem matava o
    collect() inteiro - mesma falha do corpo ilegivel, uma camada abaixo."""
    monkeypatch.setenv("NEWS_API_KEY", "chave-falsa")
    for corpo in (b'["a","b"]', b'{"articles": null}', b'{"articles": ["oi"]}'):
        def handler(request, _c=corpo):
            if "newsapi.org" in str(request.url):
                return httpx.Response(200, content=_c)
            return httpx.Response(200, content=_RSS_XML)
        monkeypatch.setattr(news.httpx, "Client",
                            lambda **kw: _ClientReal(transport=httpx.MockTransport(handler),
                                                     timeout=5))
        artigos = news.collect(include_ai=False, errors=[])
        assert len(artigos) > 0, corpo


@pytest.mark.unit
def test_corpo_malformado_da_newsapi_nao_derruba_os_rss(monkeypatch):
    """200 com JSON quebrado levanta JSONDecodeError, que nao e httpx.HTTPError."""
    monkeypatch.setenv("NEWS_API_KEY", "chave-falsa")

    def handler(request):
        if "newsapi.org" in str(request.url):
            return httpx.Response(200, content=b"nao sou json")
        return httpx.Response(200, content=_RSS_XML)

    transporte = httpx.MockTransport(handler)
    monkeypatch.setattr(news.httpx, "Client",
                        lambda **kw: _ClientReal(transport=transporte, timeout=5))
    erros = []
    artigos = news.collect(include_ai=False, errors=erros)
    assert len(artigos) > 0
    assert any("newsapi" in e.lower() for e in erros)
