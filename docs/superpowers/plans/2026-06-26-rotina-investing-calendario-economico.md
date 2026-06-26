# Rotina Investing — Calendário Econômico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cron de hora em hora que envia no WhatsApp os indicadores de alto impacto do calendário econômico do br.investing.com assim que o valor "Atual" é divulgado.

**Architecture:** Coletor (`fetch` + `parse`) sem efeitos colaterais → serviço (`run`) que deduplica via `system_alert_state`, monta uma mensagem agrupada e faz broadcast → router fino de cron protegido por `check_cron_secret`. Segue os padrões existentes de `check_alerts.py` / `_check_eia`. Sem chamada de LLM.

**Tech Stack:** Python 3.12, FastAPI, httpx, ScraperAPI, Supabase (PostgREST), Evolution API (WhatsApp), Vercel Cron.

Spec: [docs/superpowers/specs/2026-06-26-rotina-investing-calendario-economico-design.md](../specs/2026-06-26-rotina-investing-calendario-economico-design.md) — **ler a seção "Atualização pós-spike"**: a fonte migrou para Next.js; os eventos saem do JSON `__NEXT_DATA__`, não de HTML/tabela.

## Global Constraints

- Python: snake_case funções/variáveis, PascalCase classes.
- Commits: mensagens em inglês, imperativas. Terminar com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Sem comentários desnecessários — só quando o "porquê" não é óbvio.
- YAGNI: nada de toggle no painel, nada de média/baixa relevância, nada de filtro por país.
- Dedup via tabela existente `system_alert_state` (`rule_id`, `last_triggered_at`).
- Destinatários: `authorized_users` com `alerts_enabled=true` (reuso de `alert_checker._get_recipients`).
- Valores numéricos: passar as strings cruas do br.investing (já em PT) — sem reformatação de locale.
- Relevância: apenas alto impacto (`importance == "3"`). Gatilho: valor "Atual" preenchido.
- Cron: `0 * * * *` (hora em hora, 24/7).
- Rodar testes: `pytest backend/tests/ -v`.

---

### Task 1: Spike de aquisição — ✅ FEITA INLINE (2026-06-26)

Concluída pelo controller antes do restante. Resultado registrado na seção "Atualização pós-spike" do spec. Resumo do que foi descoberto e que as Tasks 3/4 assumem:

- O br.investing.com é **Next.js (SSR)**. A estrutura antiga (`getCalendarFilteredData`, tabela `#economicCalendarData`, `js-event-item`) **não existe mais**.
- GET simples da página `https://br.investing.com/economic-calendar/` via ScraperAPI (sem `render`/`premium`) retorna 200 com o conteúdo completo.
- Os eventos vivem no `<script id="__NEXT_DATA__">` em
  `props.pageProps.state.economicCalendarStore.calendarEventsByDate` (dict por data → lista).
- Campos por evento: `eventId` (int), `importance` (`"1"|"2"|"3"`), `actual`/`forecast`/`previous`
  (strings PT), `event`, `period` (já com parênteses, ex. `"(Mai)"`), `country` (PT),
  `currencyFlag` (ISO-2, ex. `"BR"`).
- Validação real: 51 eventos no dia, 3 de alta relevância, 2 já com `actual`.

Nada a commitar (spike exploratório).

---

### Task 2: Generalizar `notify_admin(title=...)`

Permitir que a rotina investing envie avisos de falha ao admin com título próprio, sem duplicar a função.

**Files:**
- Modify: `backend/services/alert_checker.py:415-440`
- Test: `backend/tests/test_alert_checker_notify.py`

**Interfaces:**
- Produces: `alert_checker.notify_admin(errors: list[str], title: str = "check-alerts com falhas") -> None`

- [ ] **Step 1: Escrever o teste falhando** em `backend/tests/test_alert_checker_notify.py`:

```python
from backend.services import alert_checker, supabase, whatsapp


def test_notify_admin_uses_custom_title(monkeypatch):
    monkeypatch.setenv("AUTHORIZED_NUMBER", "553400000000")
    monkeypatch.setattr(supabase, "get_alert_last_triggered", lambda rule_id: None)
    monkeypatch.setattr(supabase, "set_alert_triggered", lambda rule_id: None)
    captured = {}
    monkeypatch.setattr(whatsapp, "send_message",
                        lambda number, text: captured.update(number=number, text=text) or {})

    alert_checker.notify_admin(["algo quebrou"], title="cron investing com falha")

    assert "cron investing com falha" in captured["text"]
    assert "algo quebrou" in captured["text"]
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `pytest backend/tests/test_alert_checker_notify.py -v`
Esperado: FAIL — `notify_admin()` ainda não aceita `title` (TypeError) ou o título antigo não bate.

- [ ] **Step 3: Implementar a mudança** em `backend/services/alert_checker.py`. Alterar a assinatura e o cabeçalho da mensagem:

```python
def notify_admin(errors: list[str], title: str = "check-alerts com falhas") -> None:
    """Avisa o admin via WhatsApp quando o sistema falha — o sistema reporta a própria doença.
    Cooldown de 2h para não virar spam de erro a cada execução do cron."""
    admin = os.environ.get("REPLY_TO_NUMBER") or os.environ.get("AUTHORIZED_NUMBER", "")
    if not admin or not errors:
        return
    try:
        if not _cooldown_ok("system_error_alert", _ERROR_NOTIFY_COOLDOWN_HOURS):
            logger.info("admin notify: cooldown active, skipping (%d errors)", len(errors))
            return
    except Exception as e:
        logger.warning("admin notify: cooldown check failed (%s), sending anyway", e)
    msg = (
        f"🚨 *{title}*\n"
        "━━━━━━━━━━━━━━\n"
        + "\n".join(f"• {e[:200]}" for e in errors[:5])
    )
    if len(errors) > 5:
        msg += f"\n… e mais {len(errors) - 5} erro(s)"
    try:
        whatsapp.send_message(admin, msg)
        supabase.set_alert_triggered("system_error_alert")
        logger.info("admin notified of %d error(s)", len(errors))
    except Exception as e:
        logger.error("admin notify failed: %s", e)
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `pytest backend/tests/test_alert_checker_notify.py -v`
Esperado: PASS

- [ ] **Step 5: Garantir que não quebrou os chamadores existentes**

Run: `pytest backend/tests/ -v -k "alert or check"`
Esperado: PASS (chamadas antigas `notify_admin([...])` continuam válidas pelo default).

- [ ] **Step 6: Commit**

```bash
git add backend/services/alert_checker.py backend/tests/test_alert_checker_notify.py
git commit -m "refactor: parametrize notify_admin title for reuse

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Parser do calendário (`parse`)

Núcleo da feature. Recebe o HTML cru da página e devolve só os eventos de alto impacto com "Atual" já divulgado, lendo o JSON embutido `__NEXT_DATA__`. Distingue "store presente mas sem evento filtrado" (normal, lista vazia) de "store ausente / `__NEXT_DATA__` ausente" (quebra/bloqueio → `ValueError`).

**Files:**
- Create: `backend/collectors/investing_calendar.py`
- Create (fixture): `backend/tests/fixtures/investing_next_data.html`
- Test: `backend/tests/test_investing_calendar.py`

**Interfaces:**
- Produces:
  - `investing_calendar.parse(html: str) -> list[dict]` — cada dict:
    `{"event_id": str, "country": str, "flag_emoji": str, "name": str, "importance": int, "previous": str, "forecast": str, "actual": str}`
  - Levanta `ValueError` quando o corpo não é um calendário reconhecível.

- [ ] **Step 1: Criar o fixture** em `backend/tests/fixtures/investing_next_data.html` (página mínima com `__NEXT_DATA__` e 4 eventos representativos: alta+atual, alta sem atual, baixa+atual, alta sem projeção). Salvar como **UTF-8**:

```html
<!doctype html><html><body><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"state":{"economicCalendarStore":{"calendarEventsByDate":{"2026-06-26":[{"eventId":862,"importance":"3","country":"Brazil","currencyFlag":"BR","event":"Investimento Estrangeiro Direto (USD)","period":"(Mai)","previous":"8,91B","forecast":"5,75B","actual":"7,97B"},{"eventId":411,"importance":"3","country":"Brazil","currencyFlag":"BR","event":"Taxa de Desemprego no Brasil","period":"(Mai)","previous":"5,8%","forecast":"5,6%","actual":""},{"eventId":999,"importance":"1","country":"Singapore","currencyFlag":"SG","event":"Produção Industrial","period":"(Mai)","previous":"16,5%","forecast":"17,0%","actual":"13,0%"},{"eventId":555,"importance":"3","country":"Spain","currencyFlag":"ES","event":"PIB da Espanha (trimestral)","period":"(Q1)","previous":"0,8%","forecast":"","actual":"0,6%"}]}}}}}}</script></body></html>
```

- [ ] **Step 2: Escrever os testes falhando** em `backend/tests/test_investing_calendar.py`:

```python
import json
from pathlib import Path

import pytest

from backend.collectors import investing_calendar

FIXTURES = Path(__file__).parent / "fixtures"


def _page():
    return (FIXTURES / "investing_next_data.html").read_text(encoding="utf-8")


def test_parse_keeps_only_high_impact_with_actual():
    events = investing_calendar.parse(_page())
    names = [e["name"] for e in events]
    # FDI (alta+atual) e PIB Espanha (alta+atual) entram;
    # Desemprego (alta, sem atual) e Produção Industrial (baixa) ficam de fora.
    assert names == [
        "Investimento Estrangeiro Direto (USD) (Mai)",
        "PIB da Espanha (trimestral) (Q1)",
    ]


def test_parse_extracts_fields_and_flag():
    events = investing_calendar.parse(_page())
    fdi = events[0]
    assert fdi["event_id"] == "862"
    assert fdi["flag_emoji"] == "🇧🇷"
    assert fdi["importance"] == 3
    assert fdi["previous"] == "8,91B"
    assert fdi["forecast"] == "5,75B"
    assert fdi["actual"] == "7,97B"


def test_parse_blank_forecast_is_empty_string():
    events = investing_calendar.parse(_page())
    espanha = events[1]
    assert espanha["flag_emoji"] == "🇪🇸"
    assert espanha["forecast"] == ""
    assert espanha["actual"] == "0,6%"


def test_parse_missing_next_data_raises():
    with pytest.raises(ValueError):
        investing_calendar.parse("<html><body>Just a moment... Cloudflare</body></html>")


def test_parse_next_data_without_store_raises():
    body = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"state":{}}}}</script>'
    with pytest.raises(ValueError):
        investing_calendar.parse(body)


def test_parse_empty_calendar_is_normal_empty_list():
    body = ('<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"state":{"economicCalendarStore":{"calendarEventsByDate":{"2026-06-26":[]}}}}}}'
            '</script>')
    assert investing_calendar.parse(body) == []
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `pytest backend/tests/test_investing_calendar.py -v`
Esperado: FAIL — módulo `investing_calendar` sem `parse`.

- [ ] **Step 4: Implementar `parse` (+ helpers)** em `backend/collectors/investing_calendar.py`:

```python
import json
import logging
import re

logger = logging.getLogger("noticiasgg.investing")

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def _flag_emoji(country_code: str) -> str:
    cc = (country_code or "").strip().upper()
    if len(cc) != 2 or not cc.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in cc)


def _next_data(html: str) -> dict:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("investing: __NEXT_DATA__ não encontrado (bloqueio ou layout mudou)")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"investing: __NEXT_DATA__ inválido: {e}") from e


def _events_by_date(html: str) -> dict:
    data = _next_data(html)
    try:
        return data["props"]["pageProps"]["state"]["economicCalendarStore"]["calendarEventsByDate"]
    except (KeyError, TypeError) as e:
        raise ValueError(f"investing: estrutura do calendário ausente: {e}") from e


def parse(html: str) -> list[dict]:
    by_date = _events_by_date(html)
    events: list[dict] = []
    for day_events in by_date.values():
        for e in day_events:
            actual = (e.get("actual") or "").strip()
            if str(e.get("importance")) != "3" or not actual:
                continue
            name = (e.get("event") or "").strip()
            period = (e.get("period") or "").strip()
            if period:
                name = f"{name} {period}"
            events.append({
                "event_id": str(e.get("eventId")),
                "country": (e.get("country") or "").strip(),
                "flag_emoji": _flag_emoji(e.get("currencyFlag")),
                "name": name,
                "importance": 3,
                "previous": (e.get("previous") or "").strip(),
                "forecast": (e.get("forecast") or "").strip(),
                "actual": actual,
            })
    return events
```

- [ ] **Step 5: Rodar e ver passar**

Run: `pytest backend/tests/test_investing_calendar.py -v`
Esperado: PASS (6 testes)

- [ ] **Step 6: Commit**

```bash
git add backend/collectors/investing_calendar.py backend/tests/test_investing_calendar.py backend/tests/fixtures/investing_next_data.html
git commit -m "feat: parse investing economic-calendar events from __NEXT_DATA__

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Busca via ScraperAPI (`fetch`)

Adiciona a aquisição: GET da página do calendário via ScraperAPI (modo simples — o SSR já entrega o `__NEXT_DATA__`).

**Files:**
- Modify: `backend/collectors/investing_calendar.py` (adicionar `fetch` e constantes no topo)
- Test: `backend/tests/test_investing_fetch.py`

**Interfaces:**
- Consumes: `parse(html)` da Task 3.
- Produces: `investing_calendar.fetch() -> str` (HTML cru pronto pro `parse`). Levanta `ValueError` se `SCRAPER_API_KEY` ausente.

- [ ] **Step 1: Escrever o teste de integração** (pulado sem chave) em `backend/tests/test_investing_fetch.py`:

```python
import os

import pytest

from backend.collectors import investing_calendar


@pytest.mark.skipif(not os.getenv("SCRAPER_API_KEY"), reason="SCRAPER_API_KEY não configurada")
def test_fetch_returns_parseable_calendar():
    html = investing_calendar.fetch()
    # Não deve levantar: ou tem eventos de alto impacto agora, ou lista vazia (normal).
    events = investing_calendar.parse(html)
    assert isinstance(events, list)


def test_fetch_without_key_raises(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    with pytest.raises(ValueError):
        investing_calendar.fetch()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_investing_fetch.py -v`
Esperado: FAIL — `fetch` não existe.

- [ ] **Step 3: Implementar `fetch`** no topo de `backend/collectors/investing_calendar.py` (adicionar `import os` e `import httpx` aos imports):

```python
import os

import httpx

_SCRAPER_URL = "https://api.scraperapi.com/"
_PAGE_URL = "https://br.investing.com/economic-calendar/"


def fetch() -> str:
    key = os.environ.get("SCRAPER_API_KEY", "")
    if not key:
        raise ValueError("SCRAPER_API_KEY não configurada")
    with httpx.Client(timeout=60) as client:
        r = client.get(_SCRAPER_URL, params={"api_key": key, "url": _PAGE_URL})
        r.raise_for_status()
        return r.text
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest backend/tests/test_investing_fetch.py -v`
Esperado: PASS (integração roda se houver `SCRAPER_API_KEY` no ambiente — o `.env` do projeto tem; senão é skipped; o teste sem-chave passa).

- [ ] **Step 5: Commit**

```bash
git add backend/collectors/investing_calendar.py backend/tests/test_investing_fetch.py
git commit -m "feat: fetch investing economic-calendar page via ScraperAPI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Formatação da mensagem

Funções puras que montam o bloco por indicador e a mensagem agrupada, fiéis ao formato pedido.

**Files:**
- Create: `backend/services/investing_digest.py`
- Test: `backend/tests/test_investing_digest_format.py`

**Interfaces:**
- Produces:
  - `investing_digest._format_event(event: dict) -> str`
  - `investing_digest._build_message(events: list[dict], test_mode: bool = False) -> str`

- [ ] **Step 1: Escrever os testes falhando** em `backend/tests/test_investing_digest_format.py`:

```python
from backend.services import investing_digest


def _event(**over):
    base = {"event_id": "1", "country": "Spain", "flag_emoji": "🇪🇸",
            "name": "PIB da Espanha (trimestral) (Q1)", "importance": 3,
            "previous": "0,8%", "forecast": "0,6%", "actual": "0,6%"}
    base.update(over)
    return base


def test_format_event_matches_expected_layout():
    out = investing_digest._format_event(_event())
    assert out == (
        "🇪🇸 PIB da Espanha (trimestral) (Q1)\n"
        "Anterior = 0,8%\n"
        "Projeção = 0,6%\n"
        "Atual = 0,6%"
    )


def test_format_event_omits_blank_forecast():
    out = investing_digest._format_event(_event(forecast=""))
    assert "Projeção" not in out
    assert out.endswith("Atual = 0,6%")


def test_build_message_groups_with_separators():
    msg = investing_digest._build_message([_event(), _event(name="Outro", flag_emoji="🇺🇸")])
    assert msg.startswith("📅 *Calendário Econômico — novos dados*")
    assert msg.count("━━━━━━━━━━━━━━") == 2  # divisória antes de cada bloco
    assert "🇪🇸 PIB da Espanha" in msg
    assert "🇺🇸 Outro" in msg


def test_build_message_test_mode_marks_header():
    msg = investing_digest._build_message([_event()], test_mode=True)
    assert "[TESTE]" in msg.splitlines()[0]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_investing_digest_format.py -v`
Esperado: FAIL — módulo sem essas funções.

- [ ] **Step 3: Implementar as funções** em `backend/services/investing_digest.py`:

```python
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest backend/tests/test_investing_digest_format.py -v`
Esperado: PASS (4 testes)

- [ ] **Step 5: Commit**

```bash
git add backend/services/investing_digest.py backend/tests/test_investing_digest_format.py
git commit -m "feat: format grouped investing calendar message

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Orquestração (`run`) com dedup

Junta tudo: busca, parseia, deduplica por `(event_id, data_BRT)`, monta a mensagem agrupada, faz broadcast, marca como enviado e notifica admin em falha.

**Files:**
- Modify: `backend/services/investing_digest.py`
- Test: `backend/tests/test_investing_digest_run.py`

**Interfaces:**
- Consumes: `investing_calendar.fetch`/`parse`; `alert_checker._get_recipients`/`_broadcast`/`notify_admin`; `supabase.get_alert_last_triggered`/`set_alert_triggered`.
- Produces: `investing_digest.run(test_mode: bool = False) -> dict` com chaves `status`, `recipients`, `events`, `sent`.

- [ ] **Step 1: Escrever os testes falhando** em `backend/tests/test_investing_digest_run.py`:

```python
from pathlib import Path

from backend.collectors import investing_calendar
from backend.services import investing_digest, alert_checker, supabase

FIXTURES = Path(__file__).parent / "fixtures"


def _page():
    return (FIXTURES / "investing_next_data.html").read_text(encoding="utf-8")


def _wire(monkeypatch, sent_store, already=None):
    already = already or set()
    monkeypatch.setattr(investing_calendar, "fetch", lambda: _page())
    monkeypatch.setattr(alert_checker, "_get_recipients",
                        lambda: [{"phone": "553400000000", "name": "Chefe"}])

    def fake_broadcast(msg, recipients, errors=None):
        sent_store.append(msg)
        return len(recipients)
    monkeypatch.setattr(alert_checker, "_broadcast", fake_broadcast)

    triggered = set(already)
    monkeypatch.setattr(supabase, "get_alert_last_triggered",
                        lambda rid: object() if rid in triggered else None)
    monkeypatch.setattr(supabase, "set_alert_triggered", lambda rid: triggered.add(rid))
    return triggered


def test_run_sends_grouped_message_for_new_events(monkeypatch):
    sent = []
    _wire(monkeypatch, sent)
    result = investing_digest.run()
    assert result["status"] == "ok"
    assert result["events"] == 2  # FDI + PIB Espanha
    assert result["sent"] == 1
    assert len(sent) == 1
    assert "🇧🇷 Investimento Estrangeiro Direto" in sent[0]
    assert "PIB da Espanha (trimestral) (Q1)" in sent[0]


def test_run_dedups_on_second_call(monkeypatch):
    sent = []
    _wire(monkeypatch, sent)
    investing_digest.run()           # primeira vez: envia e marca
    sent.clear()
    result = investing_digest.run()  # segunda vez: tudo já enviado
    assert result["events"] == 0
    assert result["sent"] == 0
    assert sent == []


def test_run_reports_error_on_unrecognized_body(monkeypatch):
    notified = []
    monkeypatch.setattr(investing_calendar, "fetch", lambda: "<html>cloudflare block</html>")
    monkeypatch.setattr(alert_checker, "_get_recipients",
                        lambda: [{"phone": "553400000000", "name": "Chefe"}])
    monkeypatch.setattr(alert_checker, "notify_admin",
                        lambda errors, title="x": notified.append((errors, title)))
    result = investing_digest.run()
    assert result["status"] == "error"
    assert notified  # admin avisado da quebra
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_investing_digest_run.py -v`
Esperado: FAIL — `run` não existe.

- [ ] **Step 3: Implementar `run`** em `backend/services/investing_digest.py` (adicionar imports e a função):

```python
import os
from datetime import datetime, timedelta, timezone

from backend.collectors import investing_calendar
from backend.services import alert_checker, supabase

_FAIL_TITLE = "cron investing com falha"


def _already_sent(rule_id: str) -> bool:
    return supabase.get_alert_last_triggered(rule_id) is not None


def _date_brt() -> str:
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%Y%m%d")


def run(test_mode: bool = False) -> dict:
    recipients = alert_checker._get_recipients()
    if not recipients:
        logger.error("investing: nenhum destinatário (Supabase fora ou alerts_enabled vazio)")
        alert_checker.notify_admin(
            ["investing: 0 destinatários"], title=_FAIL_TITLE)
        return {"status": "ok", "recipients": 0, "events": 0, "sent": 0}

    try:
        html = investing_calendar.fetch()
        events = investing_calendar.parse(html)
    except Exception as e:
        logger.exception("investing fetch/parse failed")
        alert_checker.notify_admin([f"investing fetch/parse: {e}"], title=_FAIL_TITLE)
        return {"status": "error", "detail": str(e)}

    date_brt = _date_brt()
    new_events, rule_ids = [], []
    for event in events:
        rule_id = f"investing_{event['event_id']}_{date_brt}"
        if not test_mode and _already_sent(rule_id):
            continue
        new_events.append(event)
        rule_ids.append(rule_id)

    if not new_events:
        return {"status": "ok", "recipients": len(recipients), "events": 0, "sent": 0}

    targets = recipients
    if test_mode:
        admin = os.environ.get("REPLY_TO_NUMBER") or os.environ.get("AUTHORIZED_NUMBER", "")
        if admin:
            targets = [{"phone": admin, "name": "admin"}]

    errors: list[str] = []
    msg = _build_message(new_events, test_mode=test_mode)
    sent = alert_checker._broadcast(msg, targets, errors)
    if sent > 0 and not test_mode:
        for rule_id in rule_ids:
            supabase.set_alert_triggered(rule_id)
    if errors:
        alert_checker.notify_admin(errors, title=_FAIL_TITLE)
    logger.info("investing: %d new events, %d sent", len(new_events), sent)
    return {"status": "ok", "recipients": len(targets), "events": len(new_events), "sent": sent}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest backend/tests/test_investing_digest_run.py -v`
Esperado: PASS (3 testes)

- [ ] **Step 5: Rodar a suíte do módulo inteira**

Run: `pytest backend/tests/ -v -k investing`
Esperado: PASS (todos os testes investing)

- [ ] **Step 6: Commit**

```bash
git add backend/services/investing_digest.py backend/tests/test_investing_digest_run.py
git commit -m "feat: orchestrate investing digest run with dedup

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Router de cron + registro + agendamento

Expõe `GET /api/cron/investing`, registra no app e agenda na Vercel.

**Files:**
- Create: `backend/api/cron_investing.py`
- Modify: `backend/api/main.py:13` (import) e `backend/api/main.py:37-43` (include_router)
- Modify: `vercel.json:15-19` (crons)
- Test: `backend/tests/test_cron_investing_route.py`

**Interfaces:**
- Consumes: `check_cron_secret`; `investing_digest.run`; `alert_checker.notify_admin`.
- Produces: rota `GET /api/cron/investing?test=<bool>`.

- [ ] **Step 1: Escrever o teste falhando** em `backend/tests/test_cron_investing_route.py`:

```python
from fastapi.testclient import TestClient

from backend.api import main
from backend.services import investing_digest


def _client():
    return TestClient(main.app)


def test_cron_investing_requires_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    r = _client().get("/api/cron/investing")
    assert r.status_code == 401


def test_cron_investing_runs_with_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cr3t")
    monkeypatch.setattr(investing_digest, "run",
                        lambda test_mode=False: {"status": "ok", "events": 0, "sent": 0})
    r = _client().get("/api/cron/investing", headers={"x-cron-secret": "s3cr3t"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_cron_investing_route.py -v`
Esperado: FAIL — rota inexistente (404).

- [ ] **Step 3: Criar o router** em `backend/api/cron_investing.py`:

```python
import logging

from fastapi import APIRouter, Request

from backend.api.cron_auth import check_cron_secret
from backend.services import investing_digest, alert_checker

logger = logging.getLogger("noticiasgg")
router = APIRouter()


@router.get("/api/cron/investing")
async def cron_investing(request: Request, test: bool = False):
    check_cron_secret(request)
    try:
        return investing_digest.run(test_mode=test)
    except Exception as e:
        logger.exception("cron_investing failed")
        try:
            alert_checker.notify_admin([f"fatal: {e}"], title="cron investing com falha")
        except Exception:
            logger.exception("admin notify failed")
        return {"status": "error", "detail": str(e)}
```

- [ ] **Step 4: Registrar no app.** Em `backend/api/main.py`, adicionar `cron_investing` ao import da linha 13:

```python
from backend.api import send_report, cron_report, check_alerts, admin, me, health_digest, cron_investing
```

E adicionar o include perto da linha 43 (junto aos outros routers):

```python
app.include_router(cron_investing.router)
```

- [ ] **Step 5: Agendar na Vercel.** Em `vercel.json`, adicionar ao array `crons`:

```json
{ "path": "/api/cron/investing", "schedule": "0 * * * *" }
```

Resultado final do bloco `crons`:

```json
"crons": [
  { "path": "/api/cron/report",  "schedule": "0 * * * *" },
  { "path": "/api/check-alerts", "schedule": "*/15 * * * *" },
  { "path": "/api/health-digest", "schedule": "0 11 * * *" },
  { "path": "/api/cron/investing", "schedule": "0 * * * *" }
]
```

- [ ] **Step 6: Rodar e ver passar**

Run: `pytest backend/tests/test_cron_investing_route.py -v`
Esperado: PASS (2 testes)

- [ ] **Step 7: Rodar a suíte inteira** (garantir que o app sobe e nada quebrou)

Run: `pytest backend/tests/ -v`
Esperado: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/api/cron_investing.py backend/api/main.py vercel.json backend/tests/test_cron_investing_route.py
git commit -m "feat: add /api/cron/investing route and hourly cron

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Validação manual em produção

Confirma o caminho real ScraperAPI → Investing → WhatsApp antes de confiar no automático.

**Files:** nenhum (validação operacional).

- [ ] **Step 1: Deploy** — `git push origin master` (após merge da branch) dispara o build do projeto backend `noticiasgg` na Vercel. Confirmar deploy verde.

- [ ] **Step 2: Disparar em modo teste** (envia só pro admin, ignora dedup, marca `[TESTE]`):

```bash
curl -s "https://noticiasgg.vercel.app/api/cron/investing?test=true" \
  -H "x-cron-secret: $CRON_SECRET" | cat
```

Esperado: JSON `{"status":"ok", ...}`. Se houver indicador de alto impacto com Atual divulgado hoje, chega uma mensagem `[TESTE]` no WhatsApp do admin.

- [ ] **Step 3: Conferir o formato** da mensagem recebida contra o exemplo do spec (flag + nome + Anterior/Projeção/Atual). Ajustar se necessário (volta na Task 5).

- [ ] **Step 4: Verificar comportamento de "nada novo"** — rodar sem `test=true` quando não há release recente deve retornar `events: 0, sent: 0` sem enviar nada.

- [ ] **Step 5: Monitorar a primeira janela 24h** — confirmar que dedup funciona (mesmo indicador não repete a cada hora) e que mensagens chegam conforme releases saem.

---

## Self-Review

**Cobertura do spec:**
- Cron hora em hora 24/7 → Task 7 (vercel.json `0 * * * *`). ✓
- Alto impacto + Atual preenchido → Task 3 (filtro `importance == "3"` + actual no `parse`). ✓
- Todos os países → Task 3 (sem filtro de país; flag via `currencyFlag` ISO-2 cobre todos). ✓
- Mensagem agrupada, formato do exemplo → Task 5. ✓
- Aquisição via página + `__NEXT_DATA__` (ScraperAPI) → Tasks 3/4. ✓
- Dedup uma-vez-por-divulgação via `system_alert_state` (`eventId`+data) → Task 6. ✓
- Destinatários `alerts_enabled` → Task 6 (reuso `_get_recipients`). ✓
- Sem LLM → confirmado (nenhuma chamada Anthropic). ✓
- Anti-falha-silenciosa (store ausente vs vazio) → Task 3 (`_events_by_date` raise) + Task 6 (notify_admin). ✓
- `notify_admin(title=...)` → Task 2. ✓
- Spike primeiro + fixtures → Task 1 (feita inline) + Task 3. ✓
- Modo `?test=true` → Task 6/7/8. ✓
- Sonda no health-digest → marcada como opcional/follow-up no spec; **fora deste plano** (YAGNI por ora).

**Placeholders:** nenhum passo de código sem código. A estrutura real do Investing foi confirmada no spike (Task 1), então parser e fetch usam dados reais, não suposição.

**Consistência de tipos:** `parse() -> list[dict]` com as chaves `event_id/country/flag_emoji/name/importance/previous/forecast/actual` usadas igual em Tasks 3, 5 e 6. `run() -> dict` com `status/recipients/events/sent` consistente entre Task 6 e os testes da Task 7. `notify_admin(errors, title=...)` igual em Tasks 2, 6 e 7.
