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
    de pedir ao admin — nunca deixa o marcador cru chegar ao usuário.

    Envio desligado também não leva o link: o histórico guarda o marcador cru de
    quando o prompt mandava todo mundo ao /me, e o modelo pode repeti-lo. Preenchido,
    viraria o link de uma grade que não envia nada (achado 2, revisão do Apolo)."""
    if LINK_PLACEHOLDER not in text:
        return text
    if not envio_ligado(user):
        # Cabe no meio da frase onde estava o link ("Acesse ... e mude o horário").
        return text.replace(LINK_PLACEHOLDER, f"o admin ({_ENVIO_DESLIGADO})")
    return text.replace(LINK_PLACEHOLDER, panel_link(user) or "(peça o link ao admin)")


def has_link(text: str) -> bool:
    """Resposta com o link pessoal sai ESCRITA, nunca em áudio: falado, são ~89
    caracteres (43 aleatórios do token) sem onde clicar, e o token iria para o TTS
    de terceiro (achado 1, 5ª revisão do Apolo)."""
    return "/me?token=" in text


def envio_ligado(user: dict | None) -> bool:
    """O envio do relatório diário deste usuário está ligado? Fonte única da leitura
    da chave: o cron (`cron_report.py`) só manda para quem a tem ligada, então grade
    salva com ela desligada nunca chega a ninguém. Só o admin liga/desliga."""
    return bool((user or {}).get("use_new_report_engine"))


# Sem "relatório": as frases que usam `onde_ajustar` já dizem "relatório diário" antes.
_ENVIO_DESLIGADO = "o seu envio diário está desligado"


def onde_ajustar(link: str | None, envio_ligado: bool) -> str:
    """Onde o usuário muda seções e horário do relatório. Mesmo texto no aviso do
    webhook e na regra do prompt do chat — se divergissem, o bot daria dois caminhos.

    `envio_ligado` é obrigatório, sem default: com ele desligado a grade do /me salva
    mas nada é enviado, e mandar a pessoa para lá seria prometer o que não acontece.
    Um default esconderia o chamador que esqueceu de passar. O texto desligado fecha
    as quatro frases que o usam ("mudam ...", "se ajustam ...", "ajuste ...", "se
    ajusta ...") e não leva o link."""
    if not envio_ligado:
        # Sem dois-pontos: duas frases que o usam já trazem um antes ("por aqui: ajuste ...").
        return f"com o admin, porque {_ENVIO_DESLIGADO}"
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
