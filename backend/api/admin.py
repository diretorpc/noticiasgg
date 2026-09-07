import os

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictFloat, StrictInt

from backend.services import reporter, auth, supabase, report_engine, schedules, config, report_prompts, soja_fretes, soja_msg
from backend.services import media as media_service
from backend.collectors import news

router = APIRouter()


@router.get("/api/admin/agent-config")
def get_agent_config(user: dict = Depends(auth.require_admin)) -> dict:
    """Snapshot read-only da config do agente. Exige auth. Sem secrets."""
    return {
        "agent": reporter.describe_config(),
        "audio": media_service.describe_config(),
        "news": news.describe_config(),
    }


@router.get("/api/admin/newsapi-sources")
def get_newsapi_sources(user: dict = Depends(auth.require_admin)) -> dict:
    """Lista as fontes disponíveis na NewsAPI (id/name/category) para o painel.
    Busca server-side para não expor a NEWS_API_KEY no browser."""
    api_key = os.environ.get("NEWS_API_KEY", "")
    if not api_key:
        return {"sources": []}
    # Degrada para lista vazia se a NewsAPI falhar (429/timeout) — o painel
    # continua editável (RSS, queries) mesmo sem o picker de fontes.
    try:
        resp = httpx.get(
            "https://newsapi.org/v2/top-headlines/sources",
            params={"apiKey": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json().get("sources", [])
    except Exception:
        return {"sources": []}
    sources = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "category": s.get("category"),
            "language": s.get("language"),
            "country": s.get("country"),
        }
        for s in raw
    ]
    return {"sources": sources}


class RssValidateBody(BaseModel):
    url: str


@router.post("/api/admin/validate-rss")
def validate_rss(body: RssValidateBody, user: dict = Depends(auth.require_admin)) -> dict:
    """Valida na hora uma URL de RSS/Atom para o painel (parse + nº de itens)."""
    return news.validate_feed(body.url)


@router.get("/api/admin/users")
def list_users(user: dict = Depends(auth.require_admin)) -> dict:
    """Lista usuários autorizados com suas preferências (para o painel)."""
    out = []
    for u in supabase.list_authorized():
        prefs = supabase.get_preferences(u["phone"])
        out.append({
            "phone": u["phone"],
            "name": u.get("name"),
            "preferences": {
                "sections": prefs.get("sections"),
                "report_time": prefs.get("report_time"),
                "audio_for_text": prefs.get("audio_for_text"),
                "audio_for_media": prefs.get("audio_for_media"),
                "tts_voice": prefs.get("tts_voice"),
                "tts_speed": prefs.get("tts_speed"),
            } if prefs else None,
        })
    return {"users": out}


class UserPrefsBody(BaseModel):
    phone: str
    sections: dict | None = None
    report_time: str | None = None
    audio_for_text: bool | None = None
    audio_for_media: bool | None = None
    tts_voice: str | None = None
    tts_speed: float | None = None


@router.post("/api/admin/user-prefs")
def save_user_prefs(body: UserPrefsBody, user: dict = Depends(auth.require_admin)) -> dict:
    """Salva as preferências de um usuário (edição pelo painel)."""
    supabase.save_preferences(
        body.phone,
        sections=body.sections,
        report_time=body.report_time,
        audio_for_text=body.audio_for_text,
        audio_for_media=body.audio_for_media,
        tts_voice=body.tts_voice,
        tts_speed=body.tts_speed,
    )
    return {"ok": True}


@router.delete("/api/admin/user-prefs/{phone}")
def reset_user_prefs(phone: str, user: dict = Depends(auth.require_admin)) -> dict:
    """Reseta as preferências de um usuário (volta aos defaults)."""
    supabase.delete_preferences(phone)
    return {"ok": True}


class PreviewReportBody(BaseModel):
    phone: str
    sections: dict | None = None


@router.post("/api/admin/preview-report")
def preview_report(body: PreviewReportBody, user: dict = Depends(auth.require_admin)) -> dict:
    """Gera o relatório do motor novo (lista de mensagens) SEM enviar pro WhatsApp.
    Usado para comparar o layout lado a lado com o n8n."""
    target = supabase.get_authorized_by_phone(body.phone) or {"phone": body.phone, "name": ""}
    messages = report_engine.generate_sections(body.sections, target)
    return {"messages": messages}


class ScheduleBody(BaseModel):
    use_new_engine: bool = False
    schedule: dict = {}


@router.get("/api/admin/schedules/{phone}")
def get_schedules(phone: str, user: dict = Depends(auth.require_admin)) -> dict:
    """Grade de agendamento (motor novo) + flag de opt-in de um usuário."""
    rows = schedules.get_for_phone(phone)
    enabled = schedules.phones_with_engine_enabled()
    return {"use_new_engine": phone in enabled, "schedule": schedules.rows_to_grid(rows)}


@router.put("/api/admin/schedules/{phone}")
def put_schedules(phone: str, body: ScheduleBody,
                  user: dict = Depends(auth.require_admin)) -> dict:
    """Substitui a grade do usuário e seta a flag do motor novo."""
    try:
        rows = schedules.grid_to_rows(phone, body.schedule)
    except (ValueError, TypeError, AttributeError) as e:
        raise HTTPException(status_code=422, detail=f"grade inválida: {e}")
    schedules.replace_for_phone(phone, rows)
    schedules.set_engine_flag(phone, body.use_new_engine)
    return {"ok": True}


@router.get("/api/admin/report-prompts")
def get_report_prompts(user: dict = Depends(auth.require_admin)) -> dict:
    """Os 6 prompts de seção: valor efetivo, se é custom e o default."""
    return {"prompts": report_prompts.describe_prompts()}


class ReportPromptBody(BaseModel):
    prompt: str


@router.put("/api/admin/report-prompts/{section}")
def put_report_prompt(section: str, body: ReportPromptBody,
                      user: dict = Depends(auth.require_admin)) -> dict:
    if section not in report_prompts.SECTIONS:
        raise HTTPException(status_code=400, detail="seção inválida")
    supabase.upsert_config(report_prompts._CONFIG_KEY[section], body.prompt)
    config.clear_cache()
    return {"ok": True, "is_custom": True}


@router.delete("/api/admin/report-prompts/{section}")
def delete_report_prompt(section: str,
                         user: dict = Depends(auth.require_admin)) -> dict:
    if section not in report_prompts.SECTIONS:
        raise HTTPException(status_code=400, detail="seção inválida")
    supabase.delete_config(report_prompts._CONFIG_KEY[section])
    config.clear_cache()
    return {"ok": True, "is_custom": False}


class PreviewSectionBody(BaseModel):
    section: str
    prompt: str


@router.post("/api/admin/preview-section")
def preview_section(body: PreviewSectionBody,
                    user: dict = Depends(auth.require_admin)) -> dict:
    if body.section not in report_prompts.SECTIONS:
        raise HTTPException(status_code=400, detail="seção inválida")
    text = report_engine.preview_section(body.section, body.prompt)
    return {"text": text}


@router.get("/api/admin/soja-fretes")
def get_soja_fretes(user: dict = Depends(auth.require_admin)) -> dict:
    """Fretes da mensagem diária 'Soja Disponível': valor efetivo + metadados
    de edição (para o painel decidir se mostra o selo de envelhecido)."""
    return soja_fretes.describe()


class SojaFretesBody(BaseModel):
    # StrictFloat | StrictInt (não `float` puro): o Pydantic padrão coage
    # bool -> float ANTES de `soja_fretes.validar` rodar (bool é subclasse de
    # int em Python) — {"pontal": true} virava 200 com 1.0 (achado 4, Apolo).
    # `validar` continua a fonte da faixa/negativo/NaN; isto só barra o tipo.
    pontal: StrictFloat | StrictInt
    uberaba: StrictFloat | StrictInt
    canarana: StrictFloat | StrictInt


@router.put("/api/admin/soja-fretes")
def put_soja_fretes(body: SojaFretesBody,
                    user: dict = Depends(auth.require_admin)) -> dict:
    try:
        fretes = soja_fretes.validar(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    supabase.upsert_config(soja_fretes.CONFIG_KEY, fretes, updated_by=user.get("email"))
    config.clear_cache()
    return soja_fretes.describe()


@router.delete("/api/admin/soja-fretes")
def delete_soja_fretes(user: dict = Depends(auth.require_admin)) -> dict:
    """Volta ao default (9/12/27), apagando a linha em agent_config."""
    supabase.delete_config(soja_fretes.CONFIG_KEY)
    config.clear_cache()
    return soja_fretes.describe()


@router.get("/api/admin/soja-preview")
def get_soja_preview(user: dict = Depends(auth.require_admin)) -> dict:
    """Prévia da mensagem diária 'Soja Disponível' com os dados AO VIVO
    (coleta + fretes) — mesma montagem que o cron das 12h vai enviar."""
    return soja_msg.gerar()


@router.post("/api/admin/selflink/{phone}")
def generate_selflink(phone: str, user: dict = Depends(auth.require_admin)) -> dict:
    if not supabase.get_authorized_by_phone(phone):
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    token = supabase.set_selflink_token(phone)
    base = os.environ.get("PANEL_BASE_URL", "https://noticiasgg-painel.vercel.app").rstrip("/")
    return {"url": f"{base}/me?token={token}", "token": token}


@router.delete("/api/admin/selflink/{phone}")
def revoke_selflink(phone: str, user: dict = Depends(auth.require_admin)) -> dict:
    supabase.clear_selflink_token(phone)
    return {"ok": True}
