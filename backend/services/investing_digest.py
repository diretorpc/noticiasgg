import logging

logger = logging.getLogger("noticiasgg.investing")

_SEP = "━━━━━━━━━━━━━━"


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
