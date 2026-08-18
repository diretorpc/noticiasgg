import os
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
import httpx
from dotenv import load_dotenv

from backend.services import config

load_dotenv()

router = APIRouter()

NEWSAPI_EVERYTHING = "https://newsapi.org/v2/everything"
NEWSAPI_HEADLINES = "https://newsapi.org/v2/top-headlines"

SOURCES_FINANCE = ",".join([
    "reuters",
    "the-wall-street-journal",
    "financial-times",
    "the-economist",
    "cnbc",
    "forbes",
    "bbc-news",
    "the-guardian-uk",
    "cnn",
    "associated-press",
    "the-washington-post",
    "business-insider",
    "politico",
])

SOURCES_TECH = ",".join([
    "techcrunch",
    "wired",
    "the-verge",
    "ars-technica",
])

_FINANCE_QUERY = (
    "economy OR market OR inflation OR stocks OR bonds OR commodities "
    "OR GDP OR Fed OR interest rate OR trade OR dollar OR oil "
    "OR OPEC OR USDA OR crop OR harvest OR drought OR \"La Nina\" OR \"El Nino\" "
    "OR PMI OR China OR sanctions OR tariff OR freight OR fertilizer"
)

_AI_QUERY = (
    '"artificial intelligence" OR "machine learning" OR "LLM" OR '
    '"OpenAI" OR "Anthropic" OR "Google AI" OR "generative AI" OR '
    '"AI model" OR "large language model"'
)

_MAX_AGE = timedelta(hours=48)

# Sem User-Agent de navegador o Nasdaq trava a conexão até estourar o timeout:
# 15s desperdiçados por rodada, 96 rodadas/dia, e zero artigo. Medido 11/08/2026.
# Não resgata quem bloqueia de fato (WEF, Trading Economics, AgWeb seguem 403).
# Uma fonte que PENDURA (aceita a conexão e não responde) custa o timeout inteiro.
# Com 20 fontes a 15s, o pior caso encosta nos 300s da Vercel — e 6 delas moram no
# mesmo servidor do Google, então um soluço só levaria 90s. Nenhuma fonte viva passou
# de 2,1s na medição de 11/08/2026, então 6s dá folga de 3x sem arriscar o teto.
_RSS_TIMEOUT = 6.0

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

def _google_news(query: str, lang: str = "en") -> str:
    """Busca do Google Notícias como feed. É a única via para fontes que bloqueiam
    robô direto (Reuters, WSJ, USDA, Trading Economics) — o Google já as leu.
    `when:2d` não é enfeite: sem ele o Google ordena por relevância e devolve
    notícia velha (medido 11/08/2026: 0 itens frescos virando 2 com o parâmetro).
    ⚠️ Endereço não documentado pelo Google — pode mudar sem aviso. Se as buscas
    pararem de trazer item, é aqui que se olha primeiro."""
    loc = "hl=pt-BR&gl=BR&ceid=BR:pt-419" if lang == "pt" else "hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={quote(query + ' when:2d')}&{loc}"


# RSS feeds sem paywall, focados em commodities/macro.
# Medir antes de mexer (data do item mais recente por fonte):
#   python -c "from backend.collectors import news; [print(n, news.validate_feed(u)) for n,u in news._RSS_FEEDS]"
# Em 11/08/2026 a lista anterior (WEF, DW, Corriere, Le Monde, Japan Times, Global
# Times) rendia 5 de 6 fontes mortas em silêncio — o Corriere parado desde 05/2024 —
# e as vivas eram capa de jornal geral, que o classificador descartava como ruído.
_RSS_FEEDS = [
    # BRASIL — era o buraco maior: sobrava só o Canal Rural, e a consulta de
    # manchetes br do NewsAPI devolve zero (medido 11/08/2026).
    ("Canal Rural", "https://www.canalrural.com.br/feed/"),
    ("Agência Brasil Economia", "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml"),
    ("G1 Economia", "https://g1.globo.com/rss/g1/economia/"),
    ("G1 Agro", "https://g1.globo.com/rss/g1/economia/agronegocios/"),
    ("Money Times", "https://www.moneytimes.com.br/feed/"),
    # COMMODITIES / MACRO
    ("OilPrice", "https://oilprice.com/rss/main"),
    ("Investing Commodities", "https://www.investing.com/rss/commodities.rss"),
    ("Investing Energia/Metais", "https://www.investing.com/rss/news_11.rss"),
    ("Investing Indicadores", "https://www.investing.com/rss/news_95.rss"),
    ("Nasdaq Commodities", "https://www.nasdaq.com/feed/rssoutbound?category=Commodities"),
    # AGRO INTERNACIONAL / FRETE
    ("Farm Progress", "https://www.farmprogress.com/rss.xml"),
    ("Hellenic Shipping", "https://www.hellenicshippingnews.com/feed/"),
    ("gCaptain", "https://gcaptain.com/feed/"),
    ("DW Top Stories", "https://rss.dw.com/xml/rss-en-top"),
    # Buracos que feed direto não cobre porque a fonte bloqueia robô.
    ("GN USDA/WASDE", _google_news("WASDE OR USDA grain report")),
    ("GN OPEP", _google_news("OPEC oil production")),
    ("GN China demanda", _google_news("China imports commodities")),
    ("GN Fed/inflação", _google_news("Fed CPI PPI inflation")),
    ("GN Rússia/petróleo", _google_news("Russia sanctions oil")),
    ("GN Ucrânia/trigo", _google_news("Ukraine wheat fertilizer")),
]

# RSS feeds especializados em IA
_RSS_FEEDS_AI = [
    ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
]


def _sources_param(key: str, default_csv: str) -> str:
    """Lista de fontes do config (list[str]) → CSV; senão o default CSV."""
    val = config.get("news." + key, None)
    if isinstance(val, list) and val:
        return ",".join(str(s) for s in val)
    return default_csv


def _feeds(key: str, default_tuples: list[tuple]) -> list[tuple]:
    """Feeds do config (list[{nome,url}]) → list[(nome,url)]; senão o default."""
    val = config.get("news." + key, None)
    if isinstance(val, list) and val:
        out = [
            (str(f.get("nome", "")), f["url"])
            for f in val
            if isinstance(f, dict) and isinstance(f.get("url"), str) and f.get("url")
        ]
        if out:
            return out
    # cópia: devolver a lista-constante do módulo deixaria um caller mutá-la
    # (ex.: `feeds += ...`) e corromper o default para todo o processo — a função
    # da Vercel reaproveita a instância entre requisições.
    return list(default_tuples)


def _ordena_por_recencia(artigos: list[dict]) -> list[dict]:
    """Rodízio: a mais recente de CADA fonte, depois a 2ª de cada, e assim por diante.
    Dentro de cada rodada, ordena por data.

    Três problemas medidos em 11/08/2026 levaram a este formato, nesta ordem:
    1. Sem ordenação nenhuma, quem decidia era a POSIÇÃO da fonte na lista — o
       alert_checker varre só os 20 primeiros, então fonte no fim nunca era lida.
    2. Ordenando só por data, fonte que publica muito engolia a janela: 6 fontes de
       20 ficavam com as 20 vagas, e o G1 punha "Auxílio-doença" num agente de commodities.
    3. Com teto de 2 por fonte ainda eram 11 de 20, e as 6 buscas do Google Notícias
       (USDA, OPEP, Fed, Rússia, Ucrânia, China) caíam nas posições 24-39 — fora da
       janela, sempre, porque `when:2d` traz item de até 2 dias e perde no critério
       de recência para quem publica de minuto em minuto.
    Com rodízio cada fonte recebe uma vaga antes de qualquer uma repetir. Quando há
    mais fontes que vagas (o NewsAPI acrescenta as dele nas rodadas em que roda), o
    excesso é rebaixado, não descartado — o relatório diário consome a lista inteira.
    Data ausente ou ilegível vai para o fim: é o dado menos confiável, não pode furar
    a fila. Quantas fontes de fato entram na janela, medir — não cravar aqui:
      python -c "import httpx;from backend.collectors import news as n;c=httpx.Client(timeout=n._RSS_TIMEOUT,headers=n._BROWSER_HEADERS);a=n._ordena_por_recencia(n._collect_rss(c,n._feeds('rss_feeds',n._RSS_FEEDS),set()));print(len({x['fonte'] for x in a[:20]}),'fontes nas 20 vagas')"
    """
    def chave(a: dict) -> tuple[int, float]:
        bruto = a.get("publicado_em")
        if not bruto:
            return (1, 0.0)
        try:
            dt = datetime.fromisoformat(str(bruto).replace("Z", "+00:00"))
        except Exception:
            return (1, 0.0)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (0, -dt.timestamp())

    rodadas: dict[int, list[dict]] = defaultdict(list)
    ja_vistos: Counter = Counter()
    for a in sorted(artigos, key=chave):
        fonte = a.get("fonte") or ""
        rodadas[ja_vistos[fonte]].append(a)
        ja_vistos[fonte] += 1
    return [a for i in sorted(rodadas) for a in rodadas[i]]


def _parse_feed(content: bytes) -> dict:
    """Parseia bytes de um feed RSS/Atom. Retorna validade, nº de itens e
    o título do primeiro item. Puro (sem rede) para facilitar teste."""
    try:
        root = ET.fromstring(content)
    except Exception:
        return {"valid": False, "item_count": 0, "sample_title": None,
                "error": "conteúdo não é XML"}
    items = root.findall(".//item")
    if not items:
        items = [e for e in root.iter() if e.tag.endswith("entry")]  # Atom
    if not items:
        return {"valid": False, "item_count": 0, "sample_title": None,
                "error": "feed sem itens (<item>/<entry>)"}
    sample = None
    for child in items[0].iter():
        if child.tag.endswith("title") and child.text and child.text.strip():
            sample = child.text.strip()
            break
    return {"valid": True, "item_count": len(items), "sample_title": sample, "error": None}


def validate_feed(url: str) -> dict:
    """Busca uma URL de RSS/Atom e valida o conteúdo. Nunca levanta exceção."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=10)
    except Exception:
        return {"valid": False, "item_count": 0, "sample_title": None,
                "error": "falha ao buscar a URL"}
    if resp.status_code != 200:
        return {"valid": False, "item_count": 0, "sample_title": None,
                "error": f"HTTP {resp.status_code}"}
    return _parse_feed(resp.content)


def _is_fresh(published_at: str | None) -> bool:
    if not published_at:
        return True
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        # Sem fuso, a subtração abaixo estoura com TypeError e o except devolvia
        # "fresca" — fonte que omite o fuso entupia o sistema com notícia velha.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt <= _MAX_AGE
    except Exception:
        return True


def _parse_rss_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.isoformat()
        except Exception:
            return None


def _collect_rss(client: httpx.Client, feeds: list[tuple[str, str]], vistos: set) -> list[dict]:
    artigos = []
    for source_name, url in feeds:
        try:
            # timeout por requisição: o cliente é compartilhado com o NewsAPI, que
            # pode demorar mais legitimamente. Só o RSS tem o limite curto.
            resp = client.get(url, follow_redirects=True, timeout=_RSS_TIMEOUT)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            # suporte a RSS 2.0 e RDF
            ns = {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}
            items = root.findall(".//item")
            for item in items[:5]:
                link = (item.findtext("link") or "").strip()
                if not link or link in vistos:
                    continue
                title = item.findtext("title") or ""
                pub_date = _parse_rss_date(item.findtext("pubDate") or item.findtext("dc:date"))
                if not _is_fresh(pub_date):
                    continue
                description = item.findtext("description") or ""
                # O Google Notícias carimba o veículo real em <source url="...">Nome</source>.
                # Sem isso, `fonte` era o apelido da BUSCA ("GN USDA/WASDE") — atribuição
                # de autoria falsa (achado A6) — e o <link> é uma página JS de ~592 KB que
                # `read_article` não consegue ler (achado A2, incidente USDA de 18/08/2026).
                # Não decodificar o CBMi... do link: é protobuf não documentado do Google.
                source_el = item.find("source")
                publisher_nome = (source_el.text or "").strip() if source_el is not None and source_el.text else ""
                publisher_url = source_el.get("url") if source_el is not None else None
                vistos.add(link)
                artigos.append({
                    "titulo": title.strip(),
                    "fonte": publisher_nome or source_name,
                    "feed": source_name,
                    "url": link,
                    "url_publisher": publisher_url,
                    "publicado_em": pub_date,
                    "resumo": description[:300].strip() if description else None,
                })
        except Exception:
            continue
    return artigos


def _fetch_newsapi(client: httpx.Client, url: str, params: dict, vistos: set,
                   errors: list[str] | None, label: str) -> list[dict]:
    resp = client.get(url, params=params)
    if resp.status_code != 200:
        # 429 = limite diário do free tier estourado — reportar para o auto-alerta
        if errors is not None:
            errors.append(f"newsapi {label}: HTTP {resp.status_code}")
        return []
    artigos = []
    for a in resp.json().get("articles", []):
        article_url = a.get("url", "")
        published_at = a.get("publishedAt")
        if article_url in vistos or not _is_fresh(published_at):
            continue
        vistos.add(article_url)
        artigos.append({
            "titulo": a.get("title"),
            "fonte": (a.get("source") or {}).get("name"),
            "url": article_url,
            "publicado_em": published_at,
            "resumo": a.get("description"),
        })
    return artigos


def collect(include_ai: bool = True, include_newsapi: bool = True,
            errors: list[str] | None = None) -> list[dict]:
    api_key = os.getenv("NEWS_API_KEY", "")
    if not api_key:
        raise ValueError("NEWS_API_KEY não configurada")

    artigos = []
    vistos: set = set()

    with httpx.Client(timeout=15, headers=_BROWSER_HEADERS) as client:
        if include_newsapi:
            # Finanças: /everything filtrado por fontes financeiras + keywords
            artigos.extend(_fetch_newsapi(client, NEWSAPI_EVERYTHING, {
                "apiKey": api_key,
                "sources": _sources_param("sources_finance", SOURCES_FINANCE),
                "q": config.get_str("news.finance_query", _FINANCE_QUERY),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 15,
            }, vistos, errors, "finance"))

            # BR: top-headlines categoria business
            artigos.extend(_fetch_newsapi(client, NEWSAPI_HEADLINES, {
                "apiKey": api_key,
                "country": "br",
                "category": "business",
                "pageSize": 10,
            }, vistos, errors, "br"))

            # IA/Tech: /everything com fontes tech + query de IA
            if include_ai:
                artigos.extend(_fetch_newsapi(client, NEWSAPI_EVERYTHING, {
                    "apiKey": api_key,
                    "sources": _sources_param("sources_tech", SOURCES_TECH),
                    "q": config.get_str("news.ai_query", _AI_QUERY),
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                }, vistos, errors, "ai"))

        # RSS internacionais são grátis e sempre coletados; os de IA seguem o
        # include_ai, igual ao bloco de IA do NewsAPI acima. Sem isso o alert_checker
        # pedia include_ai=False e mesmo assim recebia MIT Tech Review/VentureBeat,
        # que ocupavam as 5 vagas de classificação com artigos de nota 1 e deixavam
        # a notícia de mundo/economia na fila (visto em produção 21/07/2026).
        feeds = _feeds("rss_feeds", _RSS_FEEDS)
        if include_ai:
            feeds = feeds + _feeds("rss_feeds_ai", _RSS_FEEDS_AI)  # sem += : não muta a lista de origem
        artigos.extend(_collect_rss(client, feeds, vistos))

    return _ordena_por_recencia(artigos)[:40]


def source_health() -> dict:
    """Quais fontes entregaram item fresco AGORA, medido pelo coletor real.
    `validate_feed` não serve para isto: ele só prova que o XML abre — o Nasdaq
    passava nele e devolvia zero artigo (11/08/2026). O boletim diário conferia
    apenas se a NEWS_API_KEY existe, nunca se alguma fonte trazia alguma coisa;
    foi essa cegueira que deixou 5 feeds mortos por meses sem ninguém notar."""
    feeds = _feeds("rss_feeds", _RSS_FEEDS)
    try:
        with httpx.Client(timeout=_RSS_TIMEOUT, headers=_BROWSER_HEADERS) as client:
            artigos = _collect_rss(client, feeds, set())
    except Exception as e:
        return {"total": len(feeds), "vivas": 0, "mortas": [], "erro": str(e)[:120]}
    vivas = {a.get("fonte") for a in artigos}
    mortas = [nome for nome, _ in feeds if nome not in vivas]
    return {"total": len(feeds), "vivas": len(feeds) - len(mortas), "mortas": mortas, "erro": None}


def describe_config() -> dict:
    """Snapshot read-only da config efetiva (override do banco ou default)."""
    return {
        "sources_finance": _sources_param("sources_finance", SOURCES_FINANCE).split(","),
        "sources_tech": _sources_param("sources_tech", SOURCES_TECH).split(","),
        "finance_query": config.get_str("news.finance_query", _FINANCE_QUERY),
        "ai_query": config.get_str("news.ai_query", _AI_QUERY),
        "rss_feeds": [{"nome": n, "url": u} for n, u in _feeds("rss_feeds", _RSS_FEEDS)],
        "rss_feeds_ai": [{"nome": n, "url": u} for n, u in _feeds("rss_feeds_ai", _RSS_FEEDS_AI)],
    }


@router.get("/api/collectors/news")
async def get_news():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
