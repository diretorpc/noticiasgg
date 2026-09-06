import json
import logging
import os
import re
import threading
from datetime import date

import httpx
import trafilatura
from bs4 import BeautifulSoup
from trafilatura.metadata import extract_metadata
from urllib.parse import urlparse

from backend.services.secrets_mask import sanitize_error

logger = logging.getLogger("noticiasgg.web_search")

SCRAPER_API_URL = "https://api.scraperapi.com/structured/google/search"
SCRAPER_FETCH_URL = "https://api.scraperapi.com/"

_MAX_ARTICLE_CHARS = 4000

# Piso do que conta como matéria lida. A página NÃO renderizada do Google
# Notícias devolve exatamente "Google News" (11 chars) pelo caminho bruto, e
# isso ia para o banco como se fosse o texto da matéria — o modelo então recebe
# um "conteúdo" vazio de fatos em vez do aviso "não capturado, não invente"
# (achado do Apolo, 19/08/2026). 200 chars ≈ 35 palavras: abaixo disso não dá
# para ancorar afirmação nenhuma, então ausência honesta é melhor.
_MIN_ARTICLE_CHARS = 200

# Piso de timeout quando render=true está ligado (ver read_article). Medido
# 18/08/2026 (revisão do Apolo, achado 2): 4 chamadas reais com render deram
# 37,4 / 38,5 / 52,3 / 56,6s — as 4 acima de 30s, o default do chamador. Sem
# piso, o caminho de chat (timeout default 30s) paga os créditos do render e
# ainda assim volta com {"erro": "timeout ao buscar artigo"} — pior dos dois
# mundos. 75.0 é o mesmo valor de `alert_checker._CONTEUDO_TIMEOUT`.
_RENDER_TIMEOUT_FLOOR = 75.0


def _is_google_news_link(url: str) -> bool:
    """Compara o HOST da URL, não substring (achado 3, revisão do Apolo,
    18/08/2026: `"news.google.com" in url` casava `https://evil.com/?x=news.google.com`,
    ligando render=true — 35 créditos e ~50s desperdiçados — para um link que
    não é do Google Notícias)."""
    if not url:
        return False
    host = _host(url)
    return host == "news.google.com" or host.endswith(".news.google.com")


def _host(url: str) -> str:
    """Host em minúsculas, sem `www.` — "" quando não dá para ler.

    `urlparse` LEVANTA ValueError com colchete desbalanceado no authority
    (`http://[bad`, `http://a]b`) — e isso aqui recebe dado de terceiro. Sem o
    try, uma canônica quebrada derrubava a leitura inteira e transformava
    matéria BEM extraída em erro (achado 4 da 3ª revisão do Apolo, 19/08/2026).
    """
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _mesmo_host(a: str, b: str) -> bool:
    """`www.` não distingue site — o resto sim."""
    ha = _host(a)
    return bool(ha) and ha == _host(b)


def _url_canonica(html: str, url_lida: str, url_publisher: str = "") -> str:
    """Endereço REAL do artigo, declarado pela própria página lida.

    Defeito 1 da primeira validação em produção (18/08/2026): o 🔗 do alerta
    levava o link do Google Notícias (`news.google.com/rss/articles/CBMi...`),
    que o navegador recusa com 403. Com render=true o ScraperAPI já entrega a
    página do PUBLICADOR — o endereço bom está nela e era só não jogar fora.
    `url_publisher` do RSS não serve: é o domínio (`https://energynow.ca`),
    não a matéria.

    Devolve "" para canônica que não vira link clicável no WhatsApp (relativa,
    esquema fora de http(s), ou apontando de volta para o Google): campo
    ausente faz o chamador manter o link original — errado seria pior.

    E devolve "" para canônica de host que não é nem o da página lida nem o do
    publicador do feed (achado do Apolo, 19/08/2026). Isto aqui é declaração de
    TERCEIRO, e 6 dos 20 feeds são busca ABERTA do Google Notícias: sem a
    conferência, quem entrasse no índice escolheria o destino do link que o bot
    entrega sob "📰 Notícia Relevante". Sindicação legítima (2 em 27 artigos
    reais) perde o link e cai no original — degradação segura.

    Os DOIS hosts precisam valer porque esta função só é chamada quando a
    resolução falhou: aí `url_lida` é o link do Google e a página lida é a do
    publicador — conferir só contra `url_lida` recusaria 100% dos casos, que é
    exatamente o buraco achado na 2ª revisão (achado 1). `url_publisher` vem do
    `<source url>` do RSS, presente em 100 de 100 itens medidos.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return ""
    candidatos = []
    link = soup.find("link", rel="canonical")
    if link:
        candidatos.append(link.get("href") or "")
    og = soup.find("meta", property="og:url")
    if og:
        candidatos.append(og.get("content") or "")
    for url in candidatos:
        url = (url or "").strip()
        if (url.startswith(("http://", "https://"))
                and not _is_google_news_link(url)
                and (_mesmo_host(url, url_lida) or _mesmo_host(url, url_publisher))):
            return url
    return ""


# Endpoint interno do Google Notícias que devolve o endereço do publicador para
# um link `news.google.com/rss/articles/CBMi...`. Medido 19/08/2026 em 5 links
# reais da coleta: 5 de 5, 0,4-0,8s, ZERO crédito de ScraperAPI — contra 35
# créditos e 37-57s do render (que na tarde do mesmo dia devolveu HTTP 500 em 3
# de 3 tentativas). Não é API documentada: pode mudar sem aviso, e o IP de
# datacenter da Vercel pode receber página de consentimento em vez do artigo.
# Por isso toda falha devolve "" e o chamador segue com o link original — o
# comportamento de antes desta função, nunca uma quebra.
_GN_BATCHEXECUTE = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_GN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Prazo ABSOLUTO da resolução (ver resolve_google_news). Vale para os dois
# caminhos: o alerta, onde estourar significaria atrasar o envio, e o chat, onde
# o usuário está esperando a resposta. A cauda é mais gorda do que a primeira
# medição sugeria — 40 links reais na 5ª revisão do Apolo (19/08/2026) deram
# mediana 0,98s, p90 1,53s e UM estouro com o teto em 3,0s. Cada estouro custa
# o 🔗 com 403 e 35 créditos de render na captura, que perde o link resolvido.
# Medir de novo antes de mexer:
#   python -c "from backend.collectors import news; from backend.services import web_search as w; import time; [print(round(time.monotonic()-t0,2)) for a in news.collect(include_ai=False, include_newsapi=False)[:20] if 'news.google.com' in (a.get('url') or '') and (t0:=time.monotonic()) and w.resolve_google_news(a['url'])]"
_GN_PRAZO = 5.0


def _desescapa(texto: str) -> str:
    """Desfaz o escape do JSON aninhado da resposta do Google.

    `\\/` vira `/` e `\\u0026` vira `&`. O segundo é o que importa de verdade:
    sem ele, um endereço com query string chegava TRUNCADO no primeiro `&` —
    URL plausível e errada, que passa em toda validação e vai para a mensagem e
    para o banco (achado 7 da 2ª revisão do Apolo, 19/08/2026; latente: 0 de 18
    destinos reais medidos tinham query string).
    """
    return re.sub(r"\\u([0-9a-fA-F]{4})",
                  lambda m: chr(int(m.group(1), 16)),
                  texto.replace("\\/", "/"))


# `_desescapa` decodifica QUALQUER `\uXXXX` — inclusive espaço, quebra de
# linha, aspas e outros controles. `urlparse` ignora esses caracteres em vez
# de rejeitar a URL, então `_mesmo_host` devolvia True e o destino sujo
# chegava à mensagem do WhatsApp e ao banco: uma quebra de linha no meio vira
# DUAS linhas e o WhatsApp auto-linka a segunda (achado da 4ª revisão do
# Apolo, 19/08/2026). `\s` cobre espaço/tab/quebra de linha; `\x00-\x1f\x7f`
# cobre os demais controles; aspas DUPLAS e `<`/`>` fecham a defesa contra o
# destino virar texto solto ou tag dentro da mensagem. Apóstrofo NÃO entra: é
# sub-delim legal na RFC 3986, e recusar por causa dele custaria o 🔗 (403) e
# 35 créditos de render num endereço perfeitamente válido.
_CARACTERE_SUJO = re.compile(r"[\s\x00-\x1f\x7f\"<>]")


def resolve_google_news(url: str, timeout: float = _GN_PRAZO, host_esperado: str = "") -> str:
    """Endereço real da matéria por trás de um link do Google Notícias.

    O link do RSS é uma página de redirecionamento em JS: no navegador ela
    resolve, mas colada no WhatsApp devolve 403 (defeito 1 da validação em
    produção, 18/08/2026). A própria página carrega os três dados que o Google
    exige para informar o destino (assinatura, timestamp e id do artigo) — é
    isso que esta função lê e devolve ao Google no `batchexecute`.

    `host_esperado` (o `<source url>` do RSS, presente em 100 de 100 itens
    medidos) confere o destino: endpoint interno pode mudar de formato ou
    responder outra coisa, e sem o cruzamento esse endereço iria direto para o
    WhatsApp sob "📰 Notícia Relevante" (achado 4 da 2ª revisão do Apolo).

    `timeout` aqui é prazo ABSOLUTO, não por operação — a thread com `join` é o
    único jeito de garantir isso (achado 2 da 3ª revisão: o teto duro tinha
    ficado só no chamador do alerta, e o caminho do CHAT, que também passa por
    aqui via `read_article`, continuava com o relógio do httpx reiniciando a
    cada pedaço da resposta). A thread é daemon e recebe o mesmo prazo como
    timeout do httpx, então morre junto em vez de acumular.

    Devolve "" para link que não é do Google Notícias (não há o que resolver) e
    para qualquer falha, inclusive estouro de prazo.
    """
    if not _is_google_news_link(url):
        return ""
    caixa: list[str] = []
    erro: list[BaseException] = []

    def _alvo() -> None:
        try:
            caixa.append(_resolve_google_news(url, timeout, host_esperado))
        except Exception:
            # Não deveria acontecer: `_resolve_google_news` já filtra toda
            # `Exception` internamente. Se acontecer mesmo assim, segue o
            # comportamento de sempre — não reergue no invólucro (só o que é
            # BaseException-mas-não-Exception reergue, ver abaixo).
            raise
        except BaseException as e:
            # A trava de rede dos testes (`RedeProibida`, em
            # backend/tests/_trava_rede.py) herda de BaseException DE PROPÓSITO
            # para escapar de `except Exception` — antes deste conserto ela
            # morria AQUI dentro (thread sem `except`) e o invólucro devolvia
            # "", fazendo um teste que deveria reprovar por tentar rede real
            # passar verde pelo caminho degradado (19/08/2026).
            erro.append(e)

    t = threading.Thread(target=_alvo, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        logger.warning("resolve_google_news estourou o prazo de %.1fs", timeout)
        return ""
    if erro:
        raise erro[0]
    return caixa[0] if caixa else ""


def _resolve_google_news(url: str, timeout: float, host_esperado: str) -> str:
    """O trabalho de verdade. Separado só para `resolve_google_news` poder
    impor o prazo absoluto por fora — e para toda exceção morrer aqui dentro,
    sem despejar traceback pelo `threading.excepthook`."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _GN_UA})
            resp.raise_for_status()
            div = BeautifulSoup(resp.text, "html.parser").select_one("c-wiz > div")
            if div is None:
                return ""
            assinatura = div.get("data-n-a-sg")
            carimbo = div.get("data-n-a-ts")
            artigo_id = div.get("data-n-a-id")
            if not (assinatura and carimbo and artigo_id):
                return ""
            pedido = ["Fbv4je", json.dumps([
                "garturlreq",
                [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                  None, None, None, None, None, 0, 1],
                 "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                artigo_id, int(carimbo), assinatura])]
            resp2 = client.post(
                _GN_BATCHEXECUTE,
                data={"f.req": json.dumps([[pedido]])},
                headers={"User-Agent": _GN_UA,
                         "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            )
            resp2.raise_for_status()
            # A resposta é JSON DENTRO de string JSON: a barra do endereço chega
            # ora crua (`https://x` — o formato de hoje), ora escapada
            # (`https:\/\/x`), e `&`/`=`/acento vêm como `\uXXXX`. A classe aceita as
            # três formas e para no `"` que fecha a string; `_desescapa` desfaz.
            achado = re.search(r'garturlres.{0,10}(https?:(?:\\u[0-9a-fA-F]{4}|\\/|[^"\\])+)',
                               resp2.text)
            if not achado:
                return ""
            destino = _desescapa(achado.group(1))
    except Exception as e:
        logger.warning("resolve_google_news falhou: %s", sanitize_error(e))
        return ""
    if not destino.startswith(("http://", "https://")) or _is_google_news_link(destino):
        return ""
    if _CARACTERE_SUJO.search(destino):
        logger.warning("resolve_google_news: destino com caractere sujo, descartado")
        return ""
    if host_esperado and not _mesmo_host(destino, host_esperado):
        logger.warning("resolve_google_news: destino fora do publicador esperado, descartado")
        return ""
    return destino


def _extrai_corpo(html: str) -> str:
    """Só o CORPO da matéria, sem o resto do site.

    Existe por causa do defeito 3 da primeira validação em produção
    (18/08/2026): a limpeza por TAG (`script/style/nav/footer/header/aside`)
    não pega boilerplate que mora em `div` com classe — e a matéria real do
    EnergyNow chegou ao banco com menu, "Sign Up for FREE Daily Energy News" e
    manchetes de OUTRAS notícias ocupando o começo dos 4000 chars: assunto
    alheio dentro da âncora daquela notícia, que é o contrário do que o
    `conteudo` existe para fazer.

    `trafilatura` em vez de heurística caseira de densidade: o alvo é o
    conjunto ABERTO de layouts que os 20 feeds trazem, e heurística própria
    erra CALADA em site que ninguém testou. Devolve "" quando não reconhece
    corpo nenhum — quem chama decide o que fazer com isso.
    """
    try:
        texto = trafilatura.extract(html, include_comments=False, include_tables=True)
    except Exception:
        return ""
    return (texto or "").strip()


def _texto_da_pagina(html: str) -> str:
    """Texto da página inteira, sem as tags de estrutura. Caminho anterior a
    19/08/2026 — hoje é a rede de segurança de `_extrai_corpo`."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()


# Incidente de 05/09/2026: o Google Notícias carimba o RSS com a hora da
# REINDEXAÇÃO, não da publicação — uma nota do WASDE de maio reapareceu no
# feed em setembro carregando `<pubDate>` de setembro, e o classificador
# recebeu essa data como se fosse a de publicação (deu nota 7). A data REAL só
# existe dentro da própria matéria — daqui para baixo é a busca por ela.
_MESES_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

# Mês ABREVIADO — "Sep 4, 2026", "Sept. 4, 2026", "Aug 12, 2026", "Jan. 3,
# 2026" não batiam em nenhum padrão de `_PADROES_DATA_TEXTO` (só nome por
# extenso) e viravam None (achado do Apolo, 05/09/2026: 4 de 4 datelines
# abreviados testados contra um dateline real). "sept" ao lado de "sep" cobre
# a grafia mais longa que alguns veículos usam para setembro.
_MESES_EN_ABREV = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MESES_PT_ABREV = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}

# Até onde o REGEX procura um candidato de data no texto — não confundir com
# a regra que decide se ele CONTA como data de publicação: essa é
# `_JANELA_DATELINE` (40 chars), bem mais estreita. Esta janela mais larga (o
# mesmo piso usado como "início" em `_MIN_ARTICLE_CHARS`) só serve para ACHAR
# o padrão e então recusá-lo como citação dentro do texto quando ele cai fora
# do dateline — sem ela, uma data citada no meio da matéria nem seria vista
# para ser recusada, e os testes que provam essa recusa não teriam o que medir.
_JANELA_DATA_TEXTO = 200

# Janela do DATELINE de verdade — mais estreita que `_JANELA_DATA_TEXTO`.
# Incidente medido 05/09/2026 (fixture `farmprogress_may_wasde_20260905.html`):
# a matéria abre com o byline "May 11, 2026" na posição 0, mas uma data citada
# no MEIO da primeira frase (ex.: "...relatório de segunda, 15 de maio, veio
# antes...") ficaria dentro dos 200 chars sem ser o byline. Byline de verdade
# mora nos primeiros ~40 chars; qualquer match depois disso é citação dentro
# do texto, não a data de quando a matéria foi escrita.
_JANELA_DATELINE = 40

# Sanidade: nenhuma matéria real tem data de publicação fora deste intervalo.
# Protege contra metadado ou dateline malformado que `date()` aceitaria mas
# que não é uma data de publicação plausível (ano de 4 dígitos por acidente,
# OCR de PDF, etc.).
_ANO_MINIMO_PUBLICACAO = 2000

# (regex, extrator) → (ano, mês, dia). Ordem não importa para o resultado: ao
# achar mais de um padrão na janela, `_data_publicacao` fica com o de MENOR
# posição (o mais próximo do início do texto).
_PADROES_DATA_TEXTO = [
    # "May 11, 2026" / "May 11 2026"
    (re.compile(r"\b(" + "|".join(_MESES_EN) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE),
     lambda m: (int(m.group(3)), _MESES_EN[m.group(1).lower()], int(m.group(2)))),
    # "11 May 2026"
    (re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MESES_EN) + r")\s+(\d{4})\b", re.IGNORECASE),
     lambda m: (int(m.group(3)), _MESES_EN[m.group(2).lower()], int(m.group(1)))),
    # "11 de maio de 2026"
    (re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MESES_PT) + r")\s+de\s+(\d{4})\b", re.IGNORECASE),
     lambda m: (int(m.group(3)), _MESES_PT[m.group(2).lower()], int(m.group(1)))),
    # "Sep 4, 2026" / "Sept. 4, 2026" / "Aug 12, 2026" / "Jan. 3, 2026" — mês
    # abreviado em inglês, ponto opcional, vírgula opcional antes do ano. Sem
    # `\b` logo após o grupo do mês: "Sep" tenta primeiro e falha dentro de
    # "Sept" (o `\s+` seguinte não bate em "t"), e o motor de regex faz
    # backtracking para a alternativa "sept" sozinho — não depende de ordem.
    (re.compile(r"\b(" + "|".join(sorted(_MESES_EN_ABREV, key=len, reverse=True))
                + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.IGNORECASE),
     lambda m: (int(m.group(3)), _MESES_EN_ABREV[m.group(1).lower()], int(m.group(2)))),
    # "4 set. 2026" / "4 de set. de 2026" — mês abreviado em português, "de"
    # opcional dos dois lados (o RSS/site tanto omite quanto usa a forma
    # completa), ponto opcional depois da abreviação.
    (re.compile(r"\b(\d{1,2})\s+(?:de\s+)?(" + "|".join(_MESES_PT_ABREV)
                + r")\.?\s+(?:de\s+)?(\d{4})\b", re.IGNORECASE),
     lambda m: (int(m.group(3)), _MESES_PT_ABREV[m.group(2).lower()], int(m.group(1)))),
    # "11/05/2026" — convenção BR, dia/mês/ano. Ambíguo quando os DOIS
    # primeiros grupos são ≤ 12 (poderia ser mês/dia, convenção americana) —
    # "09/03/2026" é 9 de março (BR) ou 3 de setembro (US), indistinguível sem
    # mais contexto (achado do Apolo, 05/09/2026). `_ymd_dd_mm_br` levanta
    # ValueError nesse caso, que o laço abaixo já trata como "sem candidato".
    (re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b"),
     lambda m: _ymd_dd_mm_br(m)),
    # "2026-05-11"
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
     lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
]


def _ymd_dd_mm_br(m: re.Match) -> tuple[int, int, int]:
    """dd/mm/aaaa só é aceito quando é INEQUÍVOCO: se o dia (`m.group(1)`)
    fosse > 12 não haveria dúvida (não existe mês 13+), mas com os dois
    grupos ≤ 12 a mesma string também é uma data mm/dd/aaaa válida — e
    convenção americana e brasileira discordam sobre qual é qual. Levanta
    ValueError de propósito: o chamador (`_data_publicacao`) já trata
    ValueError/KeyError como "este padrão não achou nada aproveitável"."""
    dia, mes = int(m.group(1)), int(m.group(2))
    if dia <= 12 and mes <= 12:
        raise ValueError("data numérica ambígua entre dd/mm e mm/dd")
    return int(m.group(3)), mes, dia


def _data_valida(iso: str) -> bool:
    """Ano fora de [2000, ano atual + 1] não é data de publicação plausível —
    descarta metadado ou dateline malformado em vez de propagar lixo."""
    try:
        ano = int(iso[:4])
    except (ValueError, TypeError):
        return False
    return _ANO_MINIMO_PUBLICACAO <= ano <= date.today().year + 1


# Byline de verdade abre a matéria SEM preâmbulo ("May 11, 2026 The USDA's
# ...") ou vem logo depois de um separador de ESTRUTURA — quebra de linha,
# travessão (em/en dash), barra vertical ou ponto médio ("Sept. 4, 2026 — The
# ...", "Farm Progress|May 11, 2026"). Data citada em PROSA vem colada a uma
# PALAVRA comum, sem separador nenhum entre ela e a data ("As of May 11,
# 2026...", "By May 11, 2026...", "No dia 11 de maio de 2026...").
#
# LISTA BRANCA de separador (não lista NEGRA de preposição) de propósito: a
# negra vazava — "As of ", "By ", "From ", "Through ", "No dia " não estavam
# na lista antiga, e um dateline como "As of Aug. 20, 2026, U.S. corn
# stocks..." (prosa, não assinatura) passava como se fosse byline —
# condenando matéria FRESCA para sempre quando essa data citada era mais nova
# que a data real da matéria (achado da 3ª revisão do Apolo, 05/09/2026: uma
# lista negra por definição nunca cobre toda palavra que pode preceder uma
# data; a lista branca cobre todo separador plausível de estrutura, que é um
# conjunto bem menor e mais estável).
#
# `,`, `:`, `/` e `-` (hífen simples) SAÍRAM da lista na 4ª revisão do Apolo
# (05/09/2026): são pontuação comum de PROSA, não marca de estrutura. "Since
# Thursday, Aug. 20, 2026, corn futures..." e "Correction: Aug. 20, 2026
# WASDE..." tinham `<publicado_em>`/metadado corretos de HOJE, mas a vírgula e
# os dois-pontos abriam a mesma brecha da lista negra — a data de dentro da
# prosa vencia `min()` e condenava matéria FRESCA. Custo aceito: "Reuters, May
# 11, 2026 ..." (agência antes da data, separada por vírgula) volta a dar
# None — falso negativo por construção, mais barato que reabrir o buraco.
_SEPARADORES_VALIDOS_ANTES_DA_DATA = ("—", "–", "|", "·")

# Prefixo de BYLINE explícito ("Published May 11, 2026", "Posted on May 11,
# 2026") — o texto antes da data não é separador de pontuação nenhum, é uma
# PALAVRA, mas uma palavra que SÓ aparece rotulando a assinatura da matéria,
# nunca dentro de prosa citando outra data. Casamento por IGUALDADE exata
# (não prefixo/substring) do texto antes, inteiro — "By Jacqueline Holland"
# não é nenhum destes, então continua caindo na regra geral (rejeitado).
_BYLINE_PREFIXES_VALIDOS_ANTES_DA_DATA = {
    "published", "published on", "posted", "posted on", "updated",
    "publicado em", "publicado", "atualizado em",
}


def _precedido_de_separador_valido(inicio: str, pos: int) -> bool:
    """True quando o texto ANTES de `pos` está vazio (a data abre a matéria,
    sem preâmbulo), termina — depois de tirar espaço/tab à direita — em
    quebra de linha ou num dos `_SEPARADORES_VALIDOS_ANTES_DA_DATA`, ou é
    (inteiro, sem sobra, case-insensitive) um dos
    `_BYLINE_PREFIXES_VALIDOS_ANTES_DA_DATA`. Qualquer outro final (uma
    PALAVRA comum — "As of", "By", "No dia") é citação dentro da prosa, não
    dateline."""
    antes = inicio[:pos].rstrip(" \t")
    if not antes:
        return True
    if antes.endswith("\n"):
        return True
    if antes.endswith(_SEPARADORES_VALIDOS_ANTES_DA_DATA):
        return True
    return antes.strip().lower() in _BYLINE_PREFIXES_VALIDOS_ANTES_DA_DATA


def _data_publicacao(html: str, texto: str) -> str | None:
    """Data real de publicação da matéria, em ISO 8601 (`YYYY-MM-DD`), ou None.

    Incidente de 05/09/2026 (fixture `farmprogress_may_wasde_20260905.html`):
    uma matéria do WASDE de maio reapareceu no índice do Google em setembro, e
    tanto o metadado (`article:published_time`/`<time datetime>` — o que
    `extract_metadata` lê) quanto o `htmldate` pegaram a data de um CARD DE
    MATÉRIA RELACIONADA na lateral (`VerticalCard-Date`, "Sep 4, 2026"), mais
    nova que a matéria de verdade. A data real estava só no byline
    (`Contributors-Date`, "May 11, 2026"), que o `trafilatura.extract` traz
    como as primeiras palavras do corpo.

    Regra por construção: a data de publicação NUNCA é POSTERIOR a nenhuma
    outra data que a página exiba (card lateral, data de modificação etc.) —
    então, havendo mais de uma candidata plausível, fica com a MAIS ANTIGA:

    1. metadado do `trafilatura` (`extract_metadata` — mais leve que
       `extract`/`bare_extraction` porque não monta o corpo, só os campos do
       `<head>`).
    2. dateline: data escrita nos primeiros `_JANELA_DATELINE` chars do texto
       já extraído — só essa janela conta como "assinatura no topo da
       matéria"; mais adiante (ainda dentro de `_JANELA_DATA_TEXTO`) é citação
       dentro do texto, não a data de quando ela foi escrita. Duas defesas a
       mais dentro dessa janela (achados do Apolo, 05/09/2026): uma data
       numérica `dd/mm/aaaa` com os dois primeiros grupos ≤ 12 é descartada
       por ser ambígua com `mm/dd` (convenção americana); e uma data cujo
       texto anterior NÃO termina num separador de estrutura válido (lista
       branca — quebra de linha, travessão em/en dash, barra vertical, ponto
       médio, ou um prefixo de byline exato como "Published"/"Posted on" —
       ver `_precedido_de_separador_valido`) é descartada por ser referência
       dentro da prosa ("As of May 11, 2026...", "By May 11, 2026..."), não
       byline. `,`/`:`/`/`/`-` saíram da lista de separador na 4ª revisão do
       Apolo (05/09/2026): pontuação de prosa comum, não marca de estrutura —
       ver o comentário de `_SEPARADORES_VALIDOS_ANTES_DA_DATA`.

    Cada candidata passa por `_data_valida` (ano fora de [2000, ano atual+1]
    é descartado). Sem candidata válida, devolve None.

    Nunca levanta: HTML de terceiro é dado não confiável, e um metadado
    ilegível não pode derrubar a leitura da matéria por causa de um campo que
    é só um extra.
    """
    candidatas: list[str] = []

    try:
        doc = extract_metadata(html)
        if doc and doc.date and _data_valida(str(doc.date)):
            candidatas.append(str(doc.date))
    except Exception:
        pass

    inicio = (texto or "")[:_JANELA_DATA_TEXTO]
    melhor: str | None = None
    melhor_pos: int | None = None
    for padrao, para_ymd in _PADROES_DATA_TEXTO:
        m = padrao.search(inicio)
        if not m or m.start() >= _JANELA_DATELINE or (melhor_pos is not None and m.start() >= melhor_pos):
            continue
        if not _precedido_de_separador_valido(inicio, m.start()):
            # "As of May 11, 2026, U.S. corn..." ou "On May 11, 2026, the
            # USDA..." são REFERÊNCIA dentro do texto, não a assinatura de
            # quando a matéria foi escrita — byline de verdade não tem
            # preâmbulo de palavra comum (achado da 3ª revisão do Apolo,
            # 05/09/2026: lista branca de separador, não lista negra de
            # preposição — ver o comentário de `_SEPARADORES_VALIDOS_ANTES_DA_DATA`).
            continue
        try:
            ano, mes, dia = para_ymd(m)
            achado = date(ano, mes, dia).isoformat()
        except (ValueError, KeyError):
            continue
        if not _data_valida(achado):
            continue
        melhor, melhor_pos = achado, m.start()
    if melhor:
        candidatas.append(melhor)

    return min(candidatas) if candidatas else None


def read_article(url: str, timeout: float = 30.0, url_publisher: str = "") -> dict:
    """Lê o texto de um artigo via ScraperAPI.

    Google Notícias entrega uma página de redirecionamento em JS: o fetch
    simples do ScraperAPI devolve 404 para ela SEMPRE (medido 18/08/2026, 6
    de 6 links reais dos feeds "GN *"). `render=true` executa o JS e chega no
    artigo do publicador real — medição refeita na revisão do Apolo (achado
    5, mesma data): 5 chamadas reais lendo o header `sa-credit-cost` deram
    **35 créditos por chamada** (não 10) e **37,4-56,6s** (não 18-49s); 1 das
    4 chamadas com render devolveu HTTP 500. Por isso só liga automaticamente
    para link do Google — nunca para o tráfego geral desta ferramenta, que o
    agente de chat também usa livremente via a tool `read_article`. `timeout`
    é parâmetro do chamador de propósito: o caminho de captura do alerta
    (`alert_checker.py`) precisa de um teto bem maior que os 30s default para
    dar tempo ao render — e quando render está ligado, esta função IMPÕE um
    piso de `_RENDER_TIMEOUT_FLOOR` (75s) mesmo que o chamador passe menos,
    porque o caminho de chat (timeout default 30s) também pode receber uma
    URL do Google Notícias colada pelo usuário.
    """
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return {"erro": "SCRAPER_API_KEY não configurada"}
    try:
        # Perguntar o endereço real ao Google (~1s, 0 crédito) antes de mandar
        # o ScraperAPI renderizar o JS (35 créditos, 37-57s): quando funciona, a
        # leitura vira um fetch simples do artigo. Quando não, `render=true`
        # segue como estava — a resolução falhar devolve "" e nada muda.
        # DENTRO do try: `Thread.start()` levanta `RuntimeError` quando o SO
        # recusa a thread, e isso sobe na thread CHAMADORA — fora daqui, a
        # exceção subia até o loop de tools do reporter, que não tem try local
        # (5ª revisão do Apolo, 19/08/2026).
        alvo = resolve_google_news(url, host_esperado=url_publisher) or url
        params = {"api_key": api_key, "url": alvo}
        if _is_google_news_link(alvo):
            params["render"] = "true"
            timeout = max(timeout, _RENDER_TIMEOUT_FLOOR)
        resp = httpx.get(
            SCRAPER_FETCH_URL,
            params=params,
            # ATENÇÃO: isto NÃO é teto de tempo total. `httpx.Timeout` é por
            # OPERAÇÃO e o relógio do read reinicia a cada pedaço da resposta —
            # medido duas vezes na revisão do Apolo (19/08/2026): servidor
            # gotejando 1 chunk/s terminou em ~20s com 3s pedidos, tanto no float
            # solto quanto no objeto. O objeto serve para baixar o connect a 15s
            # (era o mesmo valor do read, até 75s). Quem PRECISA de teto real é a
            # resolução pré-envio, e ela tem o dela em
            # `alert_checker._LINK_PRAZO`; esta leitura roda depois da entrega,
            # onde demorar custa só o registro.
            timeout=httpx.Timeout(timeout, connect=15.0),
        )
        resp.raise_for_status()
        extrator = "trafilatura"
        text = _extrai_corpo(resp.text)
        if len(text) < _MIN_ARTICLE_CHARS:
            # Rede: página que o extrator não reconhece (layout exótico, paywall,
            # HTML quebrado) não pode virar conteúdo VAZIO — sem isto o alerta
            # perderia a âncora que ele JÁ tinha antes de 19/08/2026. A rede vale
            # também para extração CURTA e correta (nota de 2 frases): medido na
            # 2ª revisão do Apolo, o caminho bruto passava do piso nos dois casos
            # em que o trafilatura ficava em ~150 chars — desistir ali perdia a
            # âncora inteira tendo conserto na mão (achado 5).
            bruto = _texto_da_pagina(resp.text)
            if len(bruto) > len(text):
                text, extrator = bruto, "html_bruto"
        if len(text) < _MIN_ARTICLE_CHARS:
            # Âncora curta demais é âncora MENTIROSA: a página não renderizada do
            # Google Notícias devolve exatamente "Google News" (11 chars) pelos
            # DOIS caminhos, e isso ia para o banco como se fosse a matéria —
            # o modelo então recebe "conteúdo" em vez do aviso "não capturado,
            # não invente" (achado do Apolo, 19/08/2026).
            return {"erro": f"conteúdo curto demais ({len(text)} chars)", "url": url}
        # `alvo != url` = a resolução funcionou, e o endereço veio do PRÓPRIO
        # Google (já conferido contra o publicador lá dentro). Senão, a canônica
        # declarada pela página lida — que é texto de terceiro e por isso passa
        # pela conferência de host em `_url_canonica`.
        url_final = alvo if alvo != url else _url_canonica(resp.text, alvo, url_publisher)
        # `url` devolve o endereço que ABRE: este dicionário vira tool_result do
        # agente de chat, e nada no prompt diz qual campo citar — com o link do
        # Google aqui, ele repetia o 403 na conversa (achado 6 da 2ª revisão).
        # `url_origem` guarda o que foi pedido, para rastro.
        # `data_publicacao` entra SEMPRE (mesmo None): campo ausente faria
        # `alert_checker._confirmar_frescor` não distinguir "sem data" de "não
        # perguntei" — a captura confirma frescor precisa do valor explícito.
        resultado = {"url": url_final or alvo, "conteudo": text[:_MAX_ARTICLE_CHARS],
                     "extrator": extrator, "data_publicacao": _data_publicacao(resp.text, text)}
        if url != resultado["url"]:
            resultado["url_origem"] = url
        if url_final:
            resultado["url_final"] = url_final
        return resultado
    except httpx.TimeoutException:
        return {"erro": "timeout ao buscar artigo", "url": url}
    except Exception as e:
        return {"erro": sanitize_error(e), "url": url}


def search(query: str) -> dict:
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return {"erro": "SCRAPER_API_KEY não configurada"}
    try:
        params = {
            "api_key": api_key,
            "query": query,
            "country": "br",
            "num_results": 5,
        }
        resp = httpx.get(SCRAPER_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        organic = data.get("organic_results", [])
        resultados = [
            {"titulo": r.get("title", ""), "snippet": r.get("snippet", ""), "link": r.get("link", "")}
            for r in organic
        ]
        return {"resultados": resultados, "query": query}
    except httpx.TimeoutException:
        return {"erro": "timeout na busca", "resultados": []}
    except Exception as e:
        return {"erro": sanitize_error(e), "resultados": []}
