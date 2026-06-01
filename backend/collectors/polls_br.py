import asyncio
import concurrent.futures
import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from fastapi import APIRouter, HTTPException
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from backend.services import supabase as supa

load_dotenv()

router = APIRouter()

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SCRAPER_URL = "https://api.scraperapi.com/"
SCRAPER_SEARCH_URL = "https://api.scraperapi.com/structured/google/search"
GAZETA_BASE_URL = "https://www.gazetadopovo.com.br/eleicoes/2026/pesquisa-eleitoral-2026/"

_MESES_PT = {
    "jan": "01", "fev": "02", "mar": "03", "abr": "04",
    "mai": "05", "jun": "06", "jul": "07", "ago": "08",
    "set": "09", "out": "10", "nov": "11", "dez": "12",
    "janeiro": "01", "fevereiro": "02", "março": "03", "abril": "04",
    "maio": "05", "junho": "06", "julho": "07", "agosto": "08",
    "setembro": "09", "outubro": "10", "novembro": "11", "dezembro": "12",
}

_MESES_SLUG = {
    "01": "janeiro", "02": "fevereiro", "03": "marco", "04": "abril",
    "05": "maio", "06": "junho", "07": "julho", "08": "agosto",
    "09": "setembro", "10": "outubro", "11": "novembro", "12": "dezembro",
}

_CANDIDATOS = [
    ("Lula", ["Lula"]),
    ("Flávio Bolsonaro", ["Flávio Bolsonaro", "Flavio Bolsonaro"]),
    ("Tarcísio de Freitas", ["Tarcísio de Freitas", "Tarcisio de Freitas"]),
    ("Romeu Zema", ["Romeu Zema"]),
    ("Ronaldo Caiado", ["Ronaldo Caiado"]),
    ("Renan Santos", ["Renan Santos"]),
    ("Samara Martins", ["Samara Martins"]),
    ("Augusto Cury", ["Augusto Cury"]),
    ("Cabo Daciolo", ["Cabo Daciolo"]),
    ("Ratinho Junior", ["Ratinho Junior"]),
    ("Aldo Rebelo", ["Aldo Rebelo"]),
    ("Pablo Marçal", ["Pablo Marçal", "Pablo Marcal"]),
    ("Guilherme Boulos", ["Guilherme Boulos"]),
    ("Marina Silva", ["Marina Silva"]),
    ("Michelle Bolsonaro", ["Michelle Bolsonaro"]),
    ("Simone Tebet", ["Simone Tebet"]),
    ("Ciro Gomes", ["Ciro Gomes"]),
]

_GAZETA_SLUGS = [
    ("Datafolha", "datafolha-presidente"),
    ("Quaest", "quaest-presidente"),
    ("AtlasIntel", "atlasintel-presidente"),
    ("MDA", "cnt-mda-presidente"),
    ("Ipespe", "ipespe-presidente"),
    ("Paraná Pesquisas", "parana-pesquisas-presidente"),
    ("Nexus", "nexus-btg-presidente"),
    ("Vox Brasil", "vox-brasil-presidente"),
    ("Futura", "futura-presidente"),
    ("ModalMais", "modal-mais-presidente"),
]

# Fontes diretas: (instituto, url, keyword_re, render_js)
# keyword_re=None → parseia a URL diretamente sem etapa de listagem
# render_js=True  → usa ScraperAPI com JavaScript rendering (5-10x créditos)
_DIRECT_SOURCES = [
    ("Nexus", "https://www.nexus.fsb.com.br/estudos-divulgados/", r"president|elei[çc]|2026", False),
    ("Ipespe", "https://ipespe.org.br/tags/eleicoes-2026/", r"pulso|pesquisa|president", False),
    ("AtlasIntel", "https://atlasintel.org/polls/general-release-polls", r"brazil|brasil|national", False),
    ("Paraná Pesquisas", "https://paranapesquisas.com.br/", r"president", False),
    ("Datafolha", "https://datafolha.folha.uol.com.br/politica/", r"president", False),
    ("Vox Brasil", "https://www.voxbrasil.com.br/", r"president", False),
    ("Futura", "https://futuraresearch.com.br/", r"president|elei[çc]", False),
]


async def _fetch(url: str, render: bool = False) -> str:
    params: dict = {"api_key": SCRAPER_API_KEY, "url": url}
    if render:
        params["render"] = "true"
    timeout = 45 if render else 20
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(SCRAPER_URL, params=params)
        resp.raise_for_status()
        return resp.text


def _parse_date(text: str) -> str | None:
    m = re.search(
        r"(?:entre|dias?)\s+(\d{1,2})\s+(?:[ae]|até)\s+\d{1,2}\s+de\s+(\w+)(?:\s+de\s+(20\d\d))?",
        text, re.IGNORECASE,
    )
    if not m:
        m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(20\d\d)", text, re.IGNORECASE)
    if not m:
        m2 = re.search(r"(\d{1,2})/(\d{2})/(20\d\d)", text)
        if m2:
            return f"{m2.group(3)}-{m2.group(2)}-{m2.group(1).zfill(2)}"
    if m:
        day = int(m.group(1))
        mes_str = m.group(2).lower()
        year = int(m.group(3)) if (m.lastindex or 0) >= 3 and m.group(3) else 2026
        month = _MESES_PT.get(mes_str[:3]) or _MESES_PT.get(mes_str)
        if month:
            return f"{year}-{month}-{str(day).zfill(2)}"
    return None


def _extract_candidates(text: str) -> dict[str, str]:
    _pct = r"(\d{1,2}(?:[,\.]\d+)?)"

    # Localiza "cenário estimulado" que é seguido de dados reais (% dentro de 60 chars).
    # Isso distingue a seção de tabela ("Lula (PT): 38%") das frases descritivas
    # ("...quando os nomes são mostrados..."), onde o primeiro % aparece 80+ chars depois.
    search_text = text
    for m in re.finditer(r"cen[áa]rio estimulado", text, re.IGNORECASE):
        immediate = text[m.end(): m.end() + 60]
        if re.search(r"\d+%", immediate):
            snippet = text[m.end(): m.end() + 600]
            end_m = re.search(
                r"cen[áa]rio espont[âa]neo|segundo turno|2[oº°]?\s*turno",
                snippet, re.IGNORECASE,
            )
            search_text = snippet[: end_m.start()] if end_m else snippet
            break

    candidatos: dict[str, str] = {}
    for nome, variantes in _CANDIDATOS:
        for v in variantes:
            pat = re.compile(re.escape(v) + r"[^\d]{0,50}?" + _pct + r"%", re.IGNORECASE)
            mt = pat.search(search_text)
            if not mt:
                pat_rev = re.compile(_pct + r"%[^\d]{0,50}?" + re.escape(v), re.IGNORECASE)
                mt = pat_rev.search(search_text)
            if mt and nome not in candidatos:
                val = float(mt.group(1).replace(",", "."))
                if 0 < val < 99:
                    candidatos[nome] = (
                        f"{int(val)}%" if val == int(val)
                        else f"{val:.1f}%".replace(".", ",")
                    )
                break
    return candidatos


def _detect_turno(text: str) -> str:
    text_l = text.lower()
    has_segundo = any(k in text_l for k in ["segundo turno", "2º turno", "2o turno"])
    has_primeiro = any(k in text_l for k in ["primeiro turno", "1º turno", "cenário estimulado"])
    if has_segundo and not has_primeiro:
        return "2º turno"
    return "1º turno"


def _parse_article(html: str, instituto: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    # Usa espaço como separador e normaliza whitespace para não quebrar nomes
    # multi-palavra que ficam em spans separados (ex: "Flávio\nBolsonaro" → "Flávio Bolsonaro")
    text = re.sub(r"\s+", " ", soup.get_text(separator=" "))
    candidatos = _extract_candidates(text)
    if not candidatos:
        return None
    return {
        "instituto": instituto,
        "turno": _detect_turno(text),
        "data_pesquisa": _parse_date(text),
        "candidatos": candidatos,
    }


def _find_poll_link(html: str, base_url: str, keyword_re: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(keyword_re, re.IGNORECASE)
    parsed_base = urlparse(base_url)

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        link_text = a.get_text(strip=True)
        if not pattern.search(link_text + " " + href):
            continue
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc == parsed_base.netloc and len(parsed.path.strip("/")) > 5:
            return full_url
    return None


async def _gazeta_one(instituto: str, slug: str, now: datetime) -> dict | None:
    """Tenta mês atual e anterior em paralelo, prefere o mais recente."""
    mes_atual = f"{now.month:02d}"
    mes_anterior = f"{(now.month - 1) or 12:02d}"
    ano_anterior = now.year if now.month > 1 else now.year - 1

    url_a = f"{GAZETA_BASE_URL}{slug}-{_MESES_SLUG[mes_atual]}-{now.year}/"
    url_b = f"{GAZETA_BASE_URL}{slug}-{_MESES_SLUG[mes_anterior]}-{ano_anterior}/"

    async def try_url(url: str) -> dict | None:
        try:
            html = await _fetch(url)
            return _parse_article(html, instituto)
        except Exception:
            return None

    results = await asyncio.gather(try_url(url_a), try_url(url_b))
    return results[0] or results[1]


async def _quaest_via_search() -> dict | None:
    """Busca o artigo mais recente da Quaest via Google Search (ScraperAPI structured).
    Tenta extrair dos snippets primeiro; se insuficiente, busca o artigo completo.
    Custo: ~25 créditos por execução.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(SCRAPER_SEARCH_URL, params={
                "api_key": SCRAPER_API_KEY,
                "query": "quaest genial pesquisa presidente 2026 intenção de voto",
                "country": "br",
                "num_results": 5,
            })
            resp.raise_for_status()
            results = resp.json().get("organic_results", [])

        for r in results:
            # Sempre busca o artigo completo — snippets têm poucos candidatos e sem data
            url = r.get("link", "")
            if url:
                try:
                    html = await _fetch(url)
                    data = _parse_article(html, "Quaest")
                    if data and len(data.get("candidatos", {})) >= 2:
                        return data
                except Exception:
                    pass
            # Fallback: usa snippet apenas se o artigo falhou
            combined = r.get("title", "") + " " + r.get("snippet", "")
            candidatos = _extract_candidates(combined)
            if len(candidatos) >= 5:
                return {
                    "instituto": "Quaest",
                    "turno": _detect_turno(combined),
                    "data_pesquisa": _parse_date(combined),
                    "candidatos": candidatos,
                }
    except Exception:
        return None
    return None


async def _direct_one(instituto: str, url: str, keyword_re: str | None, render: bool = False) -> dict | None:
    """Busca pesquisa de um instituto.
    keyword_re=None → parseia a URL diretamente (com render opcional).
    keyword_re≠None → busca listagem, acha link, parseia artigo.
    """
    try:
        html = await _fetch(url, render=render)
        if keyword_re is None:
            return _parse_article(html, instituto)
        link = _find_poll_link(html, url, keyword_re)
        if not link:
            return None
        article_html = await _fetch(link)
        return _parse_article(article_html, instituto)
    except Exception:
        return None


async def collect_async() -> list[dict]:
    if not SCRAPER_API_KEY:
        raise ValueError("SCRAPER_API_KEY não configurada")

    now = datetime.now()

    # Gazeta do Povo: todos os institutos em paralelo
    gazeta_tasks = [_gazeta_one(inst, slug, now) for inst, slug in _GAZETA_SLUGS]
    gazeta_results = await asyncio.gather(*gazeta_tasks, return_exceptions=True)
    resultados = [r for r in gazeta_results if isinstance(r, dict) and r.get("candidatos")]

    # Direto: institutos ainda não cobertos, também em paralelo
    seen = {r["instituto"] for r in resultados}
    direct_tasks = [
        _direct_one(inst, url, kw, render)
        for inst, url, kw, render in _DIRECT_SOURCES
        if inst not in seen
    ]
    # Quaest via Google Search (site deles é JS-heavy e bloqueia scraping direto)
    if "Quaest" not in seen:
        direct_tasks.append(_quaest_via_search())

    if direct_tasks:
        direct_results = await asyncio.gather(*direct_tasks, return_exceptions=True)
        seen_direct: set[str] = set()
        for r in direct_results:
            if isinstance(r, dict) and r.get("candidatos") and r["instituto"] not in seen and r["instituto"] not in seen_direct:
                resultados.append(r)
                seen_direct.add(r["instituto"])

    if resultados:
        try:
            supa.save_polls(resultados)
        except Exception:
            pass
    else:
        try:
            resultados = supa.get_polls()
        except Exception:
            pass

    return resultados


def collect() -> list[dict]:
    try:
        asyncio.get_running_loop()
        # Already inside an event loop (e.g. FastAPI async handler) — run in a fresh thread
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, collect_async()).result(timeout=90)
    except RuntimeError:
        return asyncio.run(collect_async())


@router.get("/api/collectors/polls-br")
async def get_polls_br():
    try:
        data = await collect_async()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
