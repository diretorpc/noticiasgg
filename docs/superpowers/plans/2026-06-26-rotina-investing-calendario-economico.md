# Rotina Investing — Calendário Econômico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cron de hora em hora que envia no WhatsApp os indicadores de alto impacto do calendário econômico do br.investing.com assim que o valor "Atual" é divulgado.

**Architecture:** Coletor (`fetch` + `parse`) sem efeitos colaterais → serviço (`run`) que deduplica via `system_alert_state`, monta uma mensagem agrupada e faz broadcast → router fino de cron protegido por `check_cron_secret`. Segue os padrões existentes de `check_alerts.py` / `_check_eia`. Sem chamada de LLM.

**Tech Stack:** Python 3.12, FastAPI, httpx, BeautifulSoup4, ScraperAPI, Supabase (PostgREST), Evolution API (WhatsApp), Vercel Cron.

Spec: [docs/superpowers/specs/2026-06-26-rotina-investing-calendario-economico-design.md](../specs/2026-06-26-rotina-investing-calendario-economico-design.md)

## Global Constraints

- Python: snake_case funções/variáveis, PascalCase classes.
- Commits: mensagens em inglês, imperativas. Terminar com `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Sem comentários desnecessários — só quando o "porquê" não é óbvio.
- YAGNI: nada de toggle no painel, nada de média/baixa relevância, nada de filtro por país.
- Dedup via tabela existente `system_alert_state` (`rule_id`, `last_triggered_at`).
- Destinatários: `authorized_users` com `alerts_enabled=true` (reuso de `alert_checker._get_recipients`).
- Valores numéricos: passar as strings cruas do br.investing (já em PT) — sem reformatação de locale.
- Relevância: apenas alto impacto (importância == 3). Gatilho: valor "Atual" preenchido.
- Cron: `0 * * * *` (hora em hora, 24/7).
- Rodar testes: `pytest backend/tests/ -v`.

---

### Task 1: Spike de aquisição (de-risk + calibração)

Objetivo: confirmar, com uma chamada real, que dá pra buscar o calendário via ScraperAPI e descobrir a forma exata da resposta (JSON do serviço vs HTML da página), para calibrar as constantes e os fixtures das tasks seguintes. O usuário já aprovou gastar este crédito.

**Files:**
- Create (temporário, fora do repo): `<scratchpad>/spike_investing.py`
- Create: `backend/tests/fixtures/` (diretório)

**Interfaces:**
- Produces: confirmação dos parâmetros do POST `getCalendarFilteredData` e da forma da resposta; um arquivo de amostra real salvo no scratchpad para conferência.

- [ ] **Step 1: Escrever o script de spike** em `<scratchpad>/spike_investing.py`:

```python
import os, httpx, json
KEY = os.environ["SCRAPER_API_KEY"]
SCRAPER = "https://api.scraperapi.com/"
SERVICE = "https://br.investing.com/economic-calendar/Service/getCalendarFilteredData"
PAGE = "https://br.investing.com/economic-calendar/"
SERVICE_PARAMS = {
    "importance[]": "3",
    "timeFilter": "timeRemain",
    "currentTab": "today",
    "limit_from": "0",
}

def try_service():
    with httpx.Client(timeout=60) as c:
        r = c.post(SCRAPER, params={"api_key": KEY, "url": SERVICE},
                   data=SERVICE_PARAMS, headers={"X-Requested-With": "XMLHttpRequest"})
        print("service status", r.status_code, "len", len(r.text))
        print(r.text[:500])

def try_page():
    with httpx.Client(timeout=60) as c:
        r = c.get(SCRAPER, params={"api_key": KEY, "url": PAGE})
        print("page status", r.status_code, "has table:", "economicCalendarData" in r.text)

try_service()
try_page()
```

- [ ] **Step 2: Rodar e observar a forma da resposta**

Run: `python <scratchpad>/spike_investing.py`
Esperado: pelo menos um dos dois retorna conteúdo do calendário. Anotar:
- O serviço retorna JSON com campo `data` (string HTML de `<tr>`)? Ou HTML direto?
- A página contém `<table id="economicCalendarData">`?
- Os nomes de classe reais das linhas (`js-event-item`?), do flag (`ceFlags <Pais>`?), e os `id` de atual/projeção/anterior (`eventActual_`, `eventForecast_`, `eventPrevious_`?).
- O atributo de id estável da linha (`event_attr_id` e/ou `id="eventRowId_N"`).

- [ ] **Step 3: Salvar uma amostra real** no scratchpad (`<scratchpad>/investing_sample.txt`) para conferência manual e calibração dos fixtures das Tasks 3.

- [ ] **Step 4: Calibrar constantes**

Se a estrutura real divergir do assumido neste plano (nomes de classe/id), anotar as diferenças no topo da Task 3 antes de implementar o parser. Ajustar `SERVICE_PARAMS` se o serviço exigir parâmetros adicionais (ex.: lista de `country[]`).

Sem commit (script é descartável; vive no scratchpad).

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

Núcleo da feature. Recebe o corpo cru (JSON do serviço **ou** HTML da página) e devolve só os eventos de alto impacto com "Atual" já divulgado. Distingue "tabela vazia" (normal) de "resposta irreconhecível" (quebra/bloqueio).

> **Calibração:** se a Task 1 revelou nomes de classe/id diferentes dos usados abaixo, ajustar os seletores E o fixture juntos antes de implementar.

**Files:**
- Create: `backend/collectors/investing_calendar.py`
- Create (fixture): `backend/tests/fixtures/investing_service.json`
- Create (fixture): `backend/tests/fixtures/investing_page.html`
- Test: `backend/tests/test_investing_calendar.py`

**Interfaces:**
- Produces:
  - `investing_calendar.parse(body: str) -> list[dict]` — cada dict:
    `{"event_id": str, "country": str, "flag_emoji": str, "name": str, "importance": int, "previous": str, "forecast": str, "actual": str}`
  - Levanta `ValueError` quando o corpo não é um calendário reconhecível.

- [ ] **Step 1: Criar o fixture do serviço** em `backend/tests/fixtures/investing_service.json` (JSON com 4 linhas representativas: alta+atual, alta sem atual, baixa, alta sem projeção):

```json
{"data": "<tr id=\"eventRowId_1\" event_attr_id=\"1\" class=\"js-event-item\"><td class=\"first left time js-time\">08:00</td><td class=\"left flagCur noWrap\"><span class=\"ceFlags Spain\" title=\"Spain\"></span> EUR</td><td class=\"left textNum sentiment noWrap\" data-img_key=\"bull3\" title=\"Alta Volatilidade Esperada\"><i class=\"grayFullBullishIcon\"></i><i class=\"grayFullBullishIcon\"></i><i class=\"grayFullBullishIcon\"></i></td><td class=\"left event\"><a href=\"/x\">PIB da Espanha (trimestral) (Q1)</a></td><td class=\"bold act\" id=\"eventActual_1\">0,6%</td><td class=\"fore\" id=\"eventForecast_1\">0,6%</td><td class=\"prev\" id=\"eventPrevious_1\">0,8%</td></tr><tr id=\"eventRowId_2\" event_attr_id=\"2\" class=\"js-event-item\"><td class=\"first left time js-time\">09:30</td><td class=\"left flagCur noWrap\"><span class=\"ceFlags United_States\" title=\"United States\"></span> USD</td><td class=\"left textNum sentiment noWrap\" data-img_key=\"bull3\"><i class=\"grayFullBullishIcon\"></i><i class=\"grayFullBullishIcon\"></i><i class=\"grayFullBullishIcon\"></i></td><td class=\"left event\"><a href=\"/y\">Payroll (Junho)</a></td><td class=\"act\" id=\"eventActual_2\">&nbsp;</td><td class=\"fore\" id=\"eventForecast_2\">185K</td><td class=\"prev\" id=\"eventPrevious_2\">139K</td></tr><tr id=\"eventRowId_3\" event_attr_id=\"3\" class=\"js-event-item\"><td class=\"first left time js-time\">10:00</td><td class=\"left flagCur noWrap\"><span class=\"ceFlags Brazil\" title=\"Brazil\"></span> BRL</td><td class=\"left textNum sentiment noWrap\" data-img_key=\"bull1\"><i class=\"grayFullBullishIcon\"></i></td><td class=\"left event\"><a href=\"/z\">Dado Menor BR</a></td><td class=\"act\" id=\"eventActual_3\">1,0%</td><td class=\"fore\" id=\"eventForecast_3\">1,0%</td><td class=\"prev\" id=\"eventPrevious_3\">0,9%</td></tr><tr id=\"eventRowId_4\" event_attr_id=\"4\" class=\"js-event-item\"><td class=\"first left time js-time\">10:30</td><td class=\"left flagCur noWrap\"><span class=\"ceFlags United_States\" title=\"United States\"></span> USD</td><td class=\"left textNum sentiment noWrap\" data-img_key=\"bull3\"><i class=\"grayFullBullishIcon\"></i><i class=\"grayFullBullishIcon\"></i><i class=\"grayFullBullishIcon\"></i></td><td class=\"left event\"><a href=\"/w\">Pedidos de Auxílio-Desemprego</a></td><td class=\"bold act\" id=\"eventActual_4\">206K</td><td class=\"fore\" id=\"eventForecast_4\">&nbsp;</td><td class=\"prev\" id=\"eventPrevious_4\">245K</td></tr>"}
```

- [ ] **Step 2: Criar o fixture da página** em `backend/tests/fixtures/investing_page.html` (tabela mínima reconhecível, 1 linha de alto impacto com atual):

```html
<html><body>
<table id="economicCalendarData"><tbody>
<tr id="eventRowId_9" event_attr_id="9" class="js-event-item">
<td class="first left time js-time">11:00</td>
<td class="left flagCur noWrap"><span class="ceFlags Germany" title="Germany"></span> EUR</td>
<td class="left textNum sentiment noWrap" data-img_key="bull3"><i class="grayFullBullishIcon"></i><i class="grayFullBullishIcon"></i><i class="grayFullBullishIcon"></i></td>
<td class="left event"><a href="/g">IPC da Alemanha (Mensal)</a></td>
<td class="bold act" id="eventActual_9">0,2%</td>
<td class="fore" id="eventForecast_9">0,1%</td>
<td class="prev" id="eventPrevious_9">0,0%</td>
</tr>
</tbody></table>
</body></html>
```

- [ ] **Step 3: Escrever os testes falhando** em `backend/tests/test_investing_calendar.py`:

```python
import json
from pathlib import Path

import pytest

from backend.collectors import investing_calendar

FIXTURES = Path(__file__).parent / "fixtures"


def _service_body():
    return (FIXTURES / "investing_service.json").read_text(encoding="utf-8")


def _page_body():
    return (FIXTURES / "investing_page.html").read_text(encoding="utf-8")


def test_parse_service_keeps_only_high_impact_with_actual():
    events = investing_calendar.parse(_service_body())
    names = [e["name"] for e in events]
    # Espanha (alta+atual) e Auxílio-Desemprego (alta+atual) entram;
    # Payroll (sem atual) e Dado Menor BR (baixa) ficam de fora.
    assert names == ["PIB da Espanha (trimestral) (Q1)", "Pedidos de Auxílio-Desemprego"]


def test_parse_extracts_fields_and_flag():
    events = investing_calendar.parse(_service_body())
    espanha = events[0]
    assert espanha["event_id"] == "1"
    assert espanha["flag_emoji"] == "🇪🇸"
    assert espanha["previous"] == "0,8%"
    assert espanha["forecast"] == "0,6%"
    assert espanha["actual"] == "0,6%"
    assert espanha["importance"] == 3


def test_parse_blank_forecast_is_empty_string():
    events = investing_calendar.parse(_service_body())
    auxilio = events[1]
    assert auxilio["forecast"] == ""
    assert auxilio["actual"] == "206K"


def test_parse_handles_full_page_table():
    events = investing_calendar.parse(_page_body())
    assert len(events) == 1
    assert events[0]["name"] == "IPC da Alemanha (Mensal)"
    assert events[0]["flag_emoji"] == "🇩🇪"


def test_parse_unrecognized_body_raises():
    with pytest.raises(ValueError):
        investing_calendar.parse("<html><body>Just a Cloudflare block page</body></html>")


def test_parse_empty_service_data_is_normal_empty_list():
    events = investing_calendar.parse(json.dumps({"data": ""}))
    assert events == []
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `pytest backend/tests/test_investing_calendar.py -v`
Esperado: FAIL — módulo `investing_calendar` sem `parse`.

- [ ] **Step 5: Implementar `parse` (+ helpers de flag/limpeza)** em `backend/collectors/investing_calendar.py`:

```python
import json
import logging

from bs4 import BeautifulSoup

logger = logging.getLogger("noticiasgg.investing")

_FLAG = {
    "United_States": "🇺🇸", "Euro_Zone": "🇪🇺", "Germany": "🇩🇪", "France": "🇫🇷",
    "Spain": "🇪🇸", "Italy": "🇮🇹", "United_Kingdom": "🇬🇧", "China": "🇨🇳",
    "Japan": "🇯🇵", "Australia": "🇦🇺", "Canada": "🇨🇦", "Switzerland": "🇨🇭",
    "New_Zealand": "🇳🇿", "India": "🇮🇳", "South_Korea": "🇰🇷", "Mexico": "🇲🇽",
    "Russia": "🇷🇺", "Netherlands": "🇳🇱", "Singapore": "🇸🇬", "Portugal": "🇵🇹",
    "Argentina": "🇦🇷", "South_Africa": "🇿🇦", "Turkey": "🇹🇷", "Norway": "🇳🇴",
    "Sweden": "🇸🇪", "Brazil": "🇧🇷", "Hong_Kong": "🇭🇰", "Indonesia": "🇮🇩",
}


def _clean(node) -> str:
    if node is None:
        return ""
    text = node.get_text(strip=True).replace("\xa0", "").strip()
    return "" if text in {"", "-", "&nbsp;"} else text


def _flag_emoji(span) -> tuple[str, str]:
    if span is None:
        return "", ""
    classes = [c for c in span.get("class", []) if c != "ceFlags"]
    country = classes[0] if classes else ""
    return country, _FLAG.get(country, "")


def _importance(row) -> int:
    sentiment = row.select_one("td.sentiment")
    if sentiment is not None:
        key = sentiment.get("data-img_key", "")
        if key.startswith("bull") and key[4:].isdigit():
            return int(key[4:])
        return len(sentiment.select("i.grayFullBullishIcon"))
    return 0


def _rows_html(body: str) -> str:
    """Aceita o JSON do serviço ({"data": "<tr>..."}) ou o HTML da página.
    Levanta ValueError se o corpo não for um calendário reconhecível."""
    stripped = body.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValueError(f"investing: corpo JSON inválido: {e}") from e
        if "data" not in payload:
            raise ValueError("investing: JSON sem campo 'data'")
        return payload["data"]
    if "economicCalendarData" in body:
        return body
    raise ValueError("investing: resposta irreconhecível (bloqueio ou mudança de layout)")


def parse(body: str) -> list[dict]:
    html = _rows_html(body)
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict] = []
    for row in soup.select("tr.js-event-item"):
        importance = _importance(row)
        actual = _clean(row.select_one('td[id^="eventActual_"]'))
        if importance != 3 or not actual:
            continue
        name_node = row.select_one("td.event a") or row.select_one("td.event")
        country, flag = _flag_emoji(row.select_one("span.ceFlags"))
        event_id = row.get("event_attr_id") or row.get("id", "").replace("eventRowId_", "")
        events.append({
            "event_id": str(event_id),
            "country": country,
            "flag_emoji": flag,
            "name": _clean(name_node),
            "importance": importance,
            "previous": _clean(row.select_one('td[id^="eventPrevious_"]')),
            "forecast": _clean(row.select_one('td[id^="eventForecast_"]')),
            "actual": actual,
        })
    return events
```

- [ ] **Step 6: Rodar e ver passar**

Run: `pytest backend/tests/test_investing_calendar.py -v`
Esperado: PASS (6 testes)

- [ ] **Step 7: Commit**

```bash
git add backend/collectors/investing_calendar.py backend/tests/test_investing_calendar.py backend/tests/fixtures/investing_service.json backend/tests/fixtures/investing_page.html
git commit -m "feat: parse investing economic-calendar events

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Busca via ScraperAPI (`fetch`)

Adiciona a aquisição: POST no serviço com fallback para GET da página. Usa as constantes calibradas na Task 1.

**Files:**
- Modify: `backend/collectors/investing_calendar.py` (adicionar `fetch` e constantes no topo)
- Test: `backend/tests/test_investing_fetch.py`

**Interfaces:**
- Consumes: `parse(body)` da Task 3.
- Produces: `investing_calendar.fetch() -> str` (corpo cru pronto pro `parse`). Levanta `ValueError` se `SCRAPER_API_KEY` ausente.

- [ ] **Step 1: Escrever o teste de integração** (pulado sem chave) em `backend/tests/test_investing_fetch.py`:

```python
import os

import pytest

from backend.collectors import investing_calendar


@pytest.mark.skipif(not os.getenv("SCRAPER_API_KEY"), reason="SCRAPER_API_KEY não configurada")
def test_fetch_returns_parseable_calendar():
    body = investing_calendar.fetch()
    # Não deve levantar: ou tem eventos de alto impacto agora, ou lista vazia (normal).
    events = investing_calendar.parse(body)
    assert isinstance(events, list)


def test_fetch_without_key_raises(monkeypatch):
    monkeypatch.delenv("SCRAPER_API_KEY", raising=False)
    with pytest.raises(ValueError):
        investing_calendar.fetch()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `pytest backend/tests/test_investing_fetch.py -v`
Esperado: FAIL — `fetch` não existe.

- [ ] **Step 3: Implementar `fetch`** no topo de `backend/collectors/investing_calendar.py` (abaixo dos imports; adicionar `import os` e `import httpx`):

```python
import os

import httpx

_SCRAPER_URL = "https://api.scraperapi.com/"
_SERVICE_URL = "https://br.investing.com/economic-calendar/Service/getCalendarFilteredData"
_PAGE_URL = "https://br.investing.com/economic-calendar/"
# Calibrado na Task 1. Sem country[] → serviço devolve todos os países.
_SERVICE_PARAMS = {
    "importance[]": "3",
    "timeFilter": "timeRemain",
    "currentTab": "today",
    "limit_from": "0",
}


def fetch() -> str:
    key = os.environ.get("SCRAPER_API_KEY", "")
    if not key:
        raise ValueError("SCRAPER_API_KEY não configurada")
    try:
        with httpx.Client(timeout=45) as client:
            r = client.post(
                _SCRAPER_URL,
                params={"api_key": key, "url": _SERVICE_URL},
                data=_SERVICE_PARAMS,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            r.raise_for_status()
            return r.text
    except Exception as e:
        logger.warning("investing service endpoint falhou (%s), fallback para página", e)
        with httpx.Client(timeout=45) as client:
            r = client.get(_SCRAPER_URL, params={"api_key": key, "url": _PAGE_URL})
            r.raise_for_status()
            return r.text
```

- [ ] **Step 4: Rodar e ver passar**

Run: `pytest backend/tests/test_investing_fetch.py -v`
Esperado: PASS (integração roda se houver `SCRAPER_API_KEY` no ambiente; senão é skipped; o teste sem-chave passa).

- [ ] **Step 5: Commit**

```bash
git add backend/collectors/investing_calendar.py backend/tests/test_investing_fetch.py
git commit -m "feat: fetch investing calendar via ScraperAPI with page fallback

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
import json
from pathlib import Path

from backend.collectors import investing_calendar
from backend.services import investing_digest, alert_checker, supabase

FIXTURES = Path(__file__).parent / "fixtures"


def _service_body():
    return (FIXTURES / "investing_service.json").read_text(encoding="utf-8")


def _wire(monkeypatch, sent_store, already=None):
    already = already or set()
    monkeypatch.setattr(investing_calendar, "fetch", lambda: _service_body())
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
    assert result["events"] == 2  # Espanha + Auxílio-Desemprego
    assert result["sent"] == 1
    assert len(sent) == 1
    assert "🇪🇸 PIB da Espanha" in sent[0]
    assert "Pedidos de Auxílio-Desemprego" in sent[0]


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
        body = investing_calendar.fetch()
        events = investing_calendar.parse(body)
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
import os

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
- Alto impacto + Atual preenchido → Task 3 (filtro no `parse`). ✓
- Todos os países → Task 4 (`_SERVICE_PARAMS` sem `country[]`) + mapa de flags Task 3. ✓
- Mensagem agrupada, formato do exemplo → Task 5. ✓
- Aquisição endpoint+fallback via ScraperAPI → Task 4. ✓
- Dedup uma-vez-por-divulgação via `system_alert_state` → Task 6. ✓
- Destinatários `alerts_enabled` → Task 6 (reuso `_get_recipients`). ✓
- Sem LLM → confirmado (nenhuma chamada Anthropic). ✓
- Anti-falha-silenciosa (irreconhecível vs vazio) → Task 3 (`_rows_html` raise) + Task 6 (notify_admin). ✓
- `notify_admin(title=...)` → Task 2. ✓
- Spike primeiro + fixtures → Task 1 + Task 3. ✓
- Modo `?test=true` → Task 6/7/8. ✓
- Sonda no health-digest → marcada como opcional/follow-up no spec; **fora deste plano** (YAGNI por ora).

**Placeholders:** nenhum passo de código sem código. Os `_SERVICE_PARAMS` exatos são calibrados na Task 1 (chamada de rede indisponível em tempo de planejamento) — constante isolada e documentada, não placeholder de lógica.

**Consistência de tipos:** `parse() -> list[dict]` com as chaves `event_id/country/flag_emoji/name/importance/previous/forecast/actual` usadas igual em Tasks 3, 5 e 6. `run() -> dict` com `status/recipients/events/sent` consistente entre Task 6 e os testes da Task 7. `notify_admin(errors, title=...)` igual em Tasks 2, 6 e 7.
