"""Passo 4/5 da mensagem diária "Soja Disponível" (spec em ESTADO.md,
seção "Feature em andamento").

Molde copiado de `investing_digest.py`: destinatários via
`alert_checker._get_recipients()`, envio via `alert_checker._broadcast()`,
trava "já enviado hoje" via `supabase.get_alert_last_triggered`/
`set_alert_triggered`, `test_mode` restringe o alvo ao admin.

Regra do Matheus (05/09/2026): se `soja_msg.gerar()` devolver
`indisponiveis` não vazio, a mensagem NUNCA sai para a lista de alertas —
só o admin recebe um aviso, para nunca mandar praça "indisponível" ao
primo. O aviso vai DIRETO por `whatsapp.send_message` (`_avisar_admin_direto`),
não por `alert_checker.notify_admin`, porque `notify_admin` tem cooldown de 2h
compartilhado com o resto do sistema (`system_error_alert`) — um erro
qualquer do check-alerts nas 2h anteriores engoliria o aviso das 12h em
silêncio. Pela mesma razão `_avisar_admin_direto` também é usado nos outros
dois caminhos de "a mensagem de hoje não saiu" (0 destinatários, erro no
broadcast) e pela rota `cron_soja.py` quando `run()` levanta exceção fatal —
achado da revisão de 05/09/2026 (Apolo). `alert_checker.notify_admin`
continua sendo o canal certo para o resto do sistema (`check-alerts`), não
para este cron.
"""
import logging
import os

from backend.services import alert_checker, soja_msg, supabase, whatsapp
from backend.services.date_brt import date_brt

logger = logging.getLogger("noticiasgg.soja")

RULE_PREFIX = "soja_disponivel_"
_FAIL_TITLE = "cron soja com falha"
_SEP = "━━━━━━━━━━━━━━"


def _rule_id() -> str:
    return f"{RULE_PREFIX}{date_brt()}"


def _admin_phone() -> str:
    return os.environ.get("REPLY_TO_NUMBER") or os.environ.get("AUTHORIZED_NUMBER", "")


def _avisar_admin_direto(texto: str) -> None:
    """Aviso direto ao admin via `whatsapp.send_message`, FORA do cooldown de 2h
    de `alert_checker.notify_admin` (compartilhado com `check-alerts`). Usado nos
    três caminhos em que "a mensagem de hoje não saiu": mensagem segurada, 0
    destinatários e erro no broadcast — mais a exceção fatal da rota
    `cron_soja.py`. Sem admin configurado, só loga (não pode levantar)."""
    admin = _admin_phone()
    if not admin:
        logger.error("soja: sem REPLY_TO_NUMBER/AUTHORIZED_NUMBER para avisar o "
                     "admin — mensagem perdida: %s", texto[:200])
        return
    try:
        whatsapp.send_message(admin, texto)
    except Exception as e:
        logger.warning("soja: falha ao avisar admin diretamente: %s", e)


def _build_fail_message(title: str, errors: list[str]) -> str:
    msg = f"🚨 *{title}*\n{_SEP}\n" + "\n".join(f"• {e[:200]}" for e in errors[:5])
    if len(errors) > 5:
        msg += f"\n… e mais {len(errors) - 5} erro(s)"
    return msg


def _build_held_message(res: dict) -> str:
    linhas = [
        "⚠️ *Soja Disponível segurada*",
        _SEP,
        f"Indisponível: {', '.join(res['indisponiveis'])}",
    ]
    for aviso in res.get("avisos", [])[:5]:
        linhas.append(f"• {aviso[:200]}")
    linhas.append(_SEP)
    linhas.append(res["texto"])
    return "\n".join(linhas)


def run(test_mode: bool = False) -> dict:
    # Trava conferida ANTES de coletar: já enviado hoje não precisa rodar
    # `soja_msg.gerar()` (coleta de porto/praças/CBOT/dólar) para nada.
    rule_id = _rule_id()
    if not test_mode and supabase.get_alert_last_triggered(rule_id) is not None:
        return {"status": "skipped", "reason": "already_sent_today", "sent": 0}

    res = soja_msg.gerar()

    if res["indisponiveis"]:
        _avisar_admin_direto(_build_held_message(res))
        return {
            "status": "held",
            "indisponiveis": res["indisponiveis"],
            "avisos": res["avisos"],
            "sent": 0,
        }

    recipients = alert_checker._get_recipients()
    if not recipients:
        logger.error("soja: nenhum destinatário (Supabase fora ou alerts_enabled vazio)")
        _avisar_admin_direto(_build_fail_message(_FAIL_TITLE, ["soja: 0 destinatários"]))
        return {"status": "error", "detail": "0 destinatários", "recipients": 0, "sent": 0}

    if test_mode:
        admin = _admin_phone()
        if not admin:
            logger.error(
                "soja test_mode: sem REPLY_TO_NUMBER/AUTHORIZED_NUMBER, abortando "
                "para não mandar mensagem real para a lista inteira")
            return {"status": "error", "detail": "test_mode sem admin configurado", "sent": 0}
        targets = [{"phone": admin, "name": "admin"}]
    else:
        targets = recipients

    errors: list[str] = []
    sent = alert_checker._broadcast(res["texto"], targets, errors)
    if sent > 0 and not test_mode:
        try:
            supabase.set_alert_triggered(rule_id)
        except Exception as e:
            # A mensagem JÁ foi entregue — não propagar. Pior caso: reenvia
            # amanhã de manhã se a trava nunca gravar, não perde o envio de hoje.
            logger.warning("soja: falha ao gravar a trava %s (mensagem já entregue): %s",
                           rule_id, e)
    if errors:
        _avisar_admin_direto(_build_fail_message(_FAIL_TITLE, errors))

    logger.info("soja: %d recipients, %d sent", len(targets), sent)
    return {
        # 0 entregues com destinatários na lista não é "ok" — o admin já foi
        # avisado, mas quem lê o log/monitoramento precisa ver a falha.
        "status": "ok" if sent > 0 else "error",
        "test_mode": test_mode,
        "recipients": len(targets),
        "sent": sent,
        "porto_data_ref": res["porto_data_ref"],
        "cbot_simbolo": res["cbot_simbolo"],
        "avisos": res["avisos"],
    }
