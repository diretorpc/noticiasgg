import os

from fastapi import HTTPException, Query

from backend.services import supabase


def selflink_url(token: str) -> str:
    """Endereço da página pessoal /me. Fonte única: o painel (admin) e o bot do
    WhatsApp entregam este mesmo link."""
    base = os.environ.get("PANEL_BASE_URL", "https://noticiasgg-painel.vercel.app").rstrip("/")
    return f"{base}/me?token={token}"


def panel_link(user: dict | None) -> str | None:
    """Link /me de quem está falando, ou None se o admin ainda não gerou um."""
    token = (user or {}).get("selflink_token")
    return selflink_url(token) if token else None


# O que o MODELO vê no lugar do link. O token dá escrita na grade do relatório
# (`PUT /api/me/schedule`), e o modelo tem ferramentas que mandam texto para fora
# (`read_article`, `search_web` via ScraperAPI): uma página raspada com injeção podia
# fazê-lo vazar o token. O código troca o marcador pelo link só na saída
# (achado 2, 4ª revisão do Apolo, 09/11/2026).
LINK_PLACEHOLDER = "[LINK_PESSOAL]"


def fill_link(text: str, user: dict | None) -> str:
    """Troca o marcador pelo link real de quem vai receber. Sem link, cai no aviso
    de pedir ao admin — nunca deixa o marcador cru chegar ao usuário."""
    if LINK_PLACEHOLDER not in text:
        return text
    return text.replace(LINK_PLACEHOLDER, panel_link(user) or "(peça o link ao admin)")


def has_link(text: str) -> bool:
    """Resposta com o link pessoal sai ESCRITA, nunca em áudio: falado, são ~89
    caracteres (43 aleatórios do token) sem onde clicar, e o token iria para o TTS
    de terceiro (achado 1, 5ª revisão do Apolo)."""
    return "/me?token=" in text


def onde_ajustar(link: str | None) -> str:
    """Onde o usuário muda seções e horário do relatório. Mesmo texto no aviso do
    webhook e na regra do prompt do chat — se divergissem, o bot daria dois caminhos."""
    if link:
        return f"na sua página pessoal: {link}"
    return "na sua página pessoal (peça o link ao admin)"


def resolve_phone(token: str | None) -> str:
    if not token or not str(token).strip():
        raise HTTPException(status_code=401, detail="missing token")
    user = supabase.get_by_selflink_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="invalid or revoked token")
    return user["phone"]


def selflink_phone(token: str | None = Query(default=None)) -> str:
    return resolve_phone(token)
