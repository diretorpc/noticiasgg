# Link self-service por usuário (Trilho 2 B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cada usuário edita a própria config (grade de agendamento, seções do chat, áudio) por um link `/me?token=…` sem login; admin gera/revoga o link no painel.

**Architecture:** Token opaco aleatório por usuário em `authorized_users.selflink_token`. Endpoints `/api/me*` resolvem o telefone pelo token (nunca por input). Admin gera/revoga via endpoints JWT. Frontend ganha página pública `/me` e botões de link no painel; a grade de agendamento vira componente compartilhado.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend); Next.js App Router / React / TypeScript / Tailwind (frontend); Supabase PostgREST.

## Global Constraints

- Endpoints `/api/me*` derivam o telefone **sempre** do token (dependência `selflink.selflink_phone`), nunca de parâmetro do cliente. Impossível acessar outro telefone.
- Endpoints admin (`/api/admin/*`) seguem `Depends(auth.verify_supabase_jwt)`.
- O `/me` **não** altera `use_new_report_engine` (flag é admin-only) nem `report_time` (preserva o valor atual).
- Token = `secrets.token_urlsafe(32)` (≈256 bits), opaco, guardado em `authorized_users.selflink_token`. Revogar = setar null. Regenerar = sobrescrever.
- Testes unit: `@pytest.mark.unit`; monkeypatch na camada de serviço (supabase/schedules/selflink); wrappers PostgREST crus sem teste unit dedicado (padrão `replace_for_phone`). Auth/token bypass via `app.dependency_overrides`.
- Gate CI: `pytest -m unit`. Frontend: `npx tsc --noEmit` limpo.
- Frontend: seguir padrões existentes; NÃO introduzir APIs novas do Next (ver `frontend/AGENTS.md`). A página `/me` lê o token via `window.location` (client component).
- Env nova: `PANEL_BASE_URL` (default `https://noticiasgg.vercel.app`) — adicionar na Vercel. Sem segredo novo.
- Deploy = `git push` na master (não pushar sem o usuário pedir). Se o push não disparar deploy, refazer com `git commit --allow-empty` (webhook Vercel às vezes falha).

---

### Task 1: Backend — storage do token + serviço selflink

**Files:**
- Modify: `backend/services/supabase.py` (3 funções no fim)
- Create: `backend/services/selflink.py`
- Test: `backend/tests/test_selflink.py`

**Interfaces:**
- Produces:
  - `supabase.set_selflink_token(phone: str) -> str`
  - `supabase.clear_selflink_token(phone: str) -> None`
  - `supabase.get_by_selflink_token(token: str) -> dict | None`
  - `selflink.resolve_phone(token: str | None) -> str` (levanta `HTTPException(401)`)
  - `selflink.selflink_phone(token: str | None = Query(default=None)) -> str` (dependência FastAPI)

- [ ] **Step 1: Migration manual no Supabase**

No SQL editor do Supabase, rodar (uma vez):

```sql
ALTER TABLE authorized_users ADD COLUMN IF NOT EXISTS selflink_token text;
CREATE UNIQUE INDEX IF NOT EXISTS authorized_users_selflink_token_key
  ON authorized_users (selflink_token) WHERE selflink_token IS NOT NULL;
```

Confirmar que a coluna existe antes de seguir. (Não há teste automatizado para isso.)

- [ ] **Step 2: Escrever o teste que falha**

Criar `backend/tests/test_selflink.py`:

```python
import pytest
from fastapi import HTTPException

from backend.services import selflink, supabase


@pytest.mark.unit
def test_resolve_phone_valid_token(monkeypatch):
    monkeypatch.setattr(supabase, "get_by_selflink_token",
                        lambda tok: {"phone": "5534999945010", "name": "Matheus"})
    assert selflink.resolve_phone("abc123") == "5534999945010"


@pytest.mark.unit
def test_resolve_phone_none_or_empty_raises():
    for bad in (None, "", "   "):
        with pytest.raises(HTTPException) as ei:
            selflink.resolve_phone(bad)
        assert ei.value.status_code == 401


@pytest.mark.unit
def test_resolve_phone_unknown_token_raises(monkeypatch):
    monkeypatch.setattr(supabase, "get_by_selflink_token", lambda tok: None)
    with pytest.raises(HTTPException) as ei:
        selflink.resolve_phone("nope")
    assert ei.value.status_code == 401


@pytest.mark.unit
def test_get_by_selflink_token_empty_short_circuits():
    # token vazio não deve consultar o banco (evita casar com nulls); retorna None
    assert supabase.get_by_selflink_token("") is None
    assert supabase.get_by_selflink_token(None) is None
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `python -m pytest backend/tests/test_selflink.py -m unit -v`
Expected: FAIL (`AttributeError`: `selflink`/funções inexistentes).

- [ ] **Step 4: Implementar storage em `supabase.py`**

Ao final de `backend/services/supabase.py` (já tem `import` de `os`, `httpx`, `quote`; adicionar `import secrets` no topo junto aos outros imports):

```python
def set_selflink_token(phone: str) -> str:
    token = secrets.token_urlsafe(32)
    with _client() as c:
        r = c.patch(f"/authorized_users?phone=eq.{_f(phone)}",
                    json={"selflink_token": token})
        r.raise_for_status()
    return token


def clear_selflink_token(phone: str) -> None:
    with _client() as c:
        r = c.patch(f"/authorized_users?phone=eq.{_f(phone)}",
                    json={"selflink_token": None})
        r.raise_for_status()


def get_by_selflink_token(token: str) -> dict | None:
    if not token or not str(token).strip():
        return None
    with _client() as c:
        r = c.get(f"/authorized_users?selflink_token=eq.{_f(token)}&select=*")
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None
```

Adicionar `import secrets` no bloco de imports do topo de `supabase.py`.

- [ ] **Step 5: Implementar `selflink.py`**

Criar `backend/services/selflink.py`:

```python
from fastapi import HTTPException, Query

from backend.services import supabase


def resolve_phone(token: str | None) -> str:
    if not token or not str(token).strip():
        raise HTTPException(status_code=401, detail="missing token")
    user = supabase.get_by_selflink_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="invalid or revoked token")
    return user["phone"]


def selflink_phone(token: str | None = Query(default=None)) -> str:
    return resolve_phone(token)
```

- [ ] **Step 6: Rodar e ver passar**

Run: `python -m pytest backend/tests/test_selflink.py -m unit -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/supabase.py backend/services/selflink.py backend/tests/test_selflink.py
git commit -m "feat(backend): selflink token storage + resolver"
```

---

### Task 2: Backend — endpoints admin de gerar/revogar link

**Files:**
- Modify: `backend/api/admin.py` (2 endpoints no fim)
- Test: `backend/tests/test_admin_selflink.py`

**Interfaces:**
- Consumes: `supabase.set_selflink_token`, `supabase.clear_selflink_token`, `supabase.get_authorized_by_phone`.
- Produces:
  - `POST /api/admin/selflink/{phone}` → `{"url": str, "token": str}`
  - `DELETE /api/admin/selflink/{phone}` → `{"ok": True}`

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/test_admin_selflink.py`:

```python
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth, supabase

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.verify_supabase_jwt] = lambda: {"sub": "admin"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_generate_selflink(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "name": "G.Mouro"})
    monkeypatch.setattr(supabase, "set_selflink_token", lambda phone: "TOK123")
    monkeypatch.setenv("PANEL_BASE_URL", "https://painel.example.com")
    r = client.post("/api/admin/selflink/5516991016898")
    assert r.status_code == 200
    assert r.json() == {"url": "https://painel.example.com/me?token=TOK123", "token": "TOK123"}


@pytest.mark.unit
def test_generate_selflink_unknown_phone(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone", lambda phone: None)
    r = client.post("/api/admin/selflink/000")
    assert r.status_code == 404


@pytest.mark.unit
def test_revoke_selflink(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase, "clear_selflink_token", lambda phone: captured.update(phone=phone))
    r = client.delete("/api/admin/selflink/5516991016898")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert captured["phone"] == "5516991016898"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest backend/tests/test_admin_selflink.py -m unit -v`
Expected: FAIL (404 nas rotas inexistentes).

- [ ] **Step 3: Implementar os endpoints**

Ao final de `backend/api/admin.py` (já importa `os`, `supabase`, `HTTPException`, `auth`):

```python
@router.post("/api/admin/selflink/{phone}")
def generate_selflink(phone: str, user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    if not supabase.get_authorized_by_phone(phone):
        raise HTTPException(status_code=404, detail="usuário não encontrado")
    token = supabase.set_selflink_token(phone)
    base = os.environ.get("PANEL_BASE_URL", "https://noticiasgg.vercel.app").rstrip("/")
    return {"url": f"{base}/me?token={token}", "token": token}


@router.delete("/api/admin/selflink/{phone}")
def revoke_selflink(phone: str, user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    supabase.clear_selflink_token(phone)
    return {"ok": True}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest backend/tests/test_admin_selflink.py -m unit -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/api/admin.py backend/tests/test_admin_selflink.py
git commit -m "feat(backend): admin endpoints to generate/revoke selflink"
```

---

### Task 3: Backend — endpoints /api/me (router escopado por token)

**Files:**
- Create: `backend/api/me.py`
- Modify: `backend/api/main.py` (import + include_router)
- Test: `backend/tests/test_me.py`

**Interfaces:**
- Consumes: `selflink.selflink_phone`, `supabase.get_authorized_by_phone`, `supabase.get_preferences`, `supabase.save_preferences`, `schedules.get_for_phone`, `schedules.rows_to_grid`, `schedules.grid_to_rows`, `schedules.replace_for_phone`.
- Produces (router em `me.py`, montado em `main.py`):
  - `GET /api/me?token=…` → `{name, schedule, sections, audio}`
  - `PUT /api/me?token=…` body `{sections, audio_for_text, audio_for_media, tts_voice, tts_speed}` → `{ok: True}`
  - `PUT /api/me/schedule?token=…` body `{schedule}` → `{ok: True}`

- [ ] **Step 1: Escrever o teste que falha**

Criar `backend/tests/test_me.py`:

```python
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import selflink, supabase, schedules

client = TestClient(app)

PHONE = "5534999945010"


@pytest.fixture(autouse=True)
def _bypass_token():
    app.dependency_overrides[selflink.selflink_phone] = lambda: PHONE
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_me_returns_scoped_bundle(monkeypatch):
    monkeypatch.setattr(supabase, "get_authorized_by_phone",
                        lambda phone: {"phone": phone, "name": "Matheus"})
    monkeypatch.setattr(schedules, "get_for_phone",
                        lambda phone: [{"section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(supabase, "get_preferences",
                        lambda phone: {"sections": {"market": True}, "report_time": "enabled",
                                       "audio_for_text": True, "audio_for_media": False,
                                       "tts_voice": "nova", "tts_speed": 0.85})
    r = client.get("/api/me?token=x")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Matheus"
    assert body["schedule"] == {"bolsas": {"0": [7]}}
    assert body["sections"] == {"market": True}
    assert body["audio"] == {"audio_for_text": True, "audio_for_media": False,
                             "tts_voice": "nova", "tts_speed": 0.85}


@pytest.mark.unit
def test_put_me_preserves_report_time(monkeypatch):
    monkeypatch.setattr(supabase, "get_preferences", lambda phone: {"report_time": "enabled"})
    captured = {}
    monkeypatch.setattr(supabase, "save_preferences",
                        lambda phone, **kw: captured.update(phone=phone, **kw))
    r = client.put("/api/me?token=x", json={"sections": {"market": True},
                                            "audio_for_text": True, "audio_for_media": False,
                                            "tts_voice": "nova", "tts_speed": 0.85})
    assert r.status_code == 200
    assert captured["phone"] == PHONE
    assert captured["report_time"] == "enabled"
    assert captured["sections"] == {"market": True}


@pytest.mark.unit
def test_put_me_schedule_replaces_without_touching_engine_flag(monkeypatch):
    captured = {}
    monkeypatch.setattr(schedules, "grid_to_rows",
                        lambda phone, grid: [{"phone": phone, "section": "bolsas", "weekday": 0, "hour": 7}])
    monkeypatch.setattr(schedules, "replace_for_phone",
                        lambda phone, rows: captured.update(rows=rows, phone=phone))

    def _boom(*a, **k):
        raise AssertionError("set_engine_flag não deve ser chamado pelo /me")

    monkeypatch.setattr(schedules, "set_engine_flag", _boom)
    r = client.put("/api/me/schedule?token=x", json={"schedule": {"bolsas": {"0": [7]}}})
    assert r.status_code == 200
    assert captured["phone"] == PHONE
    assert captured["rows"][0]["section"] == "bolsas"


@pytest.mark.unit
def test_me_requires_valid_token():
    # sem o override de dependência, token inválido → 401
    app.dependency_overrides.clear()
    r = client.get("/api/me")
    assert r.status_code == 401
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest backend/tests/test_me.py -m unit -v`
Expected: FAIL (404/router inexistente).

- [ ] **Step 3: Implementar `me.py`**

Criar `backend/api/me.py`:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.services import selflink, supabase, schedules

router = APIRouter()


@router.get("/api/me")
def get_me(phone: str = Depends(selflink.selflink_phone)) -> dict:
    user = supabase.get_authorized_by_phone(phone) or {"phone": phone, "name": ""}
    prefs = supabase.get_preferences(phone) or {}
    grid = schedules.rows_to_grid(schedules.get_for_phone(phone))
    return {
        "name": user.get("name") or "",
        "schedule": grid,
        "sections": prefs.get("sections"),
        "audio": {
            "audio_for_text": prefs.get("audio_for_text"),
            "audio_for_media": prefs.get("audio_for_media"),
            "tts_voice": prefs.get("tts_voice"),
            "tts_speed": prefs.get("tts_speed"),
        },
    }


class MePrefsBody(BaseModel):
    sections: dict | None = None
    audio_for_text: bool | None = None
    audio_for_media: bool | None = None
    tts_voice: str | None = None
    tts_speed: float | None = None


@router.put("/api/me")
def put_me(body: MePrefsBody, phone: str = Depends(selflink.selflink_phone)) -> dict:
    current = supabase.get_preferences(phone) or {}
    supabase.save_preferences(
        phone,
        sections=body.sections,
        report_time=current.get("report_time"),
        audio_for_text=body.audio_for_text,
        audio_for_media=body.audio_for_media,
        tts_voice=body.tts_voice,
        tts_speed=body.tts_speed,
    )
    return {"ok": True}


class MeScheduleBody(BaseModel):
    schedule: dict = {}


@router.put("/api/me/schedule")
def put_me_schedule(body: MeScheduleBody, phone: str = Depends(selflink.selflink_phone)) -> dict:
    rows = schedules.grid_to_rows(phone, body.schedule)
    schedules.replace_for_phone(phone, rows)
    return {"ok": True}
```

- [ ] **Step 4: Registrar o router em `main.py`**

Em `backend/api/main.py`, na linha de import (linha 13):

```python
from backend.api import send_report, cron_report, check_alerts, admin, me
```

E adicionar (junto aos outros `app.include_router(...)`, após `app.include_router(check_alerts.router)`):

```python
app.include_router(me.router)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest backend/tests/test_me.py -m unit -v`
Expected: PASS.

- [ ] **Step 6: Rodar o gate completo de unit**

Run: `python -m pytest -m unit -q`
Expected: PASS (52 anteriores + novos).

- [ ] **Step 7: Commit**

```bash
git add backend/api/me.py backend/api/main.py backend/tests/test_me.py
git commit -m "feat(backend): token-scoped /api/me endpoints (self-service)"
```

---

### Task 4: Frontend — clientes de API (admin selflink + me)

**Files:**
- Modify: `frontend/lib/config.ts` (`generateSelflink`, `revokeSelflink`)
- Create: `frontend/lib/selflink.ts` (`fetchMe`, `saveMePrefs`, `saveMeSchedule` + tipos)

**Interfaces:**
- Consumes: tipos `ScheduleGrid` de `lib/config`.
- Produces:
  - `lib/config.ts`: `generateSelflink(phone): Promise<{url:string}>`, `revokeSelflink(phone): Promise<void>`
  - `lib/selflink.ts`: `type MeData = {name:string; schedule?:ScheduleGrid; sections:Record<string,boolean>|null; audio:MeAudio}`; `fetchMe(token): Promise<MeData>`; `saveMePrefs(token, body): Promise<void>`; `saveMeSchedule(token, schedule): Promise<void>`

- [ ] **Step 1: Adicionar admin selflink em `lib/config.ts`**

Ao final de `frontend/lib/config.ts`:

```ts
export async function generateSelflink(phone: string): Promise<{ url: string }> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/selflink/${encodeURIComponent(phone)}`,
    { method: "POST", headers: { Authorization: `Bearer ${session?.access_token}` } },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return res.json();
}

export async function revokeSelflink(phone: string): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/selflink/${encodeURIComponent(phone)}`,
    { method: "DELETE", headers: { Authorization: `Bearer ${session?.access_token}` } },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}
```

- [ ] **Step 2: Criar `lib/selflink.ts`**

```ts
import type { ScheduleGrid } from "@/lib/config";

export type MeAudio = {
  audio_for_text: boolean | null;
  audio_for_media: boolean | null;
  tts_voice: string | null;
  tts_speed: number | null;
};

export type MeData = {
  name: string;
  schedule?: ScheduleGrid;
  sections: Record<string, boolean> | null;
  audio: MeAudio;
};

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL;

export async function fetchMe(token: string): Promise<MeData> {
  const res = await fetch(`${BACKEND}/api/me?token=${encodeURIComponent(token)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return res.json();
}

export async function saveMePrefs(
  token: string,
  body: { sections: Record<string, boolean> | null } & MeAudio,
): Promise<void> {
  const res = await fetch(`${BACKEND}/api/me?token=${encodeURIComponent(token)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function saveMeSchedule(token: string, schedule: ScheduleGrid): Promise<void> {
  const res = await fetch(`${BACKEND}/api/me/schedule?token=${encodeURIComponent(token)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ schedule }),
  });
  if (!res.ok) throw new Error(`backend ${res.status}`);
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0. (Se `ScheduleGrid` não for exportado de `lib/config`, conferir o `export type ScheduleGrid` existente lá.)

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/config.ts frontend/lib/selflink.ts
git commit -m "feat(painel): API clients for selflink (admin) and /me"
```

---

### Task 5: Frontend — extrair grade de agendamento compartilhada

**Files:**
- Create: `frontend/components/schedule-grid.tsx` (`ScheduleGridEditor` parametrizável)
- Modify: `frontend/components/users-manager.tsx` (usar o componente compartilhado, remover o inline)

**Interfaces:**
- Consumes: tipos `ScheduleGrid`, `ScheduleResponse` de `lib/config`; `fetchSchedule`, `saveSchedule` de `lib/config`.
- Produces: `ScheduleGridEditor({ load, save, showEngineToggle, reloadKey })` onde
  `load: () => Promise<{ schedule?: ScheduleGrid; use_new_engine: boolean }>`,
  `save: (args: { schedule: ScheduleGrid; use_new_engine: boolean }) => Promise<void>`,
  `showEngineToggle: boolean`, `reloadKey: string` (dep estável do efeito de carga —
  evita loop de refetch quando `load` é um arrow inline).

- [ ] **Step 1: Criar `components/schedule-grid.tsx`**

```tsx
"use client";

import { useState, useEffect } from "react";
import type { ScheduleGrid } from "@/lib/config";

const ENGINE_SECTIONS: [string, string][] = [
  ["commodities", "Commodities"],
  ["bolsas", "Bolsas"],
  ["cambio_cripto", "Câmbio/Cripto"],
  ["noticias", "Notícias"],
  ["analise", "Análise"],
  ["politica", "Política"],
];
const WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

function parseHours(raw: string): number[] {
  const seen = new Set<number>();
  for (const part of raw.split(",")) {
    const n = parseInt(part.trim(), 10);
    if (Number.isInteger(n) && n >= 0 && n <= 23) seen.add(n);
  }
  return [...seen].sort((a, b) => a - b);
}

export function ScheduleGridEditor({
  load,
  save,
  showEngineToggle,
  reloadKey,
}: {
  load: () => Promise<{ schedule?: ScheduleGrid; use_new_engine: boolean }>;
  save: (args: { schedule: ScheduleGrid; use_new_engine: boolean }) => Promise<void>;
  showEngineToggle: boolean;
  reloadKey: string;
}) {
  const [cells, setCells] = useState<Record<string, Record<number, string>>>({});
  const [useNew, setUseNew] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    load().then((res) => {
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
    // reloadKey é a dep estável; load é arrow inline (muda toda render) de propósito
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  function setCell(sec: string, wd: number, value: string) {
    setCells((c) => ({ ...c, [sec]: { ...c[sec], [wd]: value } }));
  }

  async function onSave() {
    setBusy(true);
    setStatus("Salvando…");
    const schedule: ScheduleGrid = {};
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
      await save({ use_new_engine: useNew, schedule });
      setStatus("Agendamento salvo.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">
        Agendamento
      </h2>
      {showEngineToggle && (
        <label className="mb-4 flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={useNew} onChange={() => setUseNew((v) => !v)} />
          Usar motor novo para este usuário
        </label>
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="p-1 text-left text-xs text-muted-foreground"></th>
              {WEEKDAYS.map((d) => (
                <th key={d} className="p-1 text-xs font-normal text-muted-foreground">{d}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ENGINE_SECTIONS.map(([sec, label]) => (
              <tr key={sec}>
                <td className="p-1 pr-3 text-xs text-foreground">{label}</td>
                {WEEKDAYS.map((_, wd) => (
                  <td key={wd} className="p-1">
                    <input
                      value={cells[sec]?.[wd] ?? ""}
                      onChange={(e) => setCell(sec, wd, e.target.value)}
                      placeholder="—"
                      className="w-14 rounded border border-border bg-input px-1 py-1 text-center text-xs text-foreground"
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">Horas BRT separadas por vírgula (ex: 7,12). Vazio = não envia.</p>
      {status && <p className="mt-2 text-sm text-primary">{status}</p>}
      <button onClick={onSave} disabled={busy}
        className="mt-3 rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
        Salvar agendamento
      </button>
    </section>
  );
}
```

- [ ] **Step 2: Trocar o inline em `users-manager.tsx` pelo compartilhado**

Em `frontend/components/users-manager.tsx`:
1. Remover a função inline `ScheduleGridEditor` (linhas ~27-124, da `function ScheduleGridEditor` até o `}` que a fecha) e as constantes/utilitários que só ela usava: `ENGINE_SECTIONS`, `WEEKDAYS`, `parseHours`.
2. Ajustar o import (linha 5) para parar de importar `fetchSchedule`/`saveSchedule` se não forem mais usados em outro lugar do arquivo — manter `saveUserPrefs, resetUserPrefs, previewReport`; e importar os dois ainda para passar ao componente:

```ts
import { saveUserPrefs, resetUserPrefs, previewReport, fetchSchedule, saveSchedule } from "@/lib/config";
import { ScheduleGridEditor } from "@/components/schedule-grid";
```

3. No `UserForm`, onde hoje há `<ScheduleGridEditor phone={user.phone} />`, trocar por:

```tsx
<ScheduleGridEditor
  showEngineToggle
  reloadKey={user.phone}
  load={() => fetchSchedule(user.phone)}
  save={(args) => saveSchedule(user.phone, args)}
/>
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0. Conferir que não sobrou referência a `parseHours`/`WEEKDAYS`/`ENGINE_SECTIONS` no `users-manager.tsx`.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/schedule-grid.tsx frontend/components/users-manager.tsx
git commit -m "refactor(painel): extract parametrizable ScheduleGridEditor"
```

---

### Task 6: Frontend — página pública /me + editor

**Files:**
- Create: `frontend/app/me/page.tsx`
- Create: `frontend/components/me-editor.tsx`

**Interfaces:**
- Consumes: `fetchMe`, `saveMePrefs`, `saveMeSchedule`, `MeData` de `lib/selflink`; `ScheduleGridEditor` de `components/schedule-grid`.

- [ ] **Step 1: Criar `app/me/page.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { fetchMe, type MeData } from "@/lib/selflink";
import { MeEditor } from "@/components/me-editor";

export default function MePage() {
  const [token, setToken] = useState<string | null>(null);
  const [data, setData] = useState<MeData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("token");
    if (!t) {
      setErr("Link inválido. Peça um novo ao administrador.");
      return;
    }
    setToken(t);
    // remove o token da URL (reduz vazamento em histórico/referrer)
    window.history.replaceState({}, "", "/me");
    fetchMe(t)
      .then(setData)
      .catch(() => setErr("Link inválido ou revogado. Peça um novo ao administrador."));
  }, []);

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <div className="mb-8">
        <span className="eyebrow">Minhas configurações</span>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">noticiasgg</h1>
      </div>
      {err && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{err}</p>}
      {!err && !data && <p className="text-sm text-muted-foreground">Carregando…</p>}
      {token && data && <MeEditor token={token} data={data} />}
    </main>
  );
}
```

- [ ] **Step 2: Criar `components/me-editor.tsx`**

```tsx
"use client";

import { useState } from "react";
import { ScheduleGridEditor } from "@/components/schedule-grid";
import { saveMePrefs, saveMeSchedule, type MeData } from "@/lib/selflink";

const SECTIONS: [string, string][] = [
  ["market", "Mercado"],
  ["crypto", "Cripto"],
  ["indicators_us", "Indicadores EUA"],
  ["indicators_br", "Indicadores BR"],
  ["news", "Notícias"],
  ["commodities_br", "Commodities"],
  ["politics_br", "Política"],
  ["polls_br", "Pesquisas"],
];
const VOICES = ["nova", "shimmer", "alloy", "echo", "fable", "onyx"];

function defaultSections(): Record<string, boolean> {
  return Object.fromEntries(SECTIONS.map(([k]) => [k, true]));
}

export function MeEditor({ token, data }: { token: string; data: MeData }) {
  const [sections, setSections] = useState<Record<string, boolean>>(data.sections ?? defaultSections());
  const [audioText, setAudioText] = useState(Boolean(data.audio.audio_for_text));
  const [audioMedia, setAudioMedia] = useState(Boolean(data.audio.audio_for_media));
  const [voice, setVoice] = useState(data.audio.tts_voice ?? "nova");
  const [speed, setSpeed] = useState(data.audio.tts_speed ?? 0.85);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function savePrefs() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      await saveMePrefs(token, {
        sections,
        audio_for_text: audioText,
        audio_for_media: audioMedia,
        tts_voice: voice,
        tts_speed: speed,
      });
      setStatus("Salvo.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {data.name && <p className="text-sm text-muted-foreground">Olá, {data.name.split(" ")[0]}!</p>}

      <ScheduleGridEditor
        showEngineToggle={false}
        reloadKey={token}
        load={() => Promise.resolve({ schedule: data.schedule, use_new_engine: false })}
        save={({ schedule }) => saveMeSchedule(token, schedule)}
      />

      <section className="rounded-lg border border-border bg-card p-5">
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-muted-foreground">Seções do chat</h2>
        <div className="grid grid-cols-2 gap-2">
          {SECTIONS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm text-foreground">
              <input type="checkbox" checked={sections[k] ?? false}
                onChange={() => setSections((s) => ({ ...s, [k]: !s[k] }))} />
              {label}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-border bg-card p-5 space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Áudio</h2>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={audioText} onChange={() => setAudioText((v) => !v)} />
          Responder textos em áudio
        </label>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={audioMedia} onChange={() => setAudioMedia((v) => !v)} />
          Responder mídias em áudio
        </label>
        <label className="block">
          <span className="eyebrow">Voz</span>
          <select value={voice} onChange={(e) => setVoice(e.target.value)}
            className="mt-1 block rounded-md border border-border bg-input px-3 py-2 text-sm text-foreground">
            {VOICES.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="eyebrow">Velocidade ({speed})</span>
          <input type="range" min={0.5} max={1.5} step={0.05} value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value))} className="mt-1 block w-full" />
        </label>
      </section>

      {status && <p className="text-sm text-primary">{status}</p>}
      <button onClick={savePrefs} disabled={busy}
        className="rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
        Salvar seções e áudio
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0.

Run: `cd frontend && npx next build`
Expected: build conclui; a rota `/me` aparece na lista.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/me/page.tsx frontend/components/me-editor.tsx
git commit -m "feat(painel): public /me self-service page (token-scoped)"
```

---

### Task 7: Frontend — botões de link no painel admin

**Files:**
- Modify: `frontend/components/users-manager.tsx` (botões Gerar/Revogar link no `UserForm`)

**Interfaces:**
- Consumes: `generateSelflink`, `revokeSelflink` de `lib/config`.

- [ ] **Step 1: Importar e adicionar estado + UI no `UserForm`**

Em `frontend/components/users-manager.tsx`, no import de `@/lib/config` adicionar `generateSelflink, revokeSelflink`:

```ts
import { saveUserPrefs, resetUserPrefs, previewReport, fetchSchedule, saveSchedule, generateSelflink, revokeSelflink } from "@/lib/config";
```

Dentro de `UserForm`, adicionar estado e handlers (perto dos outros `useState`):

```tsx
  const [linkUrl, setLinkUrl] = useState<string | null>(null);
  const [linkStatus, setLinkStatus] = useState<string | null>(null);

  async function genLink() {
    setLinkStatus("Gerando…");
    try {
      const { url } = await generateSelflink(user.phone);
      setLinkUrl(url);
      setLinkStatus("Link gerado. Copie e envie ao usuário.");
    } catch (e) {
      setLinkStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    }
  }

  async function revLink() {
    if (!window.confirm("Revogar o link atual? Quem tiver o link perde o acesso.")) return;
    setLinkStatus("Revogando…");
    try {
      await revokeSelflink(user.phone);
      setLinkUrl(null);
      setLinkStatus("Link revogado.");
    } catch (e) {
      setLinkStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    }
  }
```

E adicionar uma seção na UI do `UserForm` (antes do bloco de botões finais Salvar/Resetar):

```tsx
      <section className="rounded-lg border border-border bg-card p-5 space-y-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Link self-service</h2>
        <p className="text-xs text-muted-foreground">Gere um link para o usuário editar a própria config (grade, seções, áudio) sem login.</p>
        <div className="flex flex-wrap gap-3">
          <button onClick={genLink} type="button"
            className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Gerar link</button>
          <button onClick={revLink} type="button"
            className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground">Revogar</button>
        </div>
        {linkUrl && (
          <input readOnly value={linkUrl} onFocus={(e) => e.currentTarget.select()}
            className="block w-full rounded-md border border-border bg-input px-3 py-2 text-xs text-foreground" />
        )}
        {linkStatus && <p className="text-sm text-primary">{linkStatus}</p>}
      </section>
```

- [ ] **Step 2: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0.

Run: `cd frontend && npx next build`
Expected: build conclui sem erro.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/users-manager.tsx
git commit -m "feat(painel): generate/revoke selflink buttons in user editor"
```

---

## Verificação final (após todas as tasks)

- [ ] `python -m pytest -m unit -q` → todos verdes.
- [ ] `cd frontend && npx tsc --noEmit` → exit 0; `npx next build` ok com a rota `/me`.
- [ ] Migration `selflink_token` aplicada no Supabase (Task 1, Step 1).
- [ ] Env `PANEL_BASE_URL` setada na Vercel (ou aceitar o default).
- [ ] Smoke manual: admin gera link → abrir `/me?token=…` (token some da URL) → editar grade/seções/áudio → salvar → revogar → link volta a falhar.
- [ ] Deploy: `git push origin master` (confirmar com o usuário; se o webhook não disparar, `git commit --allow-empty`).
