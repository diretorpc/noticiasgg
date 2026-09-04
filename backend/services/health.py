import os
from datetime import datetime, timedelta, timezone

import logging

from backend.services import anthropic_status, soja_fretes, supabase, whatsapp

logger = logging.getLogger("noticiasgg")


# `keys` só sabe se a variável EXISTE. Em 31/08/2026 o saldo da conta Anthropic
# zerou e este check continuou dizendo "ok" — painel verde, agente mudo. Quem
# responde "a API atende?" é `anthropic_status.sondar`, e ela mora no
# `collect_status_completo` (com senha), não aqui.
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
            # Blindagem própria: esta consulta é NOVA e não se protege sozinha (ao
            # contrário de `get_news_log`). Dentro do `try` compartilhado, um 500 aqui
            # pulava para o `except`, que degrada tudo para "warn" — e o `error` do A4,
            # já calculado em `silencioso`, sumia. Alarme novo não pode apagar alarme
            # velho (achado 2, 3ª revisão do Apolo, 31/08/2026).
            try:
                entregas = supabase.count_recent_alert_messages(hours=24)
            except Exception as e:
                logger.warning("count_recent_alert_messages failed: %s", e)
                entregas = None
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


def _reavaliar(status: dict) -> dict:
    """Recalcula o veredito depois que um check foi acrescentado ao pacote.

    `collect_status` fecha o `status` geral com o que tinha na hora. Sem isto, um
    check acrescentado depois (a sonda da Anthropic, as fontes de notícia) aparece
    como `error` na lista e o cabeçalho continua dizendo `ok` — que é o mesmo tipo
    de mentira que a sonda veio consertar."""
    vals = status["checks"].values()
    if any(v.get("status") == "error" for v in vals):
        status["status"] = "error"
    elif any(v.get("status") == "warn" for v in vals):
        status["status"] = "warn"
    return status


def collect_status_completo() -> dict:
    """collect_status + a medição das fontes de notícia, que custa ~9s de rede.
    Separado de propósito: `GET /api/health` é público e sem senha (main.py:59), então
    deixar a coleta lá dentro deixaria qualquer um disparar 20 buscas no seu servidor.
    Só o boletim diário chama isto — uma vez por dia, não a cada visita."""
    base = collect_status()
    # Cópia rasa de propósito: os checks abaixo são ACRESCENTADOS aqui, e escrever
    # no dict recebido envenenava quem o compartilhava (nos testes, os dicts de
    # módulo `_STATUS_OK`/`_STATUS_PROBLEMA` voltavam com 3 checks a mais e
    # quebravam os testes seguintes conforme a ordem — 3ª revisão do Apolo, 04/09).
    status = {**base, "checks": {**base["checks"]}}
    # A sonda vive AQUI e não no `collect_status`, pela mesma razão que a medição
    # das fontes: `GET /api/health` é público e sem senha, e uma chamada PAGA num
    # endpoint aberto é convite para esvaziarem o saldo por você. Uma vez por dia,
    # no boletim, custa da ordem de US$ 0,000005.
    status["checks"]["anthropic"] = anthropic_status.sondar()
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
    status["checks"]["soja_fretes"] = _check_soja_fretes()
    # `_reavaliar` no lugar do `if` antigo: ele só sabia promover "ok" -> "warn"
    # para as FONTES. Com a sonda da Anthropic entrando aqui, saldo esgotado é
    # `error` e o cabeçalho continuaria dizendo "ok" — a mesma mentira que a
    # sonda veio consertar, uma linha abaixo dela.
    return _reavaliar(status)


def _check_soja_fretes() -> dict:
    """Fretes da mensagem diária 'Soja Disponível' (Porto − frete = praça).
    `soja_fretes.describe()` já não levanta sozinho, mas o try/except aqui segue
    o mesmo padrão dos vizinhos (news_sources, anthropic): um check novo não
    pode derrubar o boletim inteiro se algo mudar ali amanhã."""
    try:
        d = soja_fretes.describe()
    except Exception as e:
        return {"status": "warn", "message": str(e)[:120]}
    if d.get("erro"):
        return {"status": "warn", "message": d["erro"]}
    # Achado 1 (Apolo): valor salvo incompleto/inválido (describe() completou
    # com default e marcou "aviso") não pode ser engolido só porque updated_at
    # é recente — "envelhecido" mede IDADE, não VALIDADE do valor.
    if d.get("aviso"):
        return {"status": "warn", "message": d["aviso"], "idade_dias": d.get("idade_dias"),
                "updated_at": d.get("updated_at")}
    if not d.get("envelhecido"):
        return {"status": "ok", "idade_dias": d.get("idade_dias"), "updated_at": d.get("updated_at")}
    if not d.get("is_custom"):
        message = f"nunca salvos no painel — usando padrão {soja_fretes.descrever_defaults()}"
    else:
        idade = d.get("idade_dias")
        # Achado 2 (Apolo): updated_at nulo/ilegível -> idade_dias=None. Sem
        # este ramo a mensagem virava "editados há None dias" no WhatsApp.
        if idade is None:
            message = "data da última edição ilegível — salve de novo no painel"
        else:
            message = f"editados há {idade} dias (>60): confira com o primo"
    return {"status": "warn", "message": message, "idade_dias": d.get("idade_dias"),
            "updated_at": d.get("updated_at")}


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
    # DOIS motivos levam a `error`, e a mensagem tem que dizer QUAL: o A4 (a notícia
    # saiu e `news_log` não registrou) e o A12 (registrou, mas nenhuma ENTREGA por
    # destinatário). Um texto só, cravando "0 registrados", manda o dono caçar
    # escrita silenciosa que não existe — exatamente o que o comentário do ramo
    # `warn` acima proíbe (achado 1, 3ª revisão do Apolo, 31/08/2026).
    if not v.get("registrado"):
        return (f"• {_ICON['error']} Registro de notícias: {v.get('broadcasts_24h', 0)} "
                f"alertas enviados/24h, 0 registrados — escrita silenciosa")
    return (f"• {_ICON['error']} Registro de notícias: {v.get('broadcasts_24h', 0)} "
            f"alertas registrados/24h, {v.get('entregas_registradas', 0)} entregas por "
            f"destinatário — log_alert_messages ou o key.id da Evolution")


def _line_evolution(v: dict) -> str:
    if v.get("status") == "ok":
        return f"• Evolution: conectada ({v.get('estado', '?')})"
    return f"• {_ICON['warn']} Evolution: {v.get('estado') or v.get('message', 'desconectada')}"


def _line_keys(v: dict) -> str:
    if v.get("status") == "ok":
        return "• Chaves: OK"
    return f"• {_ICON['error']} Chaves faltando: {', '.join(v.get('faltando', []))}"


def _line_anthropic(v: dict) -> str:
    """A linha que faltava no boletim de 31/08/2026. `Chaves: OK` continua verdade
    (a variável está lá) e é justamente por isso que ela não avisa nada."""
    if v.get("status") == "ok":
        return "• Anthropic: respondendo"
    icone = _ICON["error"] if v.get("status") == "error" else _ICON["warn"]
    return f"• {icone} Anthropic: {v.get('message', 'indisponível')}"


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


def _line_soja_fretes(v: dict) -> str:
    if v.get("status") == "ok":
        return f"• Fretes Soja Disponível: OK ({v.get('idade_dias') or 0} dias)"
    return f"• {_ICON['warn']} Fretes Soja Disponível: {v.get('message', 'indisponível')}"


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
    if "anthropic" in checks:  # ausente no `collect_status` simples (endpoint público)
        lines.append(_line_anthropic(checks["anthropic"]))
    if "news_sources" in checks:  # ausente quando veio do collect_status simples
        lines.append(_line_news_sources(checks["news_sources"]))
    if "soja_fretes" in checks:  # ausente quando veio do collect_status simples
        lines.append(_line_soja_fretes(checks["soja_fretes"]))
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
