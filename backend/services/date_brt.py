"""Fuso BRT (UTC-3) compartilhado por crons diários que precisam de uma
chave de data estável (ex.: id de regra "já enviado hoje").

Extraído de `investing_digest.py` em 05/09/2026 quando `soja_digest.py`
precisou do mesmo cálculo — duas cópias da mesma conta de fuso divergiriam
cedo ou tarde (DRY, ver CLAUDE.md). NÃO é a única cópia de `timezone(timedelta(hours=-3))`
que resta em `backend/` — `cron_report.py`, `send_report.py`,
`collectors/soja_disponivel.py`, `services/alert_checker.py`, `services/reporter.py`,
`services/report_engine.py` e `tools/medir_volume_alertas.py` ainda têm a conta
inline. Migrar aos poucos para cá — não faça isso de uma vez numa branch que não
é sobre isso."""
from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))


def date_brt() -> str:
    """Data de hoje em BRT, formato AAAAMMDD — usada para compor ids de
    regra "já disparada hoje"."""
    return datetime.now(BRT).strftime("%Y%m%d")
