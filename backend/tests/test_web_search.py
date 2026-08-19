import pathlib
from unittest.mock import patch, MagicMock

import httpx
import pytest

from backend.services import web_search
from backend.services.secrets_mask import sanitize_error

# Chave FALSA de propósito — nunca a real, nem aqui nem em log de teste.
_CHAVE_FALSA = "chave-falsa-de-teste-SEGREDO123"


def _erro_com_chave_na_url() -> Exception:
    """Simula o formato real de httpx.HTTPStatusError: `raise_for_status()`
    monta a mensagem incluindo a URL completa da requisição — e a chave de
    API vai no query string dela."""
    request = httpx.Request(
        "GET", f"https://api.scraperapi.com/?api_key={_CHAVE_FALSA}&url=https://exemplo.com"
    )
    response = httpx.Response(500, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        return e
    raise AssertionError("raise_for_status deveria ter levantado")


@pytest.mark.unit
def test_sanitize_error_mascara_api_key():
    """A definição mora em backend.services.secrets_mask — achado 6, revisão
    18/08/2026 (4ª rodada): web_search.py mantinha um alias `_sanitize_error`
    só para este teste não precisar mudar. Duas grafias da mesma coisa no
    mesmo módulo; o teste agora aponta pra origem real."""
    erro = _erro_com_chave_na_url()
    saida = sanitize_error(erro)
    assert _CHAVE_FALSA not in saida
    assert "api_key=***" in saida


@pytest.mark.unit
def test_read_article_nao_vaza_chave_em_erro(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.services.web_search.httpx.get", side_effect=_erro_com_chave_na_url()):
        result = web_search.read_article("https://exemplo.com")
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]


@pytest.mark.unit
def test_search_nao_vaza_chave_em_erro(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", _CHAVE_FALSA)
    with patch("backend.services.web_search.httpx.get", side_effect=_erro_com_chave_na_url()):
        result = web_search.search("soja")
    assert _CHAVE_FALSA not in result["erro"]
    assert "api_key=***" in result["erro"]


@pytest.mark.unit
def test_read_article_sem_chave_nao_faz_requisicao(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    result = web_search.read_article("https://exemplo.com")
    assert result == {"erro": "SCRAPER_API_KEY não configurada"}


@pytest.mark.unit
def test_search_sem_chave_nao_faz_requisicao(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    result = web_search.search("soja")
    assert result == {"erro": "SCRAPER_API_KEY não configurada"}


def _resp_html(html: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = html
    return resp


@pytest.fixture
def sem_resolucao(monkeypatch):
    """Neutraliza a consulta ao Google (`resolve_google_news`) para exercitar o
    caminho de render — que é a rede de segurança de quando ela falha. Sem
    isto o teste abriria conexão de verdade e a trava de rede reprovaria (só
    de fato desde o Conserto 2, 19/08/2026: antes dele o erro morria dentro da
    thread e o teste passava verde pelo caminho degradado)."""
    monkeypatch.setattr(web_search, "resolve_google_news", lambda url, **k: "")


@pytest.mark.unit
def test_read_article_usa_render_para_link_do_google_noticias(monkeypatch, sem_resolucao):
    """Medido 18/08/2026: o fetch simples do ScraperAPI devolve 404 para link
    do Google Notícias em 6 de 6 casos reais — render=true resolve. Só pode
    ligar para esse domínio: custa 10x (header sa-credit-cost) e o tráfego
    geral desta tool (usada livremente pelo agente de chat) não pode pagar
    isso sempre."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://news.google.com/rss/articles/abc")
    assert mock_get.call_args.kwargs["params"]["render"] == "true"


@pytest.mark.unit
def test_read_article_nao_usa_render_para_link_normal(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://www.farmprogress.com/artigo")
    assert "render" not in mock_get.call_args.kwargs["params"]


@pytest.mark.unit
def test_read_article_timeout_customizavel(monkeypatch):
    """`alert_checker` precisa de um teto bem maior que os 30s default para
    dar tempo ao render=true (medido: até 49s por link real de GN)."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://www.farmprogress.com/artigo", timeout=75.0)
    assert mock_get.call_args.kwargs["timeout"].read == 75.0


@pytest.mark.unit
def test_read_article_timeout_default_preservado(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://www.farmprogress.com/artigo")
    assert mock_get.call_args.kwargs["timeout"].read == 30.0


@pytest.mark.unit
def test_read_article_render_eleva_piso_do_timeout(monkeypatch, sem_resolucao):
    """Achado 2, revisão do Apolo (18/08/2026): 4 renders reais mediram
    37,4-56,6s — todos acima do timeout default de 30s do caminho de chat.
    Sem piso, o chat paga os créditos do render e ainda volta com erro de
    timeout. `read_article` tem que elevar o timeout sozinho quando liga o
    render, mesmo que o chamador não passe nada."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://news.google.com/rss/articles/abc")
    assert mock_get.call_args.kwargs["timeout"].read == 75.0


@pytest.mark.unit
def test_read_article_render_respeita_timeout_maior_que_o_piso(monkeypatch, sem_resolucao):
    """O piso é um MÍNIMO, não um teto: alert_checker já passa 75s — não pode
    virar exatamente 75 se o chamador pedir mais."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://news.google.com/rss/articles/abc", timeout=120.0)
    assert mock_get.call_args.kwargs["timeout"].read == 120.0


@pytest.mark.unit
def test_is_google_news_link_compara_host_nao_substring(monkeypatch):
    """Achado 3, revisão do Apolo (18/08/2026): substring `"news.google.com"
    in url` casava um domínio hostil que só CONTÉM o texto na query string —
    ligando render=true (35 créditos, ~50s) para um link que não é do
    Google Notícias."""
    assert web_search._is_google_news_link("https://evil.com/?x=news.google.com") is False
    assert web_search._is_google_news_link("https://news.google.com/rss/articles/abc") is True
    assert web_search._is_google_news_link("") is False
    assert web_search._is_google_news_link(None) is False


@pytest.mark.unit
def test_read_article_nao_usa_render_para_dominio_hostil_parecido(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html("<p>artigo</p>")) as mock_get:
        web_search.read_article("https://evil.com/?x=news.google.com")
    assert "render" not in mock_get.call_args.kwargs["params"]
    assert mock_get.call_args.kwargs["timeout"].read == 30.0


def _fixture(nome: str) -> str:
    return (pathlib.Path(__file__).parent / "fixtures" / nome).read_text(encoding="utf-8")


@pytest.mark.unit
def test_read_article_extrai_corpo_e_descarta_entulho_do_site(monkeypatch):
    """Defeito 3 da validação em produção (18/08/2026): dos 4000 chars
    guardados de uma matéria real do EnergyNow, o começo era menu, o convite
    "Sign Up for FREE Daily Energy News" e MANCHETES DE OUTRAS NOTÍCIAS. Dois
    estragos: gasta o teto de 4000 com lixo (provavelmente cortando o miolo do
    artigo) e enfia assunto alheio dentro da âncora daquela notícia — o
    contrário do que o `conteudo` existe para fazer.

    `script/style/nav/footer/header/aside` não pega esse boilerplate: neste
    site (como na maioria) ele mora em `div` com classe."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html(_fixture("artigo_com_entulho.html"))):
        result = web_search.read_article("https://energynow.ca/artigo")
    texto = result["conteudo"]
    assert "3.8 million barrels" in texto
    assert "May 1" in texto and "ADNOC" in texto
    assert "Sign Up for FREE Daily Energy News" not in texto
    assert "Data Center Gas Plants" not in texto
    assert "Venezuela Oil Output" not in texto
    assert "Privacy Policy" not in texto


@pytest.mark.unit
def test_read_article_sem_corpo_reconhecivel_cai_no_texto_da_pagina(monkeypatch):
    """Página que o extrator não reconhece não pode virar conteúdo VAZIO: sem
    texto nenhum, `_capture_conteudo` grava None e o agente perde a âncora que
    ele tinha antes desta mudança. O caminho antigo (texto limpo da página)
    continua valendo como rede."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    pagina = ("<html><body><div>"
              + "Cotação do boi gordo fecha em alta na B3 nesta quarta. " * 6
              + "</div></body></html>")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html(pagina)):
        result = web_search.read_article("https://exemplo.com/boi")
    assert "boi gordo" in result["conteudo"]


@pytest.mark.unit
def test_read_article_devolve_url_canonica_do_publicador(monkeypatch):
    """Defeito 1 da validação em produção (18/08/2026): o 🔗 do alerta levava o
    link do Google Notícias, que o navegador recusa com 403. A página lida
    declara o endereço real da matéria (`<link rel=canonical>` / `og:url`) — a
    URL do feed pode ser a da capa da seção, não a da matéria."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html(_fixture("artigo_com_entulho.html"))):
        result = web_search.read_article("https://energynow.ca/?p=123")
    assert result["url_final"] == "https://energynow.ca/2026/08/uae-oil-production-nears-record/"
    # `url` é o endereço que ABRE (a canônica); o pedido fica em `url_origem`
    assert result["url"] == result["url_final"]
    assert result["url_origem"] == "https://energynow.ca/?p=123"


@pytest.mark.unit
def test_read_article_cai_no_og_url_quando_nao_ha_canonical(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    html = ('<html><head><meta property="og:url" content="https://valor.globo.com/materia">'
            '</head><body><article><p>' + "Texto real da matéria sobre soja. " * 20 +
            '</p></article></body></html>')
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html(html)):
        result = web_search.read_article("https://valor.globo.com/?id=9")
    assert result["url_final"] == "https://valor.globo.com/materia"


@pytest.mark.unit
@pytest.mark.parametrize("href", [
    "https://news.google.com/rss/articles/CBMiabc",   # o próprio 403 que queremos evitar
    "/2026/08/materia",                               # relativo: não serve de link no WhatsApp
    "javascript:alert(1)",                            # esquema que não é http(s)
    "https://phish.example/x",                        # canônica de OUTRO domínio
    "",
])
def test_read_article_recusa_url_canonica_imprestavel(monkeypatch, href):
    """`url_final` só existe para virar link clicável na mensagem. Canônica
    relativa, de esquema estranho, ou apontando de volta para o Google não
    resolve nada — melhor campo ausente (o chamador cai no link original) que
    campo errado.

    Domínio diferente do que foi lido também é recusado (achado do Apolo,
    19/08/2026): 6 dos 20 feeds são busca ABERTA do Google Notícias, então quem
    entrar no índice declararia a canônica que quisesse e escolheria o destino
    do link que o bot entrega sob "📰 Notícia Relevante". Sindicação legítima
    (medida: 2 em 27 artigos) perde o link e cai no original — degradação
    segura."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    html = (f'<html><head><link rel="canonical" href="{href}"></head>'
            '<body><article><p>' + "Texto real da matéria sobre soja. " * 20 +
            '</p></article></body></html>')
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html(html)):
        result = web_search.read_article("https://energynow.ca/?p=1")
    assert "url_final" not in result


# ── Link do Google Notícias resolvido sem ScraperAPI (19/08/2026) ──────────

_HTML_GN = ('<html><body><c-wiz><div data-n-a-sg="ASSINATURA" data-n-a-ts="1755600000" '
            'data-n-a-id="ARTIGO_ID">x</div></c-wiz></body></html>')


def _resp_batchexecute(url_publicador: str, escapa_barra: bool = False,
                       escapa_tudo: bool = False) -> MagicMock:
    """Formato real da resposta do batchexecute: JSON escapado dentro de texto.

    `escapa_barra=False` é o que o Google devolve HOJE (payload real capturado
    na 2ª revisão do Apolo, 19/08/2026). A forma com `\\/` já foi usada, e o `&`
    chega sempre como `\\u0026` — o parser precisa aguentar as três."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    corpo = url_publicador.replace("/", "\\/") if escapa_barra else url_publicador
    if escapa_tudo:
        # Como o serializador do Google escapa: tudo que não é ASCII imprimível
        # simples vira \uXXXX (o `&` sempre; `=` e acento quando aparecem).
        corpo = "".join(c if (c.isalnum() and c.isascii()) or c in "-._~:/?#[]@!$'()*+,;%"
                        else "\\u%04x" % ord(c) for c in corpo)
    else:
        corpo = corpo.replace("&", "\\u0026")
    resp.text = ')]}\'\n\n[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"' + corpo + '\\"]"]]'
    return resp


@pytest.mark.unit
def test_resolve_google_news_devolve_a_url_do_publicador(monkeypatch):
    """O Google responde o endereço real da matéria se a gente perguntar —
    medido 19/08/2026: 5 de 5 links reais, 0,4-0,8s, ZERO crédito de
    ScraperAPI. O caminho caro (render=true: 35 créditos, 37-57s, e 3 de 3
    HTTP 500 na tarde de 19/08) vira só a rede de segurança."""
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute("https://www.wisfarmer.com/story/x")
        url = web_search.resolve_google_news("https://news.google.com/rss/articles/CBMiabc")
    assert url == "https://www.wisfarmer.com/story/x"


@pytest.mark.unit
def test_resolve_google_news_ignora_link_que_nao_e_do_google(monkeypatch):
    """Não faz requisição nenhuma para link normal — não há o que resolver."""
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        url = web_search.resolve_google_news("https://www.farmprogress.com/x")
    assert url == ""
    MockClient.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("html", [
    "<html><body><p>página de consentimento</p></body></html>",   # IP de datacenter cai aqui
    '<html><body><c-wiz><div data-n-a-ts="1">x</div></c-wiz></body></html>',  # faltou assinatura
])
def test_resolve_google_news_sem_os_dados_devolve_vazio(html):
    """Endpoint interno do Google: pode mudar ou responder outra coisa sem
    aviso. Falhar tem que devolver "" e deixar o chamador seguir com o link
    original — o comportamento de antes de 19/08/2026, não uma quebra."""
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.return_value = _resp_html(html)
        assert web_search.resolve_google_news("https://news.google.com/rss/articles/abc") == ""


@pytest.mark.unit
def test_resolve_google_news_resposta_sem_url_devolve_vazio():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = ')]}\'\n\n[["wrb.fr","Fbv4je",null]]'
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = resp
        assert web_search.resolve_google_news("https://news.google.com/rss/articles/abc") == ""


@pytest.mark.unit
def test_resolve_google_news_excecao_nao_estoura():
    with patch("backend.services.web_search.httpx.Client", side_effect=RuntimeError("rede")):
        assert web_search.resolve_google_news("https://news.google.com/rss/articles/abc") == ""


@pytest.mark.unit
def test_read_article_resolve_o_link_do_google_antes_de_pagar_render(monkeypatch):
    """Com o endereço real na mão, a leitura dispensa o render: 1 crédito e
    ~6s em vez de 35 créditos e ~57s."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    monkeypatch.setattr(web_search, "resolve_google_news",
                        lambda url, **k: "https://www.wisfarmer.com/story/x")
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html(_fixture("artigo_com_entulho.html"))) as mock_get:
        result = web_search.read_article("https://news.google.com/rss/articles/abc")
    assert "render" not in mock_get.call_args.kwargs["params"]
    assert mock_get.call_args.kwargs["params"]["url"] == "https://www.wisfarmer.com/story/x"
    assert result["url_final"] == "https://www.wisfarmer.com/story/x"


@pytest.mark.unit
def test_read_article_sem_resolver_o_link_paga_o_render(monkeypatch):
    """Rede de segurança: resolução falhou (endpoint mudou, IP bloqueado) —
    o caminho caro continua existindo."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    monkeypatch.setattr(web_search, "resolve_google_news", lambda url, **k: "")
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html(_fixture("artigo_com_entulho.html"))) as mock_get:
        result = web_search.read_article("https://news.google.com/rss/articles/abc",
                                         url_publisher="https://energynow.ca")
    assert mock_get.call_args.kwargs["params"]["render"] == "true"
    # E a rede tem que ENTREGAR: sem esta linha o teste passava com `url_final`
    # ausente — exatamente o buraco do achado 1 da 2ª revisão, que ele exercitava
    # sem denunciar.
    assert result["url_final"] == "https://energynow.ca/2026/08/uae-oil-production-nears-record/"


# ── 2ª revisão do Apolo (19/08/2026): consertos dos achados 1, 4, 5, 6, 7 ──

@pytest.mark.unit
def test_url_canonica_vale_quando_bate_com_o_publicador(monkeypatch):
    """Achado 1: a canônica só é lida quando a resolução FALHOU — e aí a página
    pedida é a do Google enquanto a página lida é a do publicador. Conferir a
    canônica contra a URL pedida matava justamente o caso que ela existe para
    servir. O host bom vem do RSS (`<source url>`: 100 de 100 itens do feed
    trazem)."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    monkeypatch.setattr(web_search, "resolve_google_news",
                        lambda url, **k: "")
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html(_fixture("artigo_com_entulho.html"))):
        result = web_search.read_article("https://news.google.com/rss/articles/abc",
                                         url_publisher="https://energynow.ca")
    assert result["url_final"] == "https://energynow.ca/2026/08/uae-oil-production-nears-record/"


@pytest.mark.unit
def test_url_canonica_de_outro_dominio_continua_recusada(monkeypatch):
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    monkeypatch.setattr(web_search, "resolve_google_news",
                        lambda url, **k: "")
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html(_fixture("artigo_com_entulho.html"))):
        result = web_search.read_article("https://news.google.com/rss/articles/abc",
                                         url_publisher="https://outrojornal.com")
    assert "url_final" not in result


@pytest.mark.unit
def test_resolve_google_news_recusa_destino_de_outro_publicador():
    """Achado 4: nada conferia o endereço que o Google devolve. Se o endpoint
    interno mudar de formato ou responder outra coisa, o link ia direto para o
    WhatsApp sob '📰 Notícia Relevante' — e o dado que cruza está na mão."""
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute("https://outro-lugar.com/x")
        url = web_search.resolve_google_news("https://news.google.com/rss/articles/abc",
                                             host_esperado="https://www.wisfarmer.com")
    assert url == ""


@pytest.mark.unit
@pytest.mark.parametrize("escapa_barra", [True, False])
def test_resolve_google_news_nao_trunca_url_com_e_comercial(escapa_barra):
    r"""Achado 7: `[^"\]+` parava no primeiro `\`, e o Google escapa `&` como
    `\u0026`. O estrago é URL PLAUSÍVEL e errada — passa em `_url_exibivel` e
    vai para a mensagem e para o banco. O parâmetro cobre as duas formas: a
    resposta real de hoje NÃO escapa a barra, mas já escapou."""
    destino = "https://www.wisfarmer.com/story/x?id=99&utm_source=gn"
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute(destino, escapa_barra=escapa_barra)
        url = web_search.resolve_google_news("https://news.google.com/rss/articles/abc")
    assert url == destino


@pytest.mark.unit
def test_read_article_texto_curto_tenta_o_caminho_bruto_antes_de_desistir(monkeypatch):
    """Achado 5: nota curta extraída CERTO (2 frases) morria no piso de 200
    chars sem nunca tentar a rede de segurança, que passaria. Perder a âncora
    inteira num caso que tinha conserto é pior que guardar texto com um pouco
    de sobra do site."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    corpo = "Copom mantém a Selic em 15%. Decisão foi unânime e sem viés declarado."
    extra = "Assine a newsletter. Política de privacidade. Fale conosco. Últimas notícias. "
    html = f"<html><body><article><p>{corpo}</p></article><div>{extra * 3}</div></body></html>"
    # O extrator devolvendo SÓ o corpo (147 chars no caso real medido) é o
    # cenário do achado: curto, correto, e abaixo do piso.
    monkeypatch.setattr(web_search, "_extrai_corpo", lambda html: corpo)
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html(html)):
        result = web_search.read_article("https://valor.globo.com/x")
    assert corpo in result["conteudo"]
    assert result["extrator"] == "html_bruto"


@pytest.mark.unit
def test_read_article_pagina_do_google_nao_renderizada_continua_barrada(monkeypatch):
    """A rede de segurança não pode ressuscitar a âncora mentirosa: a página não
    renderizada do Google devolve "Google News" pelos DOIS caminhos."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    monkeypatch.setattr(web_search, "resolve_google_news",
                        lambda url, **k: "")
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html("<html><head><title>Google News</title></head>"
                                       "<body><c-wiz></c-wiz></body></html>")):
        result = web_search.read_article("https://news.google.com/rss/articles/abc")
    assert "conteudo" not in result
    assert "curto demais" in result["erro"]


@pytest.mark.unit
def test_read_article_devolve_ao_chat_o_endereco_que_abre(monkeypatch):
    """Achado 6: o agente de chat recebe o dicionário inteiro como tool_result e
    nada dizia qual URL citar — ele repetia o link que dá 403. `url` passa a ser
    o endereço bom; o original fica em `url_origem` para rastro."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    monkeypatch.setattr(web_search, "resolve_google_news",
                        lambda url, **k: "https://www.wisfarmer.com/story/x")
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html(_fixture("artigo_com_entulho.html"))):
        result = web_search.read_article("https://news.google.com/rss/articles/abc")
    assert result["url"] == "https://www.wisfarmer.com/story/x"
    assert result["url_origem"] == "https://news.google.com/rss/articles/abc"


@pytest.mark.unit
@pytest.mark.parametrize("destino", [
    "https://a.com/x?id=99&u=gn",          # "=" e "&" escapados juntos
    "https://a.com/cotação-do-boi",        # acento
])
def test_resolve_google_news_aguenta_qualquer_escape_unicode(destino):
    r"""3ª revisão do Apolo (19/08/2026): o conserto anterior perdoava só
    `&`. Qualquer outro `\uXXXX` (`=` do "=", acento) voltava a
    truncar a URL — e URL truncada é PLAUSÍVEL e errada: passa em
    `_url_exibivel`, vai para o WhatsApp e para o banco. Latente (28 destinos
    reais medidos, zero com escape), mas o estrago é dado errado entregue."""
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute(destino, escapa_tudo=True)
        assert web_search.resolve_google_news("https://news.google.com/rss/articles/abc") == destino


@pytest.mark.unit
@pytest.mark.parametrize("href", ["http://[bad", "http://a]b"])
def test_read_article_canonica_malformada_nao_apaga_a_materia(monkeypatch, href):
    """3ª revisão: `urlparse` levanta ValueError com colchete desbalanceado, e o
    `except` genérico transformava matéria BEM extraída em erro. Canônica é dado
    de terceiro — quebrada, recusa o link e mantém o texto."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")
    html = (f'<html><head><link rel="canonical" href="{href}"></head><body><article><p>'
            + "Texto real da matéria sobre soja e milho. " * 12 + "</p></article></body></html>")
    with patch("backend.services.web_search.httpx.get", return_value=_resp_html(html)):
        result = web_search.read_article("https://valor.globo.com/x")
    assert "soja e milho" in result["conteudo"]
    assert "url_final" not in result


@pytest.mark.unit
def test_resolve_google_news_tem_teto_absoluto_de_tempo():
    """3ª revisão, achado 2: o teto duro ficou no chamador do ALERTA, mas
    `read_article` (caminho do CHAT) chamava a resolução com timeout por
    OPERAÇÃO — a mesma doença, no lugar onde o usuário está esperando a
    resposta. O teto tem que morar aqui dentro, valendo para os dois."""
    import time as _t

    def get_lento(*a, **k):
        _t.sleep(5)
        return _resp_html(_HTML_GN)

    with patch("backend.services.web_search.httpx.Client") as MockClient:
        MockClient.return_value.__enter__.return_value.get.side_effect = get_lento
        t0 = _t.monotonic()
        url = web_search.resolve_google_news("https://news.google.com/rss/articles/abc",
                                             timeout=0.3)
        gasto = _t.monotonic() - t0
    assert url == ""
    assert gasto < 2.0


# ── Conserto 2 (19/08/2026): a thread cegava a trava de rede dos testes ────

@pytest.mark.unit
def test_resolve_google_news_propaga_erro_que_escapa_de_except_exception():
    """`backend/tests/_trava_rede.py` levanta `RedeProibida`, que herda de
    `BaseException` DE PROPÓSITO para escapar de `except Exception` (o mesmo
    motivo documentado lá: sinalizar com algo capturável pelo código de
    produção faria o teste passar verde com o caminho degradado). Antes deste
    conserto, a exceção morria DENTRO da thread e o invólucro devolvia "" — o
    teste abaixo teria passado verde mesmo tentando rede de verdade. Agora a
    thread reergue o que for BaseException-mas-não-Exception depois do
    `join`."""
    from backend.tests._trava_rede import RedeProibida
    with pytest.raises(RedeProibida):
        web_search.resolve_google_news("https://news.google.com/rss/articles/abc")


@pytest.mark.unit
def test_resolve_google_news_continua_engolindo_exception_normal():
    """Exceção normal (`Exception`) continua sendo tratada DENTRO de
    `_resolve_google_news`, como sempre — o conserto 2 só muda o que é
    `BaseException`-mas-não-`Exception`."""
    with patch("backend.services.web_search.httpx.Client", side_effect=RuntimeError("rede")):
        assert web_search.resolve_google_news("https://news.google.com/rss/articles/abc") == ""


# ── Conserto 3 (19/08/2026): prender a normalização do `www.` por teste ────

@pytest.mark.unit
def test_resolve_google_news_aceita_destino_com_www_quando_publicador_nao_tem():
    """`_host` tira o prefixo `www.` — é o que faz o cruzamento entre o destino
    resolvido e o `<source url>` do RSS (`host_esperado`) aceitar
    `wisfarmer.com` contra `www.wisfarmer.com`. Medido: tirar o
    `removeprefix` do código não quebra nenhum dos 439 testes existentes — e
    sem ele o destino legítimo é descartado e o 🔗 volta ao link que dá 403,
    calado."""
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute("https://www.wisfarmer.com/story/x")
        url = web_search.resolve_google_news(
            "https://news.google.com/rss/articles/abc",
            host_esperado="https://wisfarmer.com")
    assert url == "https://www.wisfarmer.com/story/x"


@pytest.mark.unit
def test_resolve_google_news_continua_recusando_dominio_diferente_com_www():
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute("https://www.outrositio.com/x")
        url = web_search.resolve_google_news(
            "https://news.google.com/rss/articles/abc",
            host_esperado="https://wisfarmer.com")
    assert url == ""


# ── Conserto 4 (19/08/2026): recusar destino com caractere sujo ────────────

@pytest.mark.unit
@pytest.mark.parametrize("sujo", [
    "https://www.wisfarmer.com/story/x y",     # espaço
    "https://www.wisfarmer.com/story/x\ny",    # quebra de linha
    'https://www.wisfarmer.com/story/x"y',     # aspas
    "https://www.wisfarmer.com/story/x<y",     # < (injeção de tag)
    "https://www.wisfarmer.com/story/x>y",     # >
])
def test_resolve_google_news_recusa_destino_com_caractere_sujo(sujo):
    """`_desescapa` decodifica qualquer `\\uXXXX` — inclusive espaço, quebra de
    linha, aspas e controles. `urlparse` ignora esses caracteres, então
    `_mesmo_host` devolveria True e a URL suja chegaria à mensagem do WhatsApp
    e ao banco: uma quebra de linha no meio vira duas linhas e o WhatsApp
    auto-linka a segunda."""
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute(sujo, escapa_tudo=True)
        url = web_search.resolve_google_news("https://news.google.com/rss/articles/abc")
    assert url == ""


@pytest.mark.unit
def test_resolve_google_news_destino_limpo_continua_aceito():
    """Contrapeso do conserto 4: não pode ficar recusando URL válida à toa."""
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute("https://www.wisfarmer.com/story/x?id=1")
        url = web_search.resolve_google_news("https://news.google.com/rss/articles/abc")
    assert url == "https://www.wisfarmer.com/story/x?id=1"


@pytest.mark.unit
def test_read_article_sobrevive_a_thread_recusada(monkeypatch):
    """5ª revisão do Apolo: `alvo = resolve_google_news(...)` ficou FORA do try
    de `read_article`, e `Thread.start()` levanta `RuntimeError` quando o SO
    recusa a thread. O loop de tools do reporter não tem try local — a exceção
    subiria até lá em vez de virar `{"erro": ...}`."""
    monkeypatch.setenv("SCRAPER_API_KEY", "chave-de-teste")

    def recusa(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(web_search.threading.Thread, "start", recusa)
    with patch("backend.services.web_search.httpx.get",
               return_value=_resp_html(_fixture("artigo_com_entulho.html"))):
        result = web_search.read_article("https://news.google.com/rss/articles/abc")
    assert "erro" in result


@pytest.mark.unit
def test_resolve_google_news_aceita_apostrofo_no_endereco():
    """Apóstrofo é sub-delim LEGAL em URL (RFC 3986) — recusar custa o 🔗 (403)
    e 35 créditos de render. Os outros caracteres da classe (espaço, controle,
    aspas duplas, `<`, `>`) não aparecem em URL legítima; este aparece."""
    destino = "https://www.wisfarmer.com/story/o'brien-farm"
    with patch("backend.services.web_search.httpx.Client") as MockClient:
        client = MockClient.return_value.__enter__.return_value
        client.get.return_value = _resp_html(_HTML_GN)
        client.post.return_value = _resp_batchexecute(destino)
        assert web_search.resolve_google_news("https://news.google.com/rss/articles/abc") == destino
