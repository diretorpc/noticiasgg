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
        # Reaproveita o número já calculado no check `broadcasts` acima — chamar
        # count_recent_broadcasts de novo custaria uma consulta a mais por visita
        # anônima (/api/health é público, sem senha) sem nenhum ganho (achado A_dup,
        # revisão 18/08/2026). Se aquele check já falhou, não há como cross-checar.
        broadcasts_check = checks["broadcasts"]
        registro = supabase.get_news_log(hours=24, limit=1)
        if broadcasts_check.get("status") != "ok":
            checks["news_log"] = {"status": "warn",
                                   "message": "contagem de broadcasts indisponível"}
        elif registro.get("aviso"):
            # A LEITURA falhou (Supabase soluçou ao consultar news_log) — isto não
            # prova nada sobre a ESCRITA. Confundir os dois faria o dono caçar um
            # bug de "escrita silenciosa" que não existe (achado A3, revisão 18/08/2026).
            checks["news_log"] = {"status": "warn", "message": registro["aviso"],
                                   "broadcasts_24h": broadcasts_check["enviados_24h"]}
        else:
            broadcasts_24h = broadcasts_check["enviados_24h"]
            registrado = bool(registro.get("itens"))
            # Dia calmo tem ZERO dos dois — não é sintoma. Só vira erro quando um
            # alerta SAIU (broadcast) e o registro legível não acompanhou: migration
            # 007 não executada, ou log_sent_news falhando calado (achado A4).
            # `log_sent_news` engole a própria exceção de propósito (o alerta já foi
            # entregue quando ela roda) — este cross-check é o que torna a falha visível.
            silencioso = broadcasts_24h > 0 and not registrado
            # `news_log_messages` virou a fonte da verdade da ferramenta
            # `get_sent_news` quando ela filtra por destinatário — e nada vigiava
            # essa tabela. Secando ela, o agente diz "não te mandei nada" para
            # quem recebeu: mesma falha silenciosa do A4, agora com autoridade
            # pessoal (achado 12 do Apolo, 20/08/2026).
            entregas = supabase.count_recent_alert_messages(hours=24)
            sem_destinatario = broadcasts_24h > 0 and entregas == 0
            checks["news_log"] = {
                "status": "error" if (silencioso or sem_destinatario) else "ok",
                "broadcasts_24h": broadcasts_24h,
                "registrado": registrado,
                "entregas_registradas": entregas,
            }
    except Exception as e:
        # Este bloco só falha se a própria LEITURA estourar (get_news_log não
        # costuma levantar — ela mesma se blinda —, mas o defensivo continua aqui).
        # "warn", não "error": um check que não conseguiu LER não prova que a
        # ESCRITA falhou — virar "error" global por uma leitura soluçada escalava
        # a severidade errada (achado A3, revisão 18/08/2026).
        checks["news_log"] = {"status": "warn", "message": str(e)[:120]}

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


def collect_status_completo() -> dict:
    """collect_status + a medição das fontes de notícia, que custa ~9s de rede.
    Separado de propósito: `GET /api/health` é público e sem senha (main.py:59), então
    deixar a coleta lá dentro deixaria qualquer um disparar 20 buscas no seu servidor.
    Só o boletim diário chama isto — uma vez por dia, não a cada visita."""
    status = collect_status()
    try:
        from backend.collectors import news
        h = news.source_health()
        if h.get("erro"):
            check = {"status": "warn", "message": h["erro"]}
        else:
            check = {"status": "warn" if h["mortas"] else "ok",
                     "vivas": h["vivas"], "total": h["total"], "mortas": h["mortas"]}
    except Exception as e:
        check = {"status": "warn", "message": str(e)[:120]}
    status["checks"]["news_sources"] = check
    if check["status"] == "warn" and status["status"] == "ok":
        status["status"] = "warn"
    return status


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


def _line_news_log(v: dict) -> str:
    status = v.get("status")
    if status == "ok":
        return f"• Registro de notícias: OK ({v.get('broadcasts_24h', 0)} alertas/24h)"
    if status == "warn":
        # Falha de LEITURA (registro não respondeu) — não é o mesmo sintoma que
        # "escrita silenciosa" abaixo, e usar o ícone/texto errado manda o dono
        # caçar bug que não existe (achado A3, revisão 18/08/2026).
        return f"• {_ICON['warn']} Registro de notícias: {v.get('message', 'indisponível')}"
    return (f"• {_ICON['error']} Registro de notícias: {v.get('broadcasts_24h', 0)} "
            f"alertas enviados/24h, 0 registrados — escrita silenciosa")


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


def _line_news_sources(v: dict) -> str:
    if v.get("status") == "ok":
        return f"• Fontes de notícia: {v.get('vivas', 0)}/{v.get('total', 0)} entregando"
    mortas = v.get("mortas")
    if mortas:
        return (f"• {_ICON['warn']} Fontes de notícia: {v.get('vivas', 0)}/{v.get('total', 0)}"
                f" — sem item fresco: {', '.join(mortas[:5])}")
    return f"• {_ICON['warn']} Fontes de notícia: {v.get('message', 'indisponível')}"


def format_digest(status: dict) -> str:
    checks = status.get("checks", {})
    problems = [k for k, v in checks.items() if v.get("status") in ("warn", "error")]
    head = "🩺 *noticiasgg — saúde diária*"
    summary = "✅ Tudo OK" if not problems else f"⚠️ {len(problems)} problema(s)"
    lines = [head, _SEP, summary,
             _line_dedup(checks.get("dedup", {})),
             _line_broadcasts(checks.get("broadcasts", {})),
             _line_news_log(checks.get("news_log", {})),
             _line_evolution(checks.get("evolution", {})),
             _line_keys(checks.get("keys", {}))]
    if "news_sources" in checks:  # ausente quando veio do collect_status simples
        lines.append(_line_news_sources(checks["news_sources"]))
    lines.append(_line_polls(checks.get("polls", {})))
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
    status = collect_status_completo()
    whatsapp.send_message(admin, format_digest(status))
    try:
        supabase.set_alert_triggered("health_digest_daily")
    except Exception:
        pass  # envio já saiu; marcar a trava é best-effort
    return {"status": "sent", "overall": status["status"]}
