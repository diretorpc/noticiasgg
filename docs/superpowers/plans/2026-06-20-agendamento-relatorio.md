# Agendamento Data-Driven do Relatório — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agendar e disparar o relatório do item 1 por usuário (seção × dia × hora) via cron nativo da Vercel, com grade de edição no painel, rodando em paralelo ao n8n via flag de opt-in.

**Architecture:** Tabela `report_schedules` (phone×section×weekday×hour) + flag `use_new_report_engine`. Serviço `schedules.py` (transforms puros + wrappers PostgREST). Dispatcher `/api/cron/report` reescrito: calcula dia/hora BRT, busca o que vence agora, filtra pela flag, chama `report_engine.generate_sections` e envia. Crons no `vercel.json` (relatório 1h, alerts 15min). Grade no painel grava via endpoints admin.

**Tech Stack:** Python 3.12, FastAPI, PostgREST (Supabase service role), `anthropic` (via item 1), Next.js/TS (painel), Vercel Pro cron, pytest.

## Global Constraints

- Chaves de seção (motor novo): `commodities, bolsas, cambio_cripto, noticias, analise, politica`.
- `weekday`: int 0-6, seg=0 … dom=6 (`datetime.weekday()`). `hour`: int 0-23, BRT. Na grade JSON as chaves de weekday são **strings** ("0".."6").
- Auth admin: `auth.verify_supabase_jwt`. Auth cron: aceitar `Authorization: Bearer <CRON_SECRET>` **ou** `x-cron-secret`.
- Supabase via service role (`_client()`/`_f()` de `supabase.py`). Sem mock de banco: testes monkeypatcham `schedules.*`, `report_engine.*`, `whatsapp.*`, e usam `dependency_overrides` pro auth.
- Não tocar `report_engine`, `reporter.generate_report` nem `main.py` (webhook). Testes determinísticos marcados `@pytest.mark.unit` (entram no CI gate `pytest -m unit`).

---

## File Structure

- Supabase (SQL manual) — **Criar** tabela `report_schedules` + coluna `authorized_users.use_new_report_engine`.
- `backend/services/schedules.py` — **Criar.** Transforms puros (`grid_to_rows`/`rows_to_grid`) + wrappers PostgREST (`due_now`, `get_for_phone`, `replace_for_phone`, `set_engine_flag`, `phones_with_engine_enabled`).
- `backend/api/cron_auth.py` — **Criar.** `check_cron_secret(request)` (Bearer ou x-cron-secret).
- `backend/api/check_alerts.py` — **Modificar.** Usa `cron_auth.check_cron_secret`.
- `backend/api/cron_report.py` — **Reescrever.** Dispatcher novo.
- `vercel.json` — **Modificar.** `crons`.
- `backend/api/admin.py` — **Modificar.** `GET`/`PUT /api/admin/schedules/{phone}`.
- `frontend/lib/config.ts` — **Modificar.** `fetchSchedule`/`saveSchedule`.
- `frontend/components/users-manager.tsx` — **Modificar.** Grade seção×dia + toggle.
- Testes: `backend/tests/test_schedules.py` (transforms), `test_cron_report.py` (reescrito), `test_cron_auth.py`, `test_schedules_admin.py` — **Criar/Reescrever.**

---

### Task 1: Migration Supabase (tabela + flag)

**Files:**
- Supabase SQL editor (manual, executado pelo usuário).

**Interfaces:**
- Produces: tabela `report_schedules(phone, section, weekday, hour)` e coluna `authorized_users.use_new_report_engine`.

- [ ] **Step 1: Rodar o SQL no Supabase (SQL Editor)**

```sql
create table if not exists report_schedules (
  phone   text  not null,
  section text  not null,
  weekday int2  not null check (weekday between 0 and 6),
  hour    int2  not null check (hour between 0 and 23),
  primary key (phone, section, weekday, hour)
);

alter table report_schedules enable row level security;

create policy "authenticated full access report_schedules"
  on report_schedules for all to authenticated
  using (true) with check (true);

alter table authorized_users
  add column if not exists use_new_report_engine boolean not null default false;
```

- [ ] **Step 2: Verificar via PostgREST (service role)**

Run (no Git Bash, com as envs do `.env` carregadas — ou rode os 2 GETs pelo navegador autenticado):
```bash
cd "c:/Users/Dib/Projetos/pessoal/noticiasgg" && python - <<'PY'
import os, httpx
from dotenv import load_dotenv; load_dotenv()
h={"apikey":os.environ["SUPABASE_KEY"],"Authorization":f"Bearer {os.environ['SUPABASE_KEY']}"}
b=f"{os.environ['SUPABASE_URL']}/rest/v1"
print("report_schedules:", httpx.get(f"{b}/report_schedules?limit=1",headers=h).status_code)
print("flag:", httpx.get(f"{b}/authorized_users?select=phone,use_new_report_engine&limit=1",headers=h).json())
PY
```
Expected: `report_schedules: 200` e a lista de usuários trazendo `use_new_report_engine: false`.

- [ ] **Step 3: Commit (nenhum arquivo — registrar no plano)**

Sem arquivo de código nesta task. Marcar como concluída quando os dois GETs responderem 200.

---

### Task 2: Serviço `schedules.py` (transforms + wrappers)

**Files:**
- Create: `backend/services/schedules.py`
- Test: `backend/tests/test_schedules.py`

**Interfaces:**
- Consumes: `supabase._client`, `supabase._f`.
- Produces:
  - `grid_to_rows(phone: str, schedule: dict) -> list[dict]` — grade `{section: {weekday_str: [hours]}}` → linhas `{phone, section, weekday:int, hour:int}`.
  - `rows_to_grid(rows: list[dict]) -> dict` — linhas (`section, weekday, hour`) → grade `{section: {weekday_str: [hours ordenados]}}`.
  - `due_now(weekday: int, hour: int) -> list[dict]` (linhas `{phone, section}`).
  - `get_for_phone(phone: str) -> list[dict]`.
  - `replace_for_phone(phone: str, rows: list[dict]) -> None`.
  - `set_engine_flag(phone: str, enabled: bool) -> None`.
  - `phones_with_engine_enabled() -> set[str]`.

- [ ] **Step 1: Write the failing test (transforms puros)**

```python
# backend/tests/test_schedules.py
import pytest
from backend.services import schedules


@pytest.mark.unit
def test_grid_to_rows_expands_each_hour():
    grid = {"commodities": {"0": [7, 12], "4": [7]}}
    rows = schedules.grid_to_rows("5534999945010", grid)
    assert {"phone": "5534999945010", "section": "commodities", "weekday": 0, "hour": 7} in rows
    assert {"phone": "5534999945010", "section": "commodities", "weekday": 0, "hour": 12} in rows
    assert {"phone": "5534999945010", "section": "commodities", "weekday": 4, "hour": 7} in rows
    assert len(rows) == 3


@pytest.mark.unit
def test_grid_to_rows_empty():
    assert schedules.grid_to_rows("x", {}) == []
    assert schedules.grid_to_rows("x", {"bolsas": {"0": []}}) == []


@pytest.mark.unit
def test_rows_to_grid_groups_and_sorts():
    rows = [
        {"section": "bolsas", "weekday": 0, "hour": 12},
        {"section": "bolsas", "weekday": 0, "hour": 7},
        {"section": "analise", "weekday": 6, "hour": 18},
    ]
    grid = schedules.rows_to_grid(rows)
    assert grid == {"bolsas": {"0": [7, 12]}, "analise": {"6": [18]}}


@pytest.mark.unit
def test_roundtrip_grid_rows_grid():
    grid = {"politica": {"0": [12], "2": [7, 19]}}
    rows = schedules.grid_to_rows("p", grid)
    back = schedules.rows_to_grid([{k: r[k] for k in ("section", "weekday", "hour")} for r in rows])
    assert back == grid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_schedules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.schedules'`

- [ ] **Step 3: Create `schedules.py`**

```python
# backend/services/schedules.py
from backend.services.supabase import _client, _f


def grid_to_rows(phone: str, schedule: dict) -> list[dict]:
    rows: list[dict] = []
    for section, days in (schedule or {}).items():
        for weekday, hours in (days or {}).items():
            for hour in hours:
                rows.append({
                    "phone": phone, "section": section,
                    "weekday": int(weekday), "hour": int(hour),
                })
    return rows


def rows_to_grid(rows: list[dict]) -> dict:
    grid: dict = {}
    for r in rows:
        grid.setdefault(r["section"], {}).setdefault(str(r["weekday"]), []).append(r["hour"])
    for section in grid:
        for wd in grid[section]:
            grid[section][wd] = sorted(set(grid[section][wd]))
    return grid


def due_now(weekday: int, hour: int) -> list[dict]:
    with _client() as c:
        r = c.get(f"/report_schedules?weekday=eq.{int(weekday)}&hour=eq.{int(hour)}&select=phone,section")
        r.raise_for_status()
        return r.json()


def get_for_phone(phone: str) -> list[dict]:
    with _client() as c:
        r = c.get(f"/report_schedules?phone=eq.{_f(phone)}&select=section,weekday,hour")
        r.raise_for_status()
        return r.json()


def replace_for_phone(phone: str, rows: list[dict]) -> None:
    with _client() as c:
        d = c.delete(f"/report_schedules?phone=eq.{_f(phone)}")
        d.raise_for_status()
        if rows:
            p = c.post("/report_schedules", json=rows)
            p.raise_for_status()


def set_engine_flag(phone: str, enabled: bool) -> None:
    with _client() as c:
        r = c.patch(f"/authorized_users?phone=eq.{_f(phone)}",
                    json={"use_new_report_engine": bool(enabled)})
        r.raise_for_status()


def phones_with_engine_enabled() -> set[str]:
    with _client() as c:
        r = c.get("/authorized_users?use_new_report_engine=is.true&select=phone")
        r.raise_for_status()
        return {row["phone"] for row in r.json()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_schedules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/schedules.py backend/tests/test_schedules.py
git commit -m "feat: add report_schedules service (grid transforms + PostgREST wrappers)"
```

---

### Task 3: Auth de cron compartilhada (`cron_auth.py`)

**Files:**
- Create: `backend/api/cron_auth.py`
- Modify: `backend/api/check_alerts.py:13-20`
- Test: `backend/tests/test_cron_auth.py`

**Interfaces:**
- Produces: `cron_auth.check_cron_secret(request: Request) -> None` (raise `HTTPException` 503 sem `CRON_SECRET`, 401 se segredo ausente/errado; aceita `Authorization: Bearer <s>` ou header `x-cron-secret: <s>`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cron_auth.py
import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)
_SECRET = "test-cron-secret"


@pytest.mark.unit
def test_check_alerts_accepts_bearer():
    with patch("backend.services.alert_checker.run_checks", return_value={"status": "ok"}), \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/check-alerts", headers={"Authorization": f"Bearer {_SECRET}"})
    assert r.status_code == 200


@pytest.mark.unit
def test_check_alerts_accepts_x_cron_secret():
    with patch("backend.services.alert_checker.run_checks", return_value={"status": "ok"}), \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/check-alerts", headers={"x-cron-secret": _SECRET})
    assert r.status_code == 200


@pytest.mark.unit
def test_check_alerts_rejects_missing_secret():
    with patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/check-alerts")
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_cron_auth.py -v`
Expected: FAIL — `test_check_alerts_accepts_bearer` falha com 401 (check_alerts ainda só aceita `x-cron-secret`).

- [ ] **Step 3: Create `cron_auth.py`**

```python
# backend/api/cron_auth.py
import hmac
import os

from fastapi import HTTPException, Request


def check_cron_secret(request: Request) -> None:
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    auth = request.headers.get("authorization", "")
    bearer = auth[7:] if auth[:7].lower() == "bearer " else ""
    provided = request.headers.get("x-cron-secret", "") or bearer
    if not provided or not hmac.compare_digest(provided, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
```

- [ ] **Step 4: Update `check_alerts.py` to use it**

Substitua o bloco de verificação (linhas ~13-20) por:

```python
from backend.api.cron_auth import check_cron_secret


@router.get("/api/check-alerts")
async def check_alerts(request: Request, test: bool = False):
    check_cron_secret(request)
    try:
        result = alert_checker.run_checks(test_mode=test)
        return result
    except Exception as e:
        logger.exception("check_alerts failed")
        try:
            alert_checker.notify_admin([f"fatal: {e}"])
        except Exception:
            logger.exception("admin notify failed")
        return {"status": "error", "detail": str(e)}
```

Remova os imports agora não usados em `check_alerts.py` (`hmac`, `os`, `HTTPException`) se não forem mais referenciados.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_cron_auth.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/cron_auth.py backend/api/check_alerts.py backend/tests/test_cron_auth.py
git commit -m "feat: shared cron auth accepting Vercel Bearer and x-cron-secret"
```

---

### Task 4: Dispatcher `/api/cron/report` reescrito + crons

**Files:**
- Rewrite: `backend/api/cron_report.py`
- Modify: `vercel.json`
- Test (rewrite): `backend/tests/test_cron_report.py`

**Interfaces:**
- Consumes: `cron_auth.check_cron_secret`; `schedules.due_now`, `schedules.phones_with_engine_enabled`; `supabase.get_authorized_by_phone`; `report_engine.generate_sections`; `whatsapp.send_message`.
- Produces: `GET /api/cron/report` → `{status, weekday, hour, users, sent, failed}`.

- [ ] **Step 1: Write the failing test (rewrite the file)**

```python
# backend/tests/test_cron_report.py
import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)
_SECRET = "test-cron-secret"


def _due(rows, enabled):
    return (
        patch("backend.api.cron_report.schedules.due_now", return_value=rows),
        patch("backend.api.cron_report.schedules.phones_with_engine_enabled", return_value=set(enabled)),
    )


@pytest.mark.unit
def test_cron_report_sem_agendamento_retorna_zero():
    p1, p2 = _due([], [])
    with p1, p2, patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    assert r.status_code == 200
    assert r.json()["sent"] == 0


@pytest.mark.unit
def test_cron_report_envia_secoes_agrupadas_por_usuario():
    rows = [
        {"phone": "5534999945010", "section": "commodities"},
        {"phone": "5534999945010", "section": "bolsas"},
    ]
    p1, p2 = _due(rows, ["5534999945010"])
    with p1, p2, \
         patch("backend.api.cron_report.supabase.get_authorized_by_phone",
               return_value={"phone": "5534999945010", "name": "Matheus"}), \
         patch("backend.api.cron_report.report_engine.generate_sections",
               return_value=["MSG-A", "MSG-B"]) as gen, \
         patch("backend.api.cron_report.whatsapp.send_message") as send, \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    assert r.status_code == 200
    body = r.json()
    assert body["users"] == 1 and body["sent"] == 1
    # gerou com as duas seções marcadas
    called_sections = gen.call_args.args[0]
    assert called_sections == {"commodities": True, "bolsas": True}
    # enviou as 2 mensagens
    assert send.call_count == 2


@pytest.mark.unit
def test_cron_report_filtra_quem_nao_tem_flag():
    rows = [{"phone": "999", "section": "bolsas"}]
    p1, p2 = _due(rows, [])  # ninguém habilitado
    with p1, p2, \
         patch("backend.api.cron_report.report_engine.generate_sections") as gen, \
         patch("backend.api.cron_report.whatsapp.send_message") as send, \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    assert r.json()["users"] == 0
    gen.assert_not_called()
    send.assert_not_called()


@pytest.mark.unit
def test_cron_report_isola_falha_de_usuario():
    rows = [{"phone": "A", "section": "bolsas"}, {"phone": "B", "section": "bolsas"}]
    p1, p2 = _due(rows, ["A", "B"])

    def gen(sections, user, **k):
        if user["phone"] == "A":
            raise RuntimeError("claude down")
        return ["ok"]

    with p1, p2, \
         patch("backend.api.cron_report.supabase.get_authorized_by_phone",
               side_effect=lambda p: {"phone": p, "name": ""}), \
         patch("backend.api.cron_report.report_engine.generate_sections", side_effect=gen), \
         patch("backend.api.cron_report.whatsapp.send_message"), \
         patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report", headers={"x-cron-secret": _SECRET})
    body = r.json()
    assert body["sent"] == 1 and body["failed"] == 1


@pytest.mark.unit
def test_cron_report_sem_segredo_401():
    with patch.dict(os.environ, {"CRON_SECRET": _SECRET}):
        r = client.get("/api/cron/report")
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_cron_report.py -v`
Expected: FAIL — `AttributeError`/import: `cron_report` ainda referencia `get_users_for_hour`/`reporter` e não tem `schedules`.

- [ ] **Step 3: Rewrite `cron_report.py`**

```python
# backend/api/cron_report.py
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request

from backend.api.cron_auth import check_cron_secret
from backend.services import report_engine, whatsapp, supabase, schedules

logger = logging.getLogger("noticiasgg")
router = APIRouter()

_BRT = timezone(timedelta(hours=-3))


@router.get("/api/cron/report")
async def cron_report(request: Request):
    check_cron_secret(request)

    now = datetime.now(_BRT)
    weekday, hour = now.weekday(), now.hour

    rows = schedules.due_now(weekday, hour)
    enabled = schedules.phones_with_engine_enabled()

    by_phone: dict[str, list[str]] = {}
    for r in rows:
        if r["phone"] in enabled:
            by_phone.setdefault(r["phone"], []).append(r["section"])

    sent = failed = 0
    for phone, sections in by_phone.items():
        try:
            user = supabase.get_authorized_by_phone(phone) or {"phone": phone, "name": ""}
            messages = report_engine.generate_sections({s: True for s in sections}, user)
            for msg in messages:
                whatsapp.send_message(phone, msg)
            sent += 1
        except Exception:
            logger.exception("cron_report falhou para %s", phone)
            failed += 1

    return {"status": "ok", "weekday": weekday, "hour": hour,
            "users": len(by_phone), "sent": sent, "failed": failed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_cron_report.py -v`
Expected: PASS

- [ ] **Step 5: Add crons to `vercel.json`**

Troque `"crons": []` por:

```json
  "crons": [
    { "path": "/api/cron/report",  "schedule": "0 * * * *" },
    { "path": "/api/check-alerts", "schedule": "*/15 * * * *" }
  ]
```

- [ ] **Step 6: Commit**

```bash
git add backend/api/cron_report.py backend/tests/test_cron_report.py vercel.json
git commit -m "feat: rewrite report cron dispatcher (schedules + flag + new engine) and enable Vercel crons"
```

---

### Task 5: Endpoints admin de schedule

**Files:**
- Modify: `backend/api/admin.py`
- Test: `backend/tests/test_schedules_admin.py`

**Interfaces:**
- Consumes: `schedules.get_for_phone`, `schedules.rows_to_grid`, `schedules.phones_with_engine_enabled`, `schedules.grid_to_rows`, `schedules.replace_for_phone`, `schedules.set_engine_flag`; `auth.verify_supabase_jwt`.
- Produces: `GET /api/admin/schedules/{phone}` → `{use_new_engine: bool, schedule: dict}`; `PUT /api/admin/schedules/{phone}` (body `{use_new_engine: bool, schedule: dict}`) → `{ok: true}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_schedules_admin.py
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.services import auth, schedules

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.verify_supabase_jwt] = lambda: {"sub": "admin"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_schedules_builds_grid(monkeypatch):
    monkeypatch.setattr(schedules, "get_for_phone",
                        lambda phone: [{"section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(schedules, "phones_with_engine_enabled", lambda: {"555"})
    r = client.get("/api/admin/schedules/555")
    assert r.status_code == 200
    assert r.json() == {"use_new_engine": True, "schedule": {"bolsas": {"0": [7]}}}


@pytest.mark.unit
def test_put_schedules_replaces_and_sets_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(schedules, "grid_to_rows",
                        lambda phone, grid: [{"phone": phone, "section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(schedules, "replace_for_phone",
                        lambda phone, rows: captured.update(rows=rows, phone=phone))
    monkeypatch.setattr(schedules, "set_engine_flag",
                        lambda phone, enabled: captured.update(flag=enabled))
    r = client.put("/api/admin/schedules/555",
                   json={"use_new_engine": True, "schedule": {"bolsas": {"0": [7]}}})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["phone"] == "555"
    assert captured["flag"] is True
    assert captured["rows"][0]["section"] == "bolsas"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_schedules_admin.py -v`
Expected: FAIL — 404 (rotas inexistentes).

- [ ] **Step 3: Add endpoints to `admin.py`**

No topo, inclua `schedules` no import existente:
```python
from backend.services import reporter, auth, supabase, report_engine, schedules
```

Adicione ao fim do arquivo:
```python
class ScheduleBody(BaseModel):
    use_new_engine: bool = False
    schedule: dict = {}


@router.get("/api/admin/schedules/{phone}")
def get_schedules(phone: str, user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    rows = schedules.get_for_phone(phone)
    enabled = schedules.phones_with_engine_enabled()
    return {"use_new_engine": phone in enabled, "schedule": schedules.rows_to_grid(rows)}


@router.put("/api/admin/schedules/{phone}")
def put_schedules(phone: str, body: ScheduleBody,
                  user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    rows = schedules.grid_to_rows(phone, body.schedule)
    schedules.replace_for_phone(phone, rows)
    schedules.set_engine_flag(phone, body.use_new_engine)
    return {"ok": True}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_schedules_admin.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/admin.py backend/tests/test_schedules_admin.py
git commit -m "feat: admin endpoints to read/write per-user report schedule + engine flag"
```

---

### Task 6: Grade no painel (frontend)

**Files:**
- Modify: `frontend/lib/config.ts`
- Modify: `frontend/components/users-manager.tsx`

**Interfaces:**
- Consumes: `GET`/`PUT /api/admin/schedules/{phone}`.
- Produces: `fetchSchedule(phone) -> {use_new_engine, schedule}`; `saveSchedule(phone, body) -> void`; UI da grade no card do usuário.

- [ ] **Step 1: Add client functions to `config.ts`**

Ao fim de `frontend/lib/config.ts`:
```typescript
export type ScheduleGrid = Record<string, Record<string, number[]>>;

export type ScheduleResponse = {
  use_new_engine: boolean;
  schedule: ScheduleGrid;
};

export async function fetchSchedule(phone: string): Promise<ScheduleResponse> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/schedules/${encodeURIComponent(phone)}`,
    { headers: { Authorization: `Bearer ${session?.access_token}` }, cache: "no-store" },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return res.json();
}

export async function saveSchedule(
  phone: string,
  body: { use_new_engine: boolean; schedule: ScheduleGrid },
): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/schedules/${encodeURIComponent(phone)}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session?.access_token}`,
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}
```

- [ ] **Step 2: Add the schedule grid to `users-manager.tsx`**

No import do topo, acrescente `fetchSchedule, saveSchedule` e o tipo:
```typescript
import { saveUserPrefs, resetUserPrefs, previewReport, fetchSchedule, saveSchedule } from "@/lib/config";
```

Adicione, antes do `export default function UsersManager`, o componente da grade. Usa as **chaves do motor novo** e dias seg–dom (0-6). Cada célula é um input de texto (horas separadas por vírgula); ao salvar, faz parse pra int 0-23.

```typescript
import { useEffect } from "react";

const ENGINE_SECTIONS: [string, string][] = [
  ["commodities", "Commodities"],
  ["bolsas", "Bolsas"],
  ["cambio_cripto", "Câmbio/Cripto"],
  ["noticias", "Notícias"],
  ["analise", "Análise"],
  ["politica", "Política"],
];
const WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]; // índice = weekday 0-6

function parseHours(raw: string): number[] {
  const seen = new Set<number>();
  for (const part of raw.split(",")) {
    const n = parseInt(part.trim(), 10);
    if (Number.isInteger(n) && n >= 0 && n <= 23) seen.add(n);
  }
  return [...seen].sort((a, b) => a - b);
}

function ScheduleGridEditor({ phone }: { phone: string }) {
  // cells[section][weekday] = texto bruto digitado (ex "7,12")
  const [cells, setCells] = useState<Record<string, Record<number, string>>>({});
  const [useNew, setUseNew] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchSchedule(phone).then((res) => {
      if (!alive) return;
      const next: Record<string, Record<number, string>> = {};
      for (const [sec] of ENGINE_SECTIONS) {
        next[sec] = {};
        for (let wd = 0; wd < 7; wd++) {
          const hours = res.schedule?.[sec]?.[String(wd)] ?? [];
          next[sec][wd] = hours.join(",");
        }
      }
      setCells(next);
      setUseNew(res.use_new_engine);
    }).catch(() => setStatus("Erro ao carregar agendamento."));
    return () => { alive = false; };
  }, [phone]);

  function setCell(sec: string, wd: number, value: string) {
    setCells((c) => ({ ...c, [sec]: { ...c[sec], [wd]: value } }));
  }

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    const schedule: Record<string, Record<string, number[]>> = {};
    for (const [sec] of ENGINE_SECTIONS) {
      for (let wd = 0; wd < 7; wd++) {
        const hours = parseHours(cells[sec]?.[wd] ?? "");
        if (hours.length) {
          schedule[sec] = schedule[sec] ?? {};
          schedule[sec][String(wd)] = hours;
        }
      }
    }
    try {
      await saveSchedule(phone, { use_new_engine: useNew, schedule });
      setStatus("Agendamento salvo.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-line bg-surface p-5">
      <h2 className="mb-3 font-display text-sm font-medium uppercase tracking-wide text-slate">
        Agendamento (motor novo)
      </h2>
      <label className="mb-4 flex items-center gap-2 text-sm text-bone">
        <input type="checkbox" checked={useNew} onChange={() => setUseNew((v) => !v)} />
        Usar motor novo para este usuário
      </label>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="p-1 text-left text-xs text-slate"></th>
              {WEEKDAYS.map((d) => (
                <th key={d} className="p-1 text-xs font-normal text-slate">{d}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ENGINE_SECTIONS.map(([sec, label]) => (
              <tr key={sec}>
                <td className="p-1 pr-3 text-xs text-bone">{label}</td>
                {WEEKDAYS.map((_, wd) => (
                  <td key={wd} className="p-1">
                    <input
                      value={cells[sec]?.[wd] ?? ""}
                      onChange={(e) => setCell(sec, wd, e.target.value)}
                      placeholder="—"
                      className="w-14 rounded border border-line bg-ink px-1 py-1 text-center text-xs text-bone"
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate">Horas BRT separadas por vírgula (ex: 7,12). Vazio = não envia.</p>
      {status && <p className="mt-2 text-sm text-gold">{status}</p>}
      <button onClick={save} disabled={busy}
        className="mt-3 rounded-md bg-gold px-4 py-2 font-medium text-ink hover:bg-bone disabled:opacity-50">
        Salvar agendamento
      </button>
    </section>
  );
}
```

Por fim, renderize a grade dentro do `UserForm` (no JSX de `UserForm`, após a `<section>` de Áudio e antes do `{status && ...}`):
```typescript
      <ScheduleGridEditor phone={user.phone} />
```

- [ ] **Step 3: Typecheck e lint**

Run:
```bash
cd "c:/Users/Dib/Projetos/pessoal/noticiasgg/frontend" && npx tsc --noEmit && npx eslint lib/config.ts components/users-manager.tsx
```
Expected: ambos exit 0 (sem erros).

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/config.ts frontend/components/users-manager.tsx
git commit -m "feat: per-user report schedule grid (section x weekday) + new-engine toggle in panel"
```

---

## Self-Review

**1. Spec coverage:**
- Tabela `report_schedules` + flag → Task 1. ✓
- Serviço de acesso + transforms grade↔linhas → Task 2. ✓
- Auth cron dupla (Bearer/x-cron-secret) compartilhada → Task 3. ✓
- Dispatcher reescrito (BRT, flag, motor novo, isolamento de falha) → Task 4. ✓
- Crons no vercel.json (report 1h + check-alerts 15min) → Task 4 (Step 5). ✓
- Endpoints admin GET/PUT schedules → Task 5. ✓
- Grade tabela seção×dia + toggle no painel → Task 6. ✓
- Check Alerts ligado no cron Vercel (mesma infra) → Task 3 (auth) + Task 4 (vercel.json). Desligar n8n é manual (fora de escopo). ✓
- Paralelo via flag → flag em Task 1/2, filtro no dispatcher Task 4, toggle no painel Task 6. ✓
- Não tocar report_engine/reporter/main.py → respeitado (só cron_report, check_alerts, admin, schedules, frontend). ✓

**2. Placeholder scan:** Sem "TBD/TODO/etc". Todo passo com código real ou comando exato.

**3. Type consistency:** `weekday` int 0-6 em tudo; grade JSON usa weekday **string** ("0".."6") consistente entre `grid_to_rows`/`rows_to_grid`/endpoints/frontend. `due_now -> [{phone,section}]`, `phones_with_engine_enabled -> set`, `generate_sections({sec:True}, user)` casa com a assinatura do item 1. Endpoints `{use_new_engine, schedule}` idênticos entre backend e `fetchSchedule`/`saveSchedule`/UI.
