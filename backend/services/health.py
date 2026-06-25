import os
from datetime import datetime, timezone

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
