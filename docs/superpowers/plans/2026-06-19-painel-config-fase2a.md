# Painel de Configuração Admin — Fase 2A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir editar pelo painel as preferências de cada usuário autorizado (seções do relatório, horário, voz/velocidade da TTS, toggles de áudio) — hoje editáveis só por comando no WhatsApp.

**Architecture:** Endpoints admin no backend (`/api/admin/users`, `/api/admin/user-prefs`) usando a **service role** do Supabase (sem precisar de RLS em `user_preferences`/`authorized_users`). O painel lê/escreve via esses endpoints autenticados por JWT. **Não toca na resolução de preferências do webhook** (`main.py`) — apenas adiciona o painel como mais um editor da tabela `user_preferences`, que o webhook já lê.

**Tech Stack:** Python 3.12 / FastAPI / pydantic (backend); Next.js 16 / TypeScript (frontend).

## Global Constraints

- Backend: Python 3.12, FastAPI. snake_case. Reaproveitar `supabase.save_preferences/get_preferences/delete_preferences` que já existem.
- Frontend: TypeScript, camelCase, PascalCase componentes.
- Commits: inglês, imperativos.
- TDD no backend; frontend valida via `npm run build` + teste manual.
- Endpoints admin exigem `auth.verify_supabase_jwt` (já existe).
- Backend acessa Supabase com `SUPABASE_KEY` (service role) → bypassa RLS; **não** criar RLS nova nesta fase.
- NÃO alterar `main.py` nem a lógica de resolução do webhook.
- Os 149 testes atuais continuam verdes.
- Seções válidas (8): `market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br`. Vozes (6): `alloy, echo, fable, nova, onyx, shimmer`.

---

### Task 1: `supabase.list_authorized()`

**Files:**
- Modify: `backend/services/supabase.py` (append)
- Test: `backend/tests/test_list_authorized.py`

**Interfaces:**
- Produces: `supabase.list_authorized() -> list[dict]` — `[{"phone": str, "name": str|None}, ...]` ordenado por phone.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_list_authorized.py
from dotenv import load_dotenv
load_dotenv()
from backend.services import supabase


def test_list_authorized_returns_list():
    rows = supabase.list_authorized()
    assert isinstance(rows, list)
    for row in rows:
        assert "phone" in row
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_list_authorized.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'list_authorized'`

- [ ] **Step 3: Add `list_authorized()`**

No fim de `backend/services/supabase.py`:

```python
def list_authorized() -> list[dict]:
    """Lista todos os usuários autorizados (phone + name)."""
    with _client() as c:
        r = c.get("/authorized_users?select=phone,name&order=phone.asc")
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_list_authorized.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/supabase.py backend/tests/test_list_authorized.py
git commit -m "feat: list authorized users from supabase"
```

---

### Task 2: `GET /api/admin/users`

**Files:**
- Modify: `backend/api/admin.py`
- Test: `backend/tests/test_admin_users.py`

**Interfaces:**
- Consumes: `auth.verify_supabase_jwt`, `supabase.list_authorized`, `supabase.get_preferences`.
- Produces: rota `GET /api/admin/users` → `{"users": [{"phone", "name", "preferences": {sections, report_time, audio_for_text, audio_for_media, tts_voice, tts_speed} | null}]}`; 401 sem token.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_users.py
import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth

client = TestClient(app)
_PRIV = ec.generate_private_key(ec.SECP256R1())
_PUB = _PRIV.public_key()


def _token():
    return jwt.encode(
        {"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600},
        _PRIV, algorithm="ES256",
    )


class _FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=_PUB)


def test_users_requires_auth():
    resp = client.get("/api/admin/users")
    assert resp.status_code == 401


def test_users_returns_users_with_prefs():
    authed = [{"phone": "5511", "name": "Ana"}, {"phone": "5522", "name": "Bia"}]
    prefs_5511 = {"sections": {"market": True}, "report_time": "08:00",
                  "audio_for_text": True, "audio_for_media": None,
                  "tts_voice": "onyx", "tts_speed": 0.9}
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.list_authorized", return_value=authed), \
         patch("backend.api.admin.supabase.get_preferences",
               side_effect=lambda p: prefs_5511 if p == "5511" else None):
        resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    users = resp.json()["users"]
    assert users[0]["phone"] == "5511"
    assert users[0]["preferences"]["tts_voice"] == "onyx"
    assert users[1]["preferences"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_admin_users.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Add the endpoint**

Em `backend/api/admin.py`, importe `supabase` (adicione à linha de import existente `from backend.services import reporter, auth` → inclua `supabase`) e adicione a rota:

```python
@router.get("/api/admin/users")
def list_users(user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Lista usuários autorizados com suas preferências (para o painel)."""
    out = []
    for u in supabase.list_authorized():
        prefs = supabase.get_preferences(u["phone"])
        out.append({
            "phone": u["phone"],
            "name": u.get("name"),
            "preferences": {
                "sections": prefs.get("sections"),
                "report_time": prefs.get("report_time"),
                "audio_for_text": prefs.get("audio_for_text"),
                "audio_for_media": prefs.get("audio_for_media"),
                "tts_voice": prefs.get("tts_voice"),
                "tts_speed": prefs.get("tts_speed"),
            } if prefs else None,
        })
    return {"users": out}
```

A linha de import deve ficar: `from backend.services import reporter, auth, supabase`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_admin_users.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/api/admin.py backend/tests/test_admin_users.py
git commit -m "feat: add admin endpoint listing users with preferences"
```

---

### Task 3: `POST /api/admin/user-prefs` + reset

**Files:**
- Modify: `backend/api/admin.py`
- Test: `backend/tests/test_admin_user_prefs.py`

**Interfaces:**
- Consumes: `auth.verify_supabase_jwt`, `supabase.save_preferences`, `supabase.delete_preferences`.
- Produces:
  - `POST /api/admin/user-prefs` body `{phone, sections?, report_time?, audio_for_text?, audio_for_media?, tts_voice?, tts_speed?}` → salva; `{"ok": true}`.
  - `DELETE /api/admin/user-prefs/{phone}` → reseta (apaga a linha); `{"ok": true}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_user_prefs.py
import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth

client = TestClient(app)
_PRIV = ec.generate_private_key(ec.SECP256R1())
_PUB = _PRIV.public_key()


def _token():
    return jwt.encode(
        {"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600},
        _PRIV, algorithm="ES256",
    )


class _FakeJWKS:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=_PUB)


def test_save_user_prefs_requires_auth():
    resp = client.post("/api/admin/user-prefs", json={"phone": "5511"})
    assert resp.status_code == 401


def test_save_user_prefs_calls_supabase():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.save_preferences") as mock_save:
        resp = client.post(
            "/api/admin/user-prefs",
            json={"phone": "5511", "tts_voice": "onyx", "tts_speed": 0.9,
                  "audio_for_text": True},
            headers={"Authorization": f"Bearer {_token()}"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_save.assert_called_once()
    kwargs = mock_save.call_args.kwargs
    assert kwargs["tts_voice"] == "onyx"
    assert kwargs["audio_for_text"] is True


def test_reset_user_prefs_calls_delete():
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.supabase.delete_preferences") as mock_del:
        resp = client.delete("/api/admin/user-prefs/5511",
                             headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    mock_del.assert_called_once_with("5511")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_admin_user_prefs.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Add the endpoints**

Em `backend/api/admin.py`, adicione (o `BaseModel` já está importado da Fase 1):

```python
class UserPrefsBody(BaseModel):
    phone: str
    sections: dict | None = None
    report_time: str | None = None
    audio_for_text: bool | None = None
    audio_for_media: bool | None = None
    tts_voice: str | None = None
    tts_speed: float | None = None


@router.post("/api/admin/user-prefs")
def save_user_prefs(body: UserPrefsBody, user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Salva as preferências de um usuário (edição pelo painel)."""
    supabase.save_preferences(
        body.phone,
        sections=body.sections,
        report_time=body.report_time,
        audio_for_text=body.audio_for_text,
        audio_for_media=body.audio_for_media,
        tts_voice=body.tts_voice,
        tts_speed=body.tts_speed,
    )
    return {"ok": True}


@router.delete("/api/admin/user-prefs/{phone}")
def reset_user_prefs(phone: str, user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Reseta as preferências de um usuário (volta aos defaults)."""
    supabase.delete_preferences(phone)
    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/test_admin_user_prefs.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run full backend suite**

Run: `pytest backend/tests/ -q`
Expected: PASS (todos verdes; ignorar falha transiente de `test_indicators_br` da API do BCB — re-rodar isolado se ocorrer)

- [ ] **Step 6: Commit**

```bash
git add backend/api/admin.py backend/tests/test_admin_user_prefs.py
git commit -m "feat: add admin endpoints to save and reset user preferences"
```

---

### Task 4: Frontend — helpers de usuários

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/config.ts`

**Interfaces:**
- Produces (em `lib/api.ts`): tipos `UserPrefs`, `AdminUser`; `fetchUsers(): Promise<AdminUser[]>` (server-side, GET `/api/admin/users`).
- Produces (em `lib/config.ts`): `saveUserPrefs(body)` (POST) e `resetUserPrefs(phone)` (DELETE), client-side com token da sessão.

- [ ] **Step 1: Add types + fetchUsers to lib/api.ts**

No fim de `frontend/lib/api.ts`:

```typescript
export type UserPrefs = {
  sections: Record<string, boolean> | null;
  report_time: string | null;
  audio_for_text: boolean | null;
  audio_for_media: boolean | null;
  tts_voice: string | null;
  tts_speed: number | null;
};

export type AdminUser = {
  phone: string;
  name: string | null;
  preferences: UserPrefs | null;
};

export async function fetchUsers(): Promise<AdminUser[]> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/users`,
    { headers: { Authorization: `Bearer ${session?.access_token}` }, cache: "no-store" },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return (await res.json()).users as AdminUser[];
}
```

- [ ] **Step 2: Add write helpers to lib/config.ts**

No fim de `frontend/lib/config.ts`:

```typescript
export type UserPrefsInput = {
  phone: string;
  sections: Record<string, boolean> | null;
  report_time: string | null;
  audio_for_text: boolean | null;
  audio_for_media: boolean | null;
  tts_voice: string | null;
  tts_speed: number | null;
};

export async function saveUserPrefs(body: UserPrefsInput): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/user-prefs`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session?.access_token}`,
      },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function resetUserPrefs(phone: string): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/user-prefs/${encodeURIComponent(phone)}`,
    { method: "DELETE", headers: { Authorization: `Bearer ${session?.access_token}` } },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build && cd ..`
Expected: build OK.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api.ts frontend/lib/config.ts
git commit -m "feat: add user list/prefs fetch and write helpers"
```

---

### Task 5: Frontend — página `/usuarios` + form + nav

**Files:**
- Create: `frontend/app/usuarios/page.tsx`
- Create: `frontend/components/users-manager.tsx`
- Modify: `frontend/components/shell.tsx` (nav)

**Interfaces:**
- Consumes: `fetchUsers`, `saveUserPrefs`, `resetUserPrefs`, `Shell`.
- Produces: rota `/usuarios` (lista usuários + edita as prefs do selecionado).

- [ ] **Step 1: Add "Usuários" to nav**

Em `frontend/components/shell.tsx`, no `NAV`:

```typescript
const NAV = [
  { href: "/", label: "Visão geral" },
  { href: "/agente", label: "Agente" },
  { href: "/noticias/fontes", label: "Notícias" },
  { href: "/usuarios", label: "Usuários" },
];
```

- [ ] **Step 2: Create the UsersManager client component**

```tsx
// frontend/components/users-manager.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { saveUserPrefs, resetUserPrefs } from "@/lib/config";
import type { AdminUser } from "@/lib/api";

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
const HOURS = ["", "06:00", "07:00", "08:00", "09:00", "12:00", "18:00", "19:00", "20:00", "21:00"];

function defaultSections(): Record<string, boolean> {
  return Object.fromEntries(SECTIONS.map(([k]) => [k, true]));
}

function UserForm({ user }: { user: AdminUser }) {
  const router = useRouter();
  const p = user.preferences;
  const [sections, setSections] = useState<Record<string, boolean>>(p?.sections ?? defaultSections());
  const [reportTime, setReportTime] = useState(p?.report_time ?? "");
  const [audioText, setAudioText] = useState(Boolean(p?.audio_for_text));
  const [audioMedia, setAudioMedia] = useState(Boolean(p?.audio_for_media));
  const [voice, setVoice] = useState(p?.tts_voice ?? "nova");
  const [speed, setSpeed] = useState(p?.tts_speed ?? 0.85);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      await saveUserPrefs({
        phone: user.phone,
        sections,
        report_time: reportTime || null,
        audio_for_text: audioText,
        audio_for_media: audioMedia,
        tts_voice: voice,
        tts_speed: speed,
      });
      setStatus("Salvo. Vale na próxima interação do usuário.");
      router.refresh();
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    setBusy(true);
    setStatus("Resetando…");
    try {
      await resetUserPrefs(user.phone);
      setStatus("Resetado para os padrões. Recarregue para ver.");
      router.refresh();
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-line bg-surface p-5">
        <h2 className="mb-3 font-display text-sm font-medium uppercase tracking-wide text-slate">Relatório diário</h2>
        <label className="block">
          <span className="eyebrow">Horário de envio</span>
          <select value={reportTime} onChange={(e) => setReportTime(e.target.value)}
            className="mt-1 block rounded-md border border-line bg-ink px-3 py-2 text-sm text-bone">
            {HOURS.map((h) => <option key={h} value={h}>{h || "não enviar"}</option>)}
          </select>
        </label>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {SECTIONS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-2 text-sm text-bone">
              <input type="checkbox" checked={sections[k] ?? false}
                onChange={() => setSections((s) => ({ ...s, [k]: !s[k] }))} />
              {label}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-line bg-surface p-5 space-y-3">
        <h2 className="font-display text-sm font-medium uppercase tracking-wide text-slate">Áudio</h2>
        <label className="flex items-center gap-2 text-sm text-bone">
          <input type="checkbox" checked={audioText} onChange={() => setAudioText((v) => !v)} />
          Responder textos em áudio
        </label>
        <label className="flex items-center gap-2 text-sm text-bone">
          <input type="checkbox" checked={audioMedia} onChange={() => setAudioMedia((v) => !v)} />
          Responder mídias em áudio
        </label>
        <label className="block">
          <span className="eyebrow">Voz</span>
          <select value={voice} onChange={(e) => setVoice(e.target.value)}
            className="mt-1 block rounded-md border border-line bg-ink px-3 py-2 text-sm text-bone">
            {VOICES.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="eyebrow">Velocidade ({speed})</span>
          <input type="range" min={0.5} max={1.5} step={0.05} value={speed}
            onChange={(e) => setSpeed(parseFloat(e.target.value))} className="mt-1 block w-full" />
        </label>
      </section>

      {status && <p className="text-sm text-gold">{status}</p>}
      <div className="flex gap-3">
        <button onClick={save} disabled={busy}
          className="rounded-md bg-gold px-4 py-2 font-medium text-ink hover:bg-bone disabled:opacity-50">Salvar</button>
        <button onClick={reset} disabled={busy}
          className="rounded-md border border-line px-4 py-2 text-sm text-slate hover:text-bone disabled:opacity-50">Resetar padrões</button>
      </div>
    </div>
  );
}

export default function UsersManager({ users }: { users: AdminUser[] }) {
  const [selected, setSelected] = useState(users[0]?.phone ?? null);
  if (users.length === 0) {
    return <p className="text-sm text-slate">Nenhum usuário autorizado ainda.</p>;
  }
  const current = users.find((u) => u.phone === selected) ?? users[0];
  return (
    <div className="grid gap-6 md:grid-cols-[220px_1fr]">
      <aside className="space-y-1">
        {users.map((u) => (
          <button key={u.phone} onClick={() => setSelected(u.phone)}
            className={`block w-full rounded-md px-3 py-2 text-left text-sm ${
              u.phone === current.phone ? "bg-raised text-bone" : "text-slate hover:bg-raised/50 hover:text-bone"
            }`}>
            <span className="block">{u.name || "sem nome"}</span>
            <span className="readout text-xs text-slate">{u.phone}</span>
          </button>
        ))}
      </aside>
      <UserForm key={current.phone} user={current} />
    </div>
  );
}
```

- [ ] **Step 3: Create the page (server component)**

```tsx
// frontend/app/usuarios/page.tsx
import Shell from "@/components/shell";
import UsersManager from "@/components/users-manager";
import { fetchUsers, type AdminUser } from "@/lib/api";

export default async function UsuariosPage() {
  let users: AdminUser[] = [];
  let err: string | null = null;
  try {
    users = await fetchUsers();
  } catch (e) {
    err = e instanceof Error ? e.message : "erro desconhecido";
  }

  return (
    <Shell active="/usuarios">
      <main className="mx-auto max-w-4xl px-8 py-12">
        <span className="eyebrow">Usuários</span>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-bone">
          Preferências por usuário
        </h1>
        <p className="mt-2 max-w-xl text-sm text-slate">
          Ajuste seções do relatório, horário, voz e áudio de cada usuário autorizado.
          Vale na próxima interação dele.
        </p>

        <div className="mt-8">
          {err ? (
            <div className="rounded-lg border border-line bg-surface p-6">
              <p className="text-sm text-bone">Não foi possível carregar os usuários.</p>
              <p className="mt-1 readout text-xs text-slate">backend: {err}</p>
            </div>
          ) : (
            <UsersManager users={users} />
          )}
        </div>
      </main>
    </Shell>
  );
}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build && cd ..`
Expected: build OK; rota `/usuarios` como `ƒ`.

- [ ] **Step 5: Manual end-to-end check**

Com backend local (`uvicorn backend.api.main:app --port 8000`) + frontend local (`.env.local` → `NEXT_PUBLIC_BACKEND_URL=http://localhost:8000`):
1. Logar → **Usuários**
2. Confirmar que os usuários autorizados aparecem na lista
3. Selecionar um, mudar a voz / horário / seções → **Salvar**
4. Conferir na tabela `user_preferences` do Supabase que gravou
5. (Opcional) Confirmar no WhatsApp com aquele usuário, ou via `!ajustes`, que a preferência valeu
6. **Resetar padrões** → linha some da tabela

- [ ] **Step 6: Commit**

```bash
git add frontend/app/usuarios frontend/components/users-manager.tsx frontend/components/shell.tsx
git commit -m "feat: add per-user preferences editing page"
```

---

## Pós-Fase 2A (deploy)

- Push na `master` → backend e painel redeployam (produção). Não há mudança no fluxo do webhook, então comportamento atual intacto até alguém editar prefs pelo painel.

## Self-Review

- **Spec coverage (fatia 2A):** listar usuários (Task 1,2) ✓; editar prefs por usuário — seções/horário/áudio/voz/velocidade (Task 3,5) ✓; reset (Task 3,5) ✓; nav + página (Task 5) ✓. 2B (padrões globais) e 2C (gerais) intencionalmente fora.
- **Placeholders:** nenhum — código/comando concreto em todo passo.
- **Type consistency:** `AdminUser`/`UserPrefs` (Task 4) batem com o retorno de `GET /api/admin/users` (Task 2). `UserPrefsInput` (Task 4) bate com `UserPrefsBody` (Task 3) e com `saveUserPrefs` consumido na Task 5. Seções (8) e vozes (6) idênticas entre backend e frontend. `supabase.save_preferences/get_preferences/delete_preferences/list_authorized` consistentes entre Tasks 1-3.
- **Não-regressão:** nenhuma alteração em `main.py`/`reporter.py`/`news.py`; só novos endpoints em `admin.py` e nova função em `supabase.py`. Testes de webhook intactos.
