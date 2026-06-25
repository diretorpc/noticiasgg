import os
from datetime import datetime, timedelta, timezone

from backend.services import supabase, whatsapp


def _check_keys() -> dict:
    missing = [
        k for k, v in {
            "anthropic": os.getenv("ANTHROPIC_API_KEY"),
            "news_api": os.getenv("NEWS_API_KEY"),
            "scraper_api": os.getenv("SCRAPER_API_KEY"),
            "evolution": os.getenv("EVOLUTION_API_URL"),
            "supabase": os.getenv("SUPABASE_URL"),
            "fred": os.getenv("FRED_API_KEY"),
        }.items() if not v
    ]
    return {"status": "error" if missing else "ok", "faltando": missing}


def collect_status() -> dict:
    """Fonte única da verdade da saúde do sistema. Cada check é isolado: um que
    quebra vira o próprio status de erro/warn, sem derrubar os demais."""
    checks: dict = {"keys": _check_keys()}

    try:
        titles = supabase.get_recent_sent_titles(hours=24, limit=20)
        checks["dedup"] = {"status": "ok", "titulos_24h": len(titles)}
    except Exception as e:
        checks["dedup"] = {"status": "error", "message": str(e)[:120]}

    try:
        n = supabase.count_recent_broadcasts(hours=24)
        checks["broadcasts"] = {"status": "ok", "enviados_24h": n}
    except Exception as e:
        checks["broadcasts"] = {"status": "warn", "message": str(e)[:120]}

    try:
        state = whatsapp.connection_state()
        checks["evolution"] = {"status": "ok" if state == "open" else "warn", "estado": state}
    except Exception as e:
        checks["evolution"] = {"status": "warn", "message": str(e)[:120]}

    try:
        polls = supabase.get_polls()
        checks["polls"] = {"status": "ok" if polls else "warn", "institutos": len(polls) if polls else 0}
    except Exception as e:
        checks["polls"] = {"status": "error", "message": str(e)[:120]}

    has_error = any(v.get("status") == "error" for v in checks.values())
    has_warn = any(v.get("status") == "warn" for v in checks.values())
    overall = "error" if has_error else ("warn" if has_warn else "ok")
    return {"status": overall, "checks": checks, "checked_at": datetime.now(timezone.utc).isoformat()}


_ICON = {"ok": "✅", "warn": "⚠️", "error": "❌"}
_SEP = "━━━━━━━━━━━━━━"


def _line_dedup(v: dict) -> str:
    if v.get("status") == "ok":
        return f"• Dedup: ativo ({v.get('titulos_24h', 0)} títulos/24h)"
    return f"• {_ICON['error']} Dedup: {v.get('message', 'erro')}"


def _line_broadcasts(v: dict) -> str:
    if v.get("status") == "ok":
        return f"• Alertas enviados (24h): {v.get('enviados_24h', 0)}"
    return f"• {_ICON['warn']} Alertas (24h): {v.get('message', 'indisponível')}"


def _line_evolution(v: dict) -> str:
    if v.get("status") == "ok":
        return f"• Evolution: conectada ({v.get('estado', '?')})"
    return f"• {_ICON['warn']} Evolution: {v.get('estado') or v.get('message', 'desconectada')}"


def _line_keys(v: dict) -> str:
    if v.get("status") == "ok":
        return "• Chaves: OK"
    return f"• {_ICON['error']} Chaves faltando: {', '.join(v.get('faltando', []))}"


def _line_polls(v: dict) -> str:
    if v.get("status") != "error":
        return f"• Pesquisas: {v.get('institutos', 0)} institutos"
    return f"• {_ICON['error']} Pesquisas: {v.get('message', 'erro')}"


def format_digest(status: dict) -> str:
    checks = status.get("checks", {})
    problems = [k for k, v in checks.items() if v.get("status") in ("warn", "error")]
    head = "🩺 *noticiasgg — saúde diária*"
    summary = "✅ Tudo OK" if not problems else f"⚠️ {len(problems)} problema(s)"
    lines = [head, _SEP, summary,
             _line_dedup(checks.get("dedup", {})),
             _line_broadcasts(checks.get("broadcasts", {})),
             _line_evolution(checks.get("evolution", {})),
             _line_keys(checks.get("keys", {})),
             _line_polls(checks.get("polls", {}))]
    return "\n".join(lines)


_DIGEST_COOLDOWN_HOURS = 20


def _cooldown_ok(rule_id: str, hours: float) -> bool:
    """Fail-open: se não der pra ler a trava (Supabase fora), retorna True —
    o repórter de saúde não pode ser calado justamente pela falha que reporta."""
    try:
        last = supabase.get_alert_last_triggered(rule_id)
    except Exception:
        return True
    if last is None:
        return True
    return last < datetime.now(timezone.utc) - timedelta(hours=hours)


def send_daily_digest() -> dict:
    if not _cooldown_ok("health_digest_daily", _DIGEST_COOLDOWN_HOURS):
        return {"status": "skipped", "reason": "cooldown"}
    admin = os.environ.get("REPLY_TO_NUMBER") or os.environ.get("AUTHORIZED_NUMBER", "")
    if not admin:
        return {"status": "error", "reason": "no admin number"}
    status = collect_status()
    whatsapp.send_message(admin, format_digest(status))
    try:
        supabase.set_alert_triggered("health_digest_daily")
    except Exception:
        pass  # envio já saiu; marcar a trava é best-effort
    return {"status": "sent", "overall": status["status"]}
