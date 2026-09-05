import logging
import os

from backend.collectors import investing_calendar
from backend.services import alert_checker, supabase
from backend.services.date_brt import date_brt as _brt_hoje

logger = logging.getLogger("noticiasgg.investing")

_SEP = "━━━━━━━━━━━━━━"
_FAIL_TITLE = "cron investing com falha"


def _format_event(event: dict) -> str:
    lines = [f"{event['flag_emoji']} {event['name']}".strip()]
    if event.get("previous"):
        lines.append(f"Anterior = {event['previous']}")
    if event.get("forecast"):
        lines.append(f"Projeção = {event['forecast']}")
    if event.get("actual"):
        lines.append(f"Atual = {event['actual']}")
    return "\n".join(lines)


def _build_message(events: list[dict], test_mode: bool = False) -> str:
    header = "📅 *Calendário Econômico — novos dados*"
    if test_mode:
        header += " _[TESTE]_"
    blocks = [_format_event(e) for e in events]
    body = f"\n{_SEP}\n".join(blocks)
    return f"{header}\n{_SEP}\n{body}"


def _already_sent(rule_id: str) -> bool:
    return supabase.get_alert_last_triggered(rule_id) is not None


def run(test_mode: bool = False) -> dict:
    recipients = alert_checker._get_recipients()
    if not recipients:
        logger.error("investing: nenhum destinatário (Supabase fora ou alerts_enabled vazio)")
        alert_checker.notify_admin(
            ["investing: 0 destinatários"], title=_FAIL_TITLE)
        return {"status": "error", "detail": "0 destinatários",
                "recipients": 0, "events": 0, "sent": 0}

    try:
        html = investing_calendar.fetch()
        events = investing_calendar.parse(html)
    except Exception as e:
        logger.exception("investing fetch/parse failed")
        alert_checker.notify_admin([f"investing fetch/parse: {e}"], title=_FAIL_TITLE)
        return {"status": "error", "detail": str(e)}

    date_brt = _brt_hoje()
    new_events, rule_ids = [], []
    for event in events:
        rule_id = f"investing_{event['event_id']}_{date_brt}"
        if not test_mode and _already_sent(rule_id):
            continue
        new_events.append(event)
        rule_ids.append(rule_id)

    if not new_events:
        return {"status": "ok", "recipients": len(recipients), "events": 0, "sent": 0}

    if test_mode:
        admin = os.environ.get("REPLY_TO_NUMBER") or os.environ.get("AUTHORIZED_NUMBER", "")
        if not admin:
            logger.error(
                "investing test_mode: sem REPLY_TO_NUMBER/AUTHORIZED_NUMBER, abortando "
                "para não mandar mensagem real para a lista inteira")
            return {"status": "error", "detail": "test_mode sem admin configurado", "sent": 0}
        targets = [{"phone": admin, "name": "admin"}]
    else:
        targets = recipients

    errors: list[str] = []
    msg = _build_message(new_events, test_mode=test_mode)
    sent = alert_checker._broadcast(msg, targets, errors)
    if sent > 0 and not test_mode:
        for rule_id in rule_ids:
            try:
                supabase.set_alert_triggered(rule_id)
            except Exception as e:
                # Já entregue: falha aqui não pode virar reenvio do lote inteiro
                # na próxima hora (achado do Apolo, 05/09).
                logger.warning("investing: falha ao gravar a trava %s: %s", rule_id, e)
    if errors:
        alert_checker.notify_admin(errors, title=_FAIL_TITLE)
    logger.info("investing: %d new events, %d sent", len(new_events), sent)
    return {"status": "ok", "recipients": len(targets), "events": len(new_events), "sent": sent}
