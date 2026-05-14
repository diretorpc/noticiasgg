import os
import re
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
SCRAPER_URL = "https://api.scraperapi.com/"
G1_ELEICOES_URL = "https://g1.globo.com/politica/eleicoes/2026/"

POLL_KEYWORDS = ["pesquisa", "quaest", "datafolha", "atlas", "mda", "intenção de voto", "turno"]


def fetch(url: str) -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.get(SCRAPER_URL, params={"api_key": SCRAPER_API_KEY, "url": url})
        resp.raise_for_status()
        return resp.text


def find_poll_urls() -> list[str]:
    html = fetch(G1_ELEICOES_URL)
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        if any(kw in text for kw in POLL_KEYWORDS) and "g1.globo.com" in href:
            if href not in urls:
                urls.append(href)
    return urls[:5]


def extract_poll_data(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    instituto = None
    for inst in ["Quaest", "Datafolha", "AtlasIntel", "Atlas Intel", "MDA", "Ipespe"]:
        if inst.lower() in text.lower():
            instituto = inst
            break

    if not instituto:
        return None

    CANDIDATOS = [
        "Lula", "Flávio Bolsonaro", "Flavio Bolsonaro", "Jair Bolsonaro",
        "Ronaldo Caiado", "Romeu Zema", "Renan Santos", "Augusto Cury",
        "Cabo Daciolo", "Samara Martins", "Aldo Rebelo", "Hertz Dias",
        "Tarcísio de Freitas", "Tarcisio de Freitas", "Ratinho Junior",
        "Eduardo Leite", "Simone Tebet", "Ciro Gomes",
    ]

    candidates = {}
    for candidato in CANDIDATOS:
        pattern = re.compile(
            re.escape(candidato) + r"[^\d]{0,30}?(\d{1,2})%",
            re.IGNORECASE
        )
        match = pattern.search(text)
        if match:
            candidates[candidato] = f"{match.group(1)}%"

    if not candidates:
        return None

    data_pesquisa = None
    data_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if data_match:
        d, m, y = data_match.group(1), data_match.group(2), data_match.group(3)
        data_pesquisa = f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    return {
        "instituto": instituto,
        "data_pesquisa": data_pesquisa,
        "candidatos": candidates,
    }


def collect() -> list[dict]:
    if not SCRAPER_API_KEY:
        raise ValueError("SCRAPER_API_KEY não configurada")

    poll_urls = find_poll_urls()
    resultados = []
    vistos = set()

    for url in poll_urls:
        try:
            html = fetch(url)
            data = extract_poll_data(html)
            if data and data["instituto"] not in vistos:
                vistos.add(data["instituto"])
                data["fonte_url"] = url
                resultados.append(data)
        except Exception:
            continue

    return resultados


@router.get("/api/collectors/polls-br")
async def get_polls_br():
    try:
        data = collect()
        return {"data": data, "collected_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
