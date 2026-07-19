# Camada 1 — Boletim Diário de Saúde (noticiasgg) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um boletim diário de saúde do noticiasgg enviado ao admin no WhatsApp às 08:00 BRT, com checks que exercitam os caminhos que falham em silêncio (incl. o dedup que quebrou em jun/2026).

**Architecture:** Um módulo `health.py` é a fonte única da verdade ("como estou?"): `collect_status()` roda os checks fundos, `format_digest()` monta a mensagem, `send_daily_digest()` aplica trava diária *fail-open* e envia ao admin. Um cron dedicado `/api/health-digest` (Vercel Pro permite >2 crons) chama o digest 1x/dia; o mesmo `collect_status()` passa a alimentar o `/api/health` (deixa pronto pra Camada 2 ler de lá). É o "check-up médico" diário, complementar ao `notify_admin` (o "alarme de incêndio" que já existe e só toca em erro forte).

**Tech Stack:** Python 3.12, FastAPI, httpx, Supabase REST (PostgREST), Evolution API (WhatsApp), Anthropic não envolvido, pytest.

## Global Constraints

- Timestamps em filtros PostgREST SEMPRE encodados via `supabase._f()` (o `+00:00` cru vira espaço e dá 400 — bug corrigido em fa2b5d0; não repetir).
- Endpoint de cron novo SEMPRE protegido por `check_cron_secret(request)` (mesmo padrão de `check_alerts.py`).
- Destinatário do boletim = admin apenas (`REPLY_TO_NUMBER` → fallback `AUTHORIZED_NUMBER`), nunca os usuários finais.
- Trava diária *fail-open*: falha ao ler/gravar a trava no Supabase NÃO pode silenciar o boletim.
- Sem mock de banco onde a API real cabe; testes usam transport fake do httpx (padrão de `test_supabase.py`).
- Cron schedule em UTC: 08:00 BRT = `0 11 * * *`.

---

### Task 1: `supabase.count_recent_broadcasts` — contagem de broadcasts nas últimas 24h

**Files:**
- Modify: `backend/services/supabase.py` (nova função após `get_recent_sent_titles`)
- Test: `backend/tests/test_supabase.py`

**Interfaces:**
- Produces: `count_recent_broadcasts(hours: int = 24) -> int` — nº de linhas em `sent_news` com `title` não-nulo (broadcasts reais) na janela.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao final de `backend/tests/test_supabase.py`:

```python
def test_count_recent_broadcasts_le_content_range():
    captured = {}

    def fake_handle(self, request):
        captured["url"] = str(request.url)
        captured["prefer"] = request.headers.get("prefer", "")
        return httpx.Response(200, json=[], headers={"content-range": "0-8/9"})

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        n = supabase.count_recent_broadcasts()
    assert n == 9
    assert "count=exact" in captured["prefer"]
    assert "title=not.is.null" in captured["url"]
    assert "+00:00" not in captured["url"]  # cutoff encodado (lição do bug fa2b5d0)


def test_count_recent_broadcasts_zero_quando_sem_header():
    def fake_handle(self, request):
        return httpx.Response(200, json=[])

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        n = supabase.count_recent_broadcasts()
    assert n == 0
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `python -m pytest backend/tests/test_supabase.py -q`
Expected: 2 FAILED — `AttributeError: module ... has no attribute 'count_recent_broadcasts'`

- [ ] **Step 3: Implementar**

Em `backend/services/supabase.py`, adicionar logo após `get_recent_sent_titles`:

```python
def count_recent_broadcasts(hours: int = 24) -> int:
    """Nº de notícias efetivamente enviadas (title não-nulo) na janela — sinal de vida."""
    cutoff = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    ).isoformat()
    with _client() as c:
        r = c.get(
            f"/sent_news?select=news_id&title=not.is.null"
            f"&sent_at=gte.{_f(cutoff)}&limit=1",
            headers={"Prefer": "count=exact"},
        )
        r.raise_for_status()
        content_range = r.headers.get("content-range", "*/0")
        try:
            return int(content_range.split("/")[1])
        except (IndexError, ValueError):
            return 0
```

- [ ] **Step 4: Rodar e verificar que passam**

Run: `python -m pytest backend/tests/test_supabase.py -q`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/supabase.py backend/tests/test_supabase.py
git commit -m "feat: count recent broadcasts for health digest"
```

---

### Task 2: `whatsapp.connection_state` — estado da instância Evolution

**Files:**
- Modify: `backend/services/whatsapp.py` (nova função)
- Test: `backend/tests/test_whatsapp.py` (criar)

**Interfaces:**
- Produces: `connection_state() -> str` — devolve o estado da instância (`"open"`, `"connecting"`, `"close"`, `"unknown"`). Levanta em falha de transporte/HTTP (o caller decide degradar).

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/test_whatsapp.py`:

```python
import os
from unittest.mock import patch

import httpx

from backend.services import whatsapp

_ENV = {
    "EVOLUTION_API_URL": "http://fake:8080",
    "EVOLUTION_API_KEY": "k",
    "EVOLUTION_INSTANCE": "noticiasgg",
}


def test_connection_state_extrai_state_do_payload():
    def fake_handle(self, request):
        assert "/instance/connectionState/noticiasgg" in str(request.url)
        return httpx.Response(200, json={"instance": {"instanceName": "noticiasgg", "state": "open"}})

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        assert whatsapp.connection_state() == "open"


def test_connection_state_payload_plano():
    def fake_handle(self, request):
        return httpx.Response(200, json={"state": "connecting"})

    with patch.dict(os.environ, _ENV), \
         patch.object(httpx.HTTPTransport, "handle_request", fake_handle):
        assert whatsapp.connection_state() == "connecting"
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `python -m pytest backend/tests/test_whatsapp.py -q`
Expected: 2 FAILED — `AttributeError: module ... has no attribute 'connection_state'`

- [ ] **Step 3: Implementar**

Em `backend/services/whatsapp.py`, adicionar ao final:

```python
def connection_state() -> str:
    """Estado da conexão da instância na Evolution API (open/connecting/close).
    Levanta em falha — o caller (health) decide degradar para warn."""
    endpoint = f"{_base_url()}/instance/connectionState/{_instance()}"
    with httpx.Client(timeout=10) as client:
        resp = client.get(endpoint, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        inst = data.get("instance", data)
        return inst.get("state", "unknown")
```

- [ ] **Step 4: Rodar e verificar que passam**

Run: `python -m pytest backend/tests/test_whatsapp.py -q`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/whatsapp.py backend/tests/test_whatsapp.py
git commit -m "feat: expose Evolution instance connection state"
```

---

### Task 3: `health.collect_status` — os checks fundos

**Files:**
- Create: `backend/services/health.py`
- Test: `backend/tests/test_health.py` (criar)

**Interfaces:**
- Consumes: `supabase.get_recent_sent_titles`, `supabase.count_recent_broadcasts`, `supabase.get_polls`, `whatsapp.connection_state`.
- Produces: `collect_status() -> dict` no formato `{"status": "ok"|"warn"|"error", "checks": {<nome>: {"status": ...}}, "checked_at": iso}`. Chaves de `checks`: `keys`, `dedup`, `broadcasts`, `evolution`, `polls`.

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/test_health.py`:

```python
from unittest.mock import patch

from backend.services import health


def test_collect_status_tudo_ok():
    with patch.multiple(
        "backend.services.health.supabase",
        get_recent_sent_titles=lambda *a, **k: ["a", "b"],
        count_recent_broadcasts=lambda *a, **k: 9,
        get_polls=lambda *a, **k: [{"instituto": "X"}],
    ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["status"] == "ok"
    assert st["checks"]["dedup"]["status"] == "ok"
    assert st["checks"]["dedup"]["titulos_24h"] == 2
    assert st["checks"]["broadcasts"]["enviados_24h"] == 9
    assert st["checks"]["evolution"]["status"] == "ok"
    assert "checked_at" in st


def test_collect_status_dedup_quebrado_vira_error():
    with patch.multiple(
        "backend.services.health.supabase",
        get_recent_sent_titles=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("400 Bad Request")),
        count_recent_broadcasts=lambda *a, **k: 9,
        get_polls=lambda *a, **k: [{"instituto": "X"}],
    ), patch("backend.services.health.whatsapp.connection_state", return_value="open"):
        st = health.collect_status()
    assert st["status"] == "error"
    assert st["checks"]["dedup"]["status"] == "error"


def test_collect_status_evolution_desconectada_vira_warn():
    with patch.multiple(
        "backend.services.health.supabase",
        get_recent_sent_titles=lambda *a, **k: ["a"],
        count_recent_broadcasts=lambda *a, **k: 1,
        get_polls=lambda *a, **k: [{"instituto": "X"}],
    ), patch("backend.services.health.whatsapp.connection_state", return_value="close"):
        st = health.collect_status()
    assert st["status"] == "warn"
    assert st["checks"]["evolution"]["status"] == "warn"
    assert st["checks"]["evolution"]["estado"] == "close"


def test_collect_status_evolution_excecao_degrada_para_warn():
    with patch.multiple(
        "backend.services.health.supabase",
        get_recent_sent_titles=lambda *a, **k: ["a"],
        count_recent_broadcasts=lambda *a, **k: 1,
        get_polls=lambda *a, **k: [{"instituto": "X"}],
    ), patch("backend.services.health.whatsapp.connection_state",
             side_effect=RuntimeError("timeout")):
        st = health.collect_status()
    assert st["checks"]["evolution"]["status"] == "warn"
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: FAILED — `ModuleNotFoundError: backend.services.health`

- [ ] **Step 3: Implementar**

Criar `backend/services/health.py`:

```python
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
```

- [ ] **Step 4: Rodar e verificar que passam**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/health.py backend/tests/test_health.py
git commit -m "feat: health.collect_status with deep silent-failure probes"
```

---

### Task 4: `health.format_digest` — a mensagem do WhatsApp

**Files:**
- Modify: `backend/services/health.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: dict de `collect_status()`.
- Produces: `format_digest(status: dict) -> str`. Verde quando nenhum check é warn/error; senão lidera com `⚠️ N problema(s)`.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `backend/tests/test_health.py`:

```python
_STATUS_OK = {
    "status": "ok",
    "checks": {
        "keys": {"status": "ok", "faltando": []},
        "dedup": {"status": "ok", "titulos_24h": 12},
        "broadcasts": {"status": "ok", "enviados_24h": 9},
        "evolution": {"status": "ok", "estado": "open"},
        "polls": {"status": "ok", "institutos": 3},
    },
    "checked_at": "2026-06-25T11:00:00+00:00",
}

_STATUS_PROBLEMA = {
    "status": "error",
    "checks": {
        "keys": {"status": "ok", "faltando": []},
        "dedup": {"status": "error", "message": "400 Bad Request"},
        "broadcasts": {"status": "ok", "enviados_24h": 9},
        "evolution": {"status": "ok", "estado": "open"},
        "polls": {"status": "ok", "institutos": 3},
    },
    "checked_at": "2026-06-25T11:00:00+00:00",
}


def test_format_digest_verde():
    msg = health.format_digest(_STATUS_OK)
    assert "saúde diária" in msg
    assert "✅ Tudo OK" in msg
    assert "Dedup: ativo (12 títulos/24h)" in msg
    assert "Alertas enviados (24h): 9" in msg


def test_format_digest_problema_lidera_e_marca():
    msg = health.format_digest(_STATUS_PROBLEMA)
    assert "⚠️ 1 problema" in msg
    assert "❌" in msg
    assert "Dedup" in msg
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: 2 FAILED — `AttributeError: module ... has no attribute 'format_digest'`

- [ ] **Step 3: Implementar**

Em `backend/services/health.py`, adicionar:

```python
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
```

- [ ] **Step 4: Rodar e verificar que passam**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/health.py backend/tests/test_health.py
git commit -m "feat: format daily health digest message"
```

---

### Task 5: `health.send_daily_digest` — trava fail-open + envio ao admin

**Files:**
- Modify: `backend/services/health.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: `collect_status`, `format_digest`, `supabase.get_alert_last_triggered`, `supabase.set_alert_triggered`, `whatsapp.send_message`.
- Produces: `send_daily_digest() -> dict` — `{"status": "sent"|"skipped"|"error", ...}`.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `backend/tests/test_health.py`:

```python
import os as _os
from datetime import datetime, timedelta, timezone

_ADMIN_ENV = {"REPLY_TO_NUMBER": "5534999945010"}


def test_send_daily_digest_envia_para_admin():
    with patch.dict(_os.environ, _ADMIN_ENV), \
         patch("backend.services.health.supabase.get_alert_last_triggered", return_value=None), \
         patch("backend.services.health.collect_status", return_value=_STATUS_OK), \
         patch("backend.services.health.supabase.set_alert_triggered"), \
         patch("backend.services.health.whatsapp.send_message") as mock_send:
        out = health.send_daily_digest()
    assert out["status"] == "sent"
    assert mock_send.call_args[0][0] == "5534999945010"
    assert "saúde diária" in mock_send.call_args[0][1]


def test_send_daily_digest_respeita_cooldown():
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    with patch.dict(_os.environ, _ADMIN_ENV), \
         patch("backend.services.health.supabase.get_alert_last_triggered", return_value=recent), \
         patch("backend.services.health.whatsapp.send_message") as mock_send:
        out = health.send_daily_digest()
    assert out["status"] == "skipped"
    mock_send.assert_not_called()


def test_send_daily_digest_cooldown_falha_aberta():
    """Supabase fora não pode silenciar o boletim — se a trava não puder ser lida, envia mesmo assim."""
    with patch.dict(_os.environ, _ADMIN_ENV), \
         patch("backend.services.health.supabase.get_alert_last_triggered",
               side_effect=RuntimeError("supabase down")), \
         patch("backend.services.health.collect_status", return_value=_STATUS_PROBLEMA), \
         patch("backend.services.health.supabase.set_alert_triggered"), \
         patch("backend.services.health.whatsapp.send_message") as mock_send:
        out = health.send_daily_digest()
    assert out["status"] == "sent"
    mock_send.assert_called_once()
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: 3 FAILED — `AttributeError: module ... has no attribute 'send_daily_digest'`

- [ ] **Step 3: Implementar**

Em `backend/services/health.py`, adicionar imports e a função:

```python
from datetime import timedelta  # adicionar ao import de datetime no topo
```

(O topo passa a ser: `from datetime import datetime, timedelta, timezone`.)

```python
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
```

- [ ] **Step 4: Rodar e verificar que passam**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/health.py backend/tests/test_health.py
git commit -m "feat: send_daily_digest with fail-open cooldown to admin"
```

---

### Task 6: Endpoint cron `/api/health-digest` + wiring no main.py

**Files:**
- Create: `backend/api/health_digest.py`
- Modify: `backend/api/main.py` (incluir router; apontar `/api/health` GET para `health.collect_status()`)
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: `check_cron_secret`, `health.send_daily_digest`, `alert_checker.notify_admin`, `health.collect_status`.
- Produces: rota `GET /api/health-digest` (protegida por CRON_SECRET); `GET /api/health` passa a devolver `collect_status()`.

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient


def test_health_digest_endpoint_exige_cron_secret():
    from backend.api.main import app
    client = TestClient(app)
    with patch.dict(_os.environ, {"CRON_SECRET": "s3cr3t"}):
        r = client.get("/api/health-digest")  # sem header
    assert r.status_code == 401


def test_health_digest_endpoint_dispara_digest():
    from backend.api.main import app
    client = TestClient(app)
    with patch.dict(_os.environ, {"CRON_SECRET": "s3cr3t"}), \
         patch("backend.api.health_digest.health.send_daily_digest",
               return_value={"status": "sent", "overall": "ok"}) as mock_dig:
        r = client.get("/api/health-digest", headers={"Authorization": "Bearer s3cr3t"})
    assert r.status_code == 200
    assert r.json()["status"] == "sent"
    mock_dig.assert_called_once()


def test_health_endpoint_usa_collect_status():
    from backend.api.main import app
    client = TestClient(app)
    fake = {"status": "ok", "checks": {"dedup": {"status": "ok"}}, "checked_at": "x"}
    with patch("backend.api.main.health.collect_status", return_value=fake):
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["checks"]["dedup"]["status"] == "ok"
```

- [ ] **Step 2: Rodar e verificar que falham**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: FAILED — rota `/api/health-digest` é 404 / `health` não importado em main.

- [ ] **Step 3: Implementar**

Criar `backend/api/health_digest.py`:

```python
import logging

from fastapi import APIRouter, Request

from backend.api.cron_auth import check_cron_secret
from backend.services import health, alert_checker

logger = logging.getLogger("noticiasgg")
router = APIRouter()


@router.get("/api/health-digest")
async def health_digest(request: Request):
    check_cron_secret(request)
    try:
        return health.send_daily_digest()
    except Exception as e:
        logger.exception("health digest failed")
        try:
            alert_checker.notify_admin([f"health-digest fatal: {e}"])
        except Exception:
            logger.exception("admin notify failed")
        return {"status": "error", "detail": str(e)}
```

Em `backend/api/main.py`:

1. No bloco de imports de services (`from backend.services import reporter, whatsapp, supabase`), adicionar `health`:

```python
from backend.services import reporter, whatsapp, supabase, health
```

2. No bloco de imports de api (`from backend.api import send_report, cron_report, check_alerts, admin, me`), adicionar `health_digest`:

```python
from backend.api import send_report, cron_report, check_alerts, admin, me, health_digest
```

3. Após `app.include_router(me.router)`, adicionar:

```python
app.include_router(health_digest.router)
```

4. Substituir o corpo do handler `GET /api/health` (de `from datetime import ...` até o `return {...}`) por:

```python
@app.get("/api/health")
async def health_endpoint():
    return health.collect_status()
```

(O handler `@app.head("/api/health")` permanece inalterado — ping de uptime continua barato.)

- [ ] **Step 4: Rodar a suíte de health + a do arquivo**

Run: `python -m pytest backend/tests/test_health.py -q`
Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/health_digest.py backend/api/main.py backend/tests/test_health.py
git commit -m "feat: /api/health-digest cron endpoint and deep /api/health"
```

---

### Task 7: Cron na Vercel + deploy + verificação em produção

**Files:**
- Modify: `vercel.json`

- [ ] **Step 1: Adicionar o cron dedicado**

Em `vercel.json`, no array `crons`, adicionar a 3ª entrada (Vercel Pro permite):

```json
  "crons": [
    { "path": "/api/cron/report",  "schedule": "0 * * * *" },
    { "path": "/api/check-alerts", "schedule": "*/15 * * * *" },
    { "path": "/api/health-digest", "schedule": "0 11 * * *" }
  ]
```

(`0 11 * * *` UTC = 08:00 BRT.)

- [ ] **Step 2: Suíte completa local**

Run: `python -m pytest backend/tests/ -q`
Expected: todos PASS (217 antigos + os novos)

- [ ] **Step 3: Commit + deploy**

```bash
git add vercel.json
git commit -m "chore: schedule daily health digest cron (08:00 BRT)"
git push origin master
```

Confirmar via MCP Vercel que o deploy do projeto `noticiasgg` (python) ficou READY.

- [ ] **Step 4: Smoke test do health profundo**

```bash
curl -s "https://noticiasgg.vercel.app/api/health" | head -c 400
```

Expected: JSON com `"checks"` contendo `dedup`, `broadcasts`, `evolution` — e `dedup.status == "ok"` (prova que o fix de fa2b5d0 segue de pé).

- [ ] **Step 5: Disparo manual do digest (validação end-to-end)**

Com o `CRON_SECRET` de produção (mesmo usado pelo check-alerts):

```bash
curl -s "https://noticiasgg.vercel.app/api/health-digest" \
  -H "Authorization: Bearer $CRON_SECRET"
```

Expected: `{"status":"sent","overall":"ok"}` e o boletim chega no WhatsApp do admin. Rodar 2x seguidas → a 2ª deve voltar `{"status":"skipped","reason":"cooldown"}` (trava diária funcionando).

- [ ] **Step 6: Confirmar o cron agendado**

Via MCP Vercel (ou painel) confirmar que `/api/health-digest` aparece na lista de crons com schedule `0 11 * * *`. No próximo dia às 08:00 BRT, o boletim deve chegar sozinho.

---

## Fora do escopo (backlog)

- **Camada 2** (vigia da frota): rotina Claude agendada que bate no `/api/health` de cada projeto. Só depois desta Camada 1 provar valor e dos outros projetos terem `/api/health`.
- **Cota real da NewsAPI** no health: hoje usamos "broadcasts 24h" como proxy de vida; medir cota exigiria gastar request — não vale agora.
- **Unificar `notify_admin` e o digest** num único canal de saúde — os dois coexistem de propósito (alarme imediato vs. check-up diário).

## Riscos aceitos

- `/api/health` GET fica mais lento (lê Supabase 2x + bate na Evolution). Ping de uptime usa o HEAD, que continua barato. Aceitável.
- A Evolution é consultada a cada GET `/api/health` — se a Camada 2 bater nesse endpoint com muita frequência, reavaliar cache. Por ora, baixo volume.
- Boletim depende do WhatsApp/Evolution pra chegar. Se a Evolution cair, o boletim não chega — e a ausência do verde diário vira o sinal (trade-off aceito da cadência diária).
