# Painel de Configuração Admin — Fase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar um painel web read-only com login que exibe a config atual do agente (prompts, tools, modelo, timeouts, áudio, fontes de notícia), provando a arquitetura auth + Next.js + endpoint de introspecção.

**Architecture:** Next.js (App Router) em `frontend/`, deploy Vercel separado, autenticado via Supabase Auth. Um endpoint FastAPI read-only (`GET /api/admin/agent-config`) serializa a config hardcoded do backend (sem secrets) e o painel consome com o JWT da sessão Supabase.

**Tech Stack:** Python 3.12 / FastAPI / PyJWT (backend); Next.js 15 / TypeScript / Tailwind / @supabase/ssr (frontend).

## Global Constraints

- Backend: Python 3.12, FastAPI. snake_case funções/variáveis.
- Frontend: TypeScript, camelCase variáveis/funções, PascalCase componentes.
- Commits: mensagens em inglês, imperativas.
- TDD no backend; frontend valida via build/run (sem testes de UI nesta fase — YAGNI).
- O endpoint `/api/admin/agent-config` **nunca** expõe secrets (chaves de API).
- Os 116 testes atuais continuam verdes (`pytest backend/tests/ -v`).
- Auth backend: verificar JWT Supabase (HS256, audience `authenticated`) com `SUPABASE_JWT_SECRET`.
- Sem editar nada nesta fase — somente leitura.

---

### Task 1: `describe_config()` no reporter

**Files:**
- Modify: `backend/services/reporter.py`
- Test: `backend/tests/test_reporter_describe.py`

**Interfaces:**
- Produces: `reporter.describe_config() -> dict` com chaves `model`, `validator_model`, `anthropic_timeout_s`, `max_tool_rounds`, `max_tokens`, `tools` (lista de `{name, description}`), `system_market`, `system_chat`, `system_validator`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_reporter_describe.py
from backend.services import reporter


def test_describe_config_exposes_model_and_tools():
    cfg = reporter.describe_config()
    assert cfg["model"] == "claude-sonnet-4-6"
    assert cfg["validator_model"] == "claude-haiku-4-5-20251001"
    assert cfg["max_tool_rounds"] == 6
    assert cfg["max_tokens"] == 2000
    assert len(cfg["tools"]) == 5
    assert {"get_stock_data", "get_agro_data", "search_agro_web",
            "search_web", "read_article"} == {t["name"] for t in cfg["tools"]}


def test_describe_config_exposes_prompts_no_secret():
    cfg = reporter.describe_config()
    assert "INTEGRIDADE FACTUAL" in cfg["system_market"]
    assert "system_chat" in cfg and "system_validator" in cfg
    assert "ANTHROPIC_API_KEY" not in str(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_reporter_describe.py -v`
Expected: FAIL — `AttributeError: module 'backend.services.reporter' has no attribute 'describe_config'`

- [ ] **Step 3: Add a `_MAX_TOKENS` constant and `describe_config()`**

Em `backend/services/reporter.py`, logo após a linha `_MAX_TOOL_ROUNDS = 6` (linha 18), adicione:

```python
_MAX_TOKENS = 2000
```

Substitua os dois usos literais de `max_tokens=2000` em `generate_report` (na chamada de `create_kwargs`, ~linha 435) por `max_tokens=_MAX_TOKENS`. O `max_tokens=2000` do validador (`_validate_and_fix`) pode permanecer literal.

Ao final do arquivo, adicione:

```python
def describe_config() -> dict:
    """Snapshot read-only da config do agente para exibição no painel.
    Não inclui secrets."""
    return {
        "model": "claude-sonnet-4-6",
        "validator_model": "claude-haiku-4-5-20251001",
        "anthropic_timeout_s": _ANTHROPIC_TIMEOUT,
        "max_tool_rounds": _MAX_TOOL_ROUNDS,
        "max_tokens": _MAX_TOKENS,
        "tools": [
            {"name": t["name"], "description": t["description"]}
            for t in (_STOCK_TOOL, _AGRO_DATA_TOOL, _AGRO_SEARCH_TOOL,
                      _WEB_SEARCH_TOOL, _READ_ARTICLE_TOOL)
        ],
        "system_market": _SYSTEM_MARKET,
        "system_chat": _SYSTEM_CHAT,
        "system_validator": _SYSTEM_VALIDATOR,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_reporter_describe.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/reporter.py backend/tests/test_reporter_describe.py
git commit -m "feat: expose read-only agent config snapshot from reporter"
```

---

### Task 2: `describe_config()` no news collector

**Files:**
- Modify: `backend/collectors/news.py`
- Test: `backend/tests/test_news_describe.py`

**Interfaces:**
- Produces: `news.describe_config() -> dict` com `sources_finance` (list[str]), `sources_tech` (list[str]), `finance_query` (str), `ai_query` (str), `rss_feeds` (list[`{nome, url}`]), `rss_feeds_ai` (list[`{nome, url}`]).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_news_describe.py
from backend.collectors import news


def test_news_describe_config_sources_and_feeds():
    cfg = news.describe_config()
    assert "reuters" in cfg["sources_finance"]
    assert "techcrunch" in cfg["sources_tech"]
    assert isinstance(cfg["finance_query"], str) and "inflation" in cfg["finance_query"]
    assert cfg["rss_feeds"][0]["nome"] and cfg["rss_feeds"][0]["url"].startswith("http")
    assert any(f["nome"] == "MIT Technology Review" for f in cfg["rss_feeds_ai"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_news_describe.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'describe_config'`

- [ ] **Step 3: Add `describe_config()` to news.py**

Ao final de `backend/collectors/news.py` (antes do bloco `@router.get`), adicione:

```python
def describe_config() -> dict:
    """Snapshot read-only das fontes/queries de notícia para o painel."""
    return {
        "sources_finance": SOURCES_FINANCE.split(","),
        "sources_tech": SOURCES_TECH.split(","),
        "finance_query": _FINANCE_QUERY,
        "ai_query": _AI_QUERY,
        "rss_feeds": [{"nome": n, "url": u} for n, u in _RSS_FEEDS],
        "rss_feeds_ai": [{"nome": n, "url": u} for n, u in _RSS_FEEDS_AI],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_news_describe.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/collectors/news.py backend/tests/test_news_describe.py
git commit -m "feat: expose read-only news sources config"
```

---

### Task 3: `describe_config()` no media (áudio)

**Files:**
- Modify: `backend/services/media.py`
- Test: `backend/tests/test_media_describe.py`

**Interfaces:**
- Produces: `media.describe_config() -> dict` com `tts_voice`, `tts_speed`, `tts_model`, `transcribe_model`, `voices_disponiveis` (list[str]).
- Produces: constantes `media.DEFAULT_TTS_VOICE` (str), `media.DEFAULT_TTS_SPEED` (float).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_media_describe.py
from backend.services import media


def test_media_describe_config_defaults():
    cfg = media.describe_config()
    assert cfg["tts_voice"] == "nova"
    assert cfg["tts_speed"] == 0.85
    assert cfg["tts_model"] == "tts-1"
    assert cfg["transcribe_model"] == "whisper-1"
    assert "nova" in cfg["voices_disponiveis"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_media_describe.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'describe_config'`

- [ ] **Step 3: Extrair constantes e adicionar `describe_config()`**

Em `backend/services/media.py`, após `_OPENAI_TIMEOUT = 60.0` (linha 9), adicione:

```python
DEFAULT_TTS_VOICE = "nova"
DEFAULT_TTS_SPEED = 0.85
```

Altere a assinatura de `text_to_speech` (linha 39) para usar as constantes como default:

```python
def text_to_speech(text: str, voice: str = DEFAULT_TTS_VOICE, speed: float = DEFAULT_TTS_SPEED) -> bytes:
```

Ao final do arquivo, adicione:

```python
def describe_config() -> dict:
    """Snapshot read-only da config de áudio (TTS/transcrição) para o painel."""
    return {
        "tts_voice": DEFAULT_TTS_VOICE,
        "tts_speed": DEFAULT_TTS_SPEED,
        "tts_model": "tts-1",
        "transcribe_model": "whisper-1",
        "voices_disponiveis": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_media_describe.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/media.py backend/tests/test_media_describe.py
git commit -m "feat: expose read-only audio config defaults"
```

---

### Task 4: Dependência de auth Supabase JWT (FastAPI)

**Files:**
- Create: `backend/services/auth.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Produces: `auth.decode_token(token: str) -> dict` — decodifica/valida JWT HS256 com `SUPABASE_JWT_SECRET`, audience `authenticated`; lança `jwt.PyJWTError` se inválido.
- Produces: `auth.verify_supabase_jwt(authorization: str | None) -> dict` — dependência FastAPI; lança `HTTPException(401)` se header ausente/malformado ou token inválido; retorna o payload.

- [ ] **Step 1: Add PyJWT to requirements**

Em `backend/requirements.txt`, adicione ao final:

```
PyJWT==2.10.1
```

Instale: `pip install PyJWT==2.10.1`

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_auth.py
import os
import time
from unittest.mock import patch

import jwt
import pytest
from fastapi import HTTPException

from backend.services import auth

_SECRET = "test-jwt-secret"


def _token(secret=_SECRET, aud="authenticated", exp_offset=3600):
    return jwt.encode(
        {"sub": "u1", "aud": aud, "exp": int(time.time()) + exp_offset},
        secret, algorithm="HS256",
    )


def test_decode_valid_token():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        payload = auth.decode_token(_token())
    assert payload["sub"] == "u1"


def test_verify_missing_header_raises_401():
    with pytest.raises(HTTPException) as exc:
        auth.verify_supabase_jwt(authorization=None)
    assert exc.value.status_code == 401


def test_verify_invalid_token_raises_401():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        with pytest.raises(HTTPException) as exc:
            auth.verify_supabase_jwt(authorization="Bearer garbage")
    assert exc.value.status_code == 401


def test_verify_valid_bearer_returns_payload():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        payload = auth.verify_supabase_jwt(authorization=f"Bearer {_token()}")
    assert payload["sub"] == "u1"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.auth'`

- [ ] **Step 4: Create `backend/services/auth.py`**

```python
import os

import jwt
from fastapi import Header, HTTPException


def decode_token(token: str) -> dict:
    """Valida um JWT Supabase (HS256) e retorna o payload.
    Lança jwt.PyJWTError se inválido/expirado."""
    secret = os.environ["SUPABASE_JWT_SECRET"]
    return jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")


def verify_supabase_jwt(authorization: str | None = Header(default=None)) -> dict:
    """Dependência FastAPI: exige `Authorization: Bearer <jwt>` válido."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return decode_token(authorization.split(" ", 1)[1])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="invalid token")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_auth.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/services/auth.py backend/tests/test_auth.py backend/requirements.txt
git commit -m "feat: add Supabase JWT verification dependency"
```

---

### Task 5: Endpoint `GET /api/admin/agent-config`

**Files:**
- Create: `backend/api/admin.py`
- Modify: `backend/api/main.py:13` (import) e `backend/api/main.py:40` (include_router)
- Test: `backend/tests/test_admin_config.py`

**Interfaces:**
- Consumes: `auth.verify_supabase_jwt`, `reporter.describe_config`, `news.describe_config`, `media.describe_config`.
- Produces: rota `GET /api/admin/agent-config` retornando `{"agent": {...}, "audio": {...}, "news": {...}}`; 401 sem token válido.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_config.py
import os
import time
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient

from backend.api.main import app

client = TestClient(app)
_SECRET = "test-jwt-secret"


def _token():
    return jwt.encode(
        {"sub": "u1", "aud": "authenticated", "exp": int(time.time()) + 3600},
        _SECRET, algorithm="HS256",
    )


def test_agent_config_requires_auth():
    resp = client.get("/api/admin/agent-config")
    assert resp.status_code == 401


def test_agent_config_returns_all_sections():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        resp = client.get("/api/admin/agent-config",
                          headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent"]["model"] == "claude-sonnet-4-6"
    assert "reuters" in body["news"]["sources_finance"]
    assert body["audio"]["tts_voice"] == "nova"


def test_agent_config_exposes_no_secrets():
    with patch.dict(os.environ, {"SUPABASE_JWT_SECRET": _SECRET}):
        resp = client.get("/api/admin/agent-config",
                          headers={"Authorization": f"Bearer {_token()}"})
    raw = resp.text.lower()
    assert "api_key" not in raw
    assert "sk-" not in raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_admin_config.py -v`
Expected: FAIL — 404 em todas (rota não existe)

- [ ] **Step 3: Create `backend/api/admin.py`**

```python
from fastapi import APIRouter, Depends

from backend.services import reporter, auth
from backend.services import media as media_service
from backend.collectors import news

router = APIRouter()


@router.get("/api/admin/agent-config")
def get_agent_config(user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Snapshot read-only da config do agente. Exige auth. Sem secrets."""
    return {
        "agent": reporter.describe_config(),
        "audio": media_service.describe_config(),
        "news": news.describe_config(),
    }
```

- [ ] **Step 4: Register the router in main.py**

Em `backend/api/main.py` linha 13, troque:

```python
from backend.api import send_report, cron_report, check_alerts
```

por:

```python
from backend.api import send_report, cron_report, check_alerts, admin
```

E após a linha 40 (`app.include_router(eia.router)`), adicione:

```python
app.include_router(admin.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_admin_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the full backend suite**

Run: `pytest backend/tests/ -v`
Expected: PASS — todos os testes existentes + os novos verdes

- [ ] **Step 7: Commit**

```bash
git add backend/api/admin.py backend/api/main.py backend/tests/test_admin_config.py
git commit -m "feat: add read-only admin agent-config endpoint"
```

---

### Task 6: Scaffold do painel Next.js em `frontend/`

**Files:**
- Create: `frontend/` (via create-next-app)
- Create: `frontend/.env.local.example`
- Modify: `frontend/package.json` (deps Supabase)

**Interfaces:**
- Produces: app Next.js 15 (App Router, TS, Tailwind) em `frontend/`, rodável com `npm run dev`.
- Produces: env keys `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_BACKEND_URL`.

- [ ] **Step 1: Scaffold the app**

Run (da raiz do projeto):

```bash
npx create-next-app@latest frontend --typescript --tailwind --app --eslint --no-src-dir --import-alias "@/*" --use-npm
```

- [ ] **Step 2: Add Supabase deps**

Run:

```bash
cd frontend && npm install @supabase/ssr @supabase/supabase-js && cd ..
```

- [ ] **Step 3: Create env example**

```bash
# frontend/.env.local.example
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key>
NEXT_PUBLIC_BACKEND_URL=https://noticiasgg.vercel.app
```

Copie para `.env.local` e preencha com os valores reais do Supabase.

- [ ] **Step 4: Verify it builds**

Run: `cd frontend && npm run build && cd ..`
Expected: build conclui sem erro.

- [ ] **Step 5: Commit**

```bash
git add frontend/ -- ':!frontend/node_modules'
git commit -m "chore: scaffold admin dashboard next.js app"
```

(Confirme que `frontend/.gitignore` ignora `node_modules` e `.env.local` — o create-next-app já gera isso.)

---

### Task 7: Clientes Supabase + middleware de proteção de rotas

**Files:**
- Create: `frontend/lib/supabase/client.ts`
- Create: `frontend/lib/supabase/server.ts`
- Create: `frontend/lib/supabase/middleware.ts`
- Create: `frontend/middleware.ts`

**Interfaces:**
- Produces: `createClient()` (browser) em `lib/supabase/client.ts`.
- Produces: `createClient()` (server, async) em `lib/supabase/server.ts`.
- Produces: `updateSession(request)` em `lib/supabase/middleware.ts`.
- Comportamento: requisições não autenticadas a qualquer rota que não seja `/login` são redirecionadas para `/login`.

- [ ] **Step 1: Browser client**

```typescript
// frontend/lib/supabase/client.ts
import { createBrowserClient } from "@supabase/ssr";

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
```

- [ ] **Step 2: Server client**

```typescript
// frontend/lib/supabase/server.ts
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // chamado de um Server Component — ignorável quando há middleware
          }
        },
      },
    },
  );
}
```

- [ ] **Step 3: Middleware session helper**

```typescript
// frontend/lib/supabase/middleware.ts
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  const { data: { user } } = await supabase.auth.getUser();

  if (!user && !request.nextUrl.pathname.startsWith("/login")) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    return NextResponse.redirect(url);
  }

  return response;
}
```

- [ ] **Step 4: Root middleware**

```typescript
// frontend/middleware.ts
import { type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";

export async function middleware(request: NextRequest) {
  return await updateSession(request);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 5: Verify it builds**

Run: `cd frontend && npm run build && cd ..`
Expected: build conclui sem erro de tipos.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib frontend/middleware.ts
git commit -m "feat: add supabase clients and route-protection middleware"
```

---

### Task 8: Página de login

**Files:**
- Create: `frontend/app/login/page.tsx`
- Create: `frontend/app/login/actions.ts`

**Interfaces:**
- Consumes: `createClient` de `lib/supabase/server.ts`.
- Produces: rota `/login` com form email+senha; em sucesso redireciona para `/`.
- Nota: signup é fechado — usuários são criados manualmente no painel do Supabase.

- [ ] **Step 1: Server action de login**

```typescript
// frontend/app/login/actions.ts
"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

export async function login(formData: FormData) {
  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({
    email: String(formData.get("email")),
    password: String(formData.get("password")),
  });
  if (error) {
    redirect("/login?error=" + encodeURIComponent(error.message));
  }
  redirect("/");
}
```

- [ ] **Step 2: Login page**

```tsx
// frontend/app/login/page.tsx
import { login } from "./actions";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  return (
    <main className="flex min-h-screen items-center justify-center bg-neutral-950 text-neutral-100">
      <form action={login} className="w-full max-w-sm space-y-4 rounded-xl border border-neutral-800 p-8">
        <h1 className="text-xl font-semibold">Painel noticiasgg</h1>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <input
          name="email"
          type="email"
          required
          placeholder="email"
          className="w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2"
        />
        <input
          name="password"
          type="password"
          required
          placeholder="senha"
          className="w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2"
        />
        <button type="submit" className="w-full rounded-md bg-emerald-600 px-3 py-2 font-medium hover:bg-emerald-500">
          Entrar
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 3: Verify build + manual login**

Run: `cd frontend && npm run build && cd ..`
Expected: build OK.

Manual (depois de criar um usuário no Supabase Auth e preencher `.env.local`): `cd frontend && npm run dev`, abrir `http://localhost:3000`, confirmar redirecionamento para `/login`, logar e cair em `/`.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/login
git commit -m "feat: add admin login page with supabase auth"
```

---

### Task 9: Helper de API + página `/agente` read-only + overview

**Files:**
- Create: `frontend/lib/api.ts`
- Create: `frontend/app/agente/page.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `createClient` de `lib/supabase/server.ts`; endpoint backend `GET /api/admin/agent-config`.
- Produces: `fetchAgentConfig()` em `lib/api.ts` — pega o access token da sessão e chama o backend com `Authorization: Bearer`.
- Produces: rota `/agente` exibindo agent/audio/news read-only; `/` com link para `/agente`.

- [ ] **Step 1: API helper**

```typescript
// frontend/lib/api.ts
import { createClient } from "@/lib/supabase/server";

export async function fetchAgentConfig() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/agent-config`,
    {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    },
  );
  if (!res.ok) {
    throw new Error(`backend ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 2: `/agente` page**

```tsx
// frontend/app/agente/page.tsx
import { fetchAgentConfig } from "@/lib/api";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border-b border-neutral-800 py-2">
      <dt className="text-xs uppercase tracking-wide text-neutral-500">{label}</dt>
      <dd className="mt-1 text-sm">{value}</dd>
    </div>
  );
}

export default async function AgentePage() {
  const cfg = await fetchAgentConfig();
  const { agent, audio, news } = cfg;

  return (
    <main className="mx-auto max-w-3xl space-y-8 p-8 text-neutral-100">
      <header>
        <h1 className="text-2xl font-semibold">Agente</h1>
        <p className="text-sm text-amber-400">🔒 Somente leitura nesta fase.</p>
      </header>

      <section>
        <h2 className="mb-2 text-lg font-medium">Modelo & limites</h2>
        <dl>
          <Field label="Modelo" value={agent.model} />
          <Field label="Validador" value={agent.validator_model} />
          <Field label="Timeout (s)" value={agent.anthropic_timeout_s} />
          <Field label="Max tool rounds" value={agent.max_tool_rounds} />
          <Field label="Max tokens" value={agent.max_tokens} />
        </dl>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">Áudio</h2>
        <dl>
          <Field label="Voz TTS" value={audio.tts_voice} />
          <Field label="Velocidade" value={audio.tts_speed} />
          <Field label="Modelo TTS" value={audio.tts_model} />
          <Field label="Transcrição" value={audio.transcribe_model} />
        </dl>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">Tools ({agent.tools.length})</h2>
        <ul className="space-y-1 text-sm">
          {agent.tools.map((t: { name: string; description: string }) => (
            <li key={t.name}>
              <span className="font-mono text-emerald-400">{t.name}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">Fontes de notícia</h2>
        <Field label="Finance" value={news.sources_finance.join(", ")} />
        <Field label="Tech" value={news.sources_tech.join(", ")} />
        <Field label="RSS" value={news.rss_feeds.map((f: { nome: string }) => f.nome).join(", ")} />
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">System prompts</h2>
        <details className="text-sm">
          <summary className="cursor-pointer text-neutral-400">system_market</summary>
          <pre className="mt-2 whitespace-pre-wrap rounded-md bg-neutral-900 p-3 text-xs">{agent.system_market}</pre>
        </details>
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-neutral-400">system_chat</summary>
          <pre className="mt-2 whitespace-pre-wrap rounded-md bg-neutral-900 p-3 text-xs">{agent.system_chat}</pre>
        </details>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Overview page**

```tsx
// frontend/app/page.tsx
import Link from "next/link";

export default function HomePage() {
  return (
    <main className="mx-auto max-w-3xl space-y-4 p-8 text-neutral-100">
      <h1 className="text-2xl font-semibold">Painel noticiasgg</h1>
      <nav className="flex flex-col gap-2">
        <Link href="/agente" className="rounded-md border border-neutral-800 px-4 py-3 hover:bg-neutral-900">
          Agente (read-only) →
        </Link>
      </nav>
    </main>
  );
}
```

- [ ] **Step 4: Verify build + manual check**

Run: `cd frontend && npm run build && cd ..`
Expected: build OK.

Manual (com backend acessível e `.env.local` preenchido): `npm run dev`, logar, abrir `/agente`, confirmar que modelo/áudio/fontes/prompts aparecem e que nenhum secret é exibido.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api.ts frontend/app/agente frontend/app/page.tsx
git commit -m "feat: add read-only agent config view"
```

---

## Pós-Fase 0 (config, fora do plano de código)

- Definir `SUPABASE_JWT_SECRET` nas env vars da Vercel (backend) — pegar em Supabase → Settings → API → JWT Secret.
- Criar projeto Vercel separado apontando para `frontend/`; definir `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_BACKEND_URL`.
- Criar os usuários admin manualmente em Supabase → Authentication → Users.

## Self-Review

- **Spec coverage:** Auth (Task 4,7,8) ✓; endpoint read-only sem secrets (Task 5) ✓; espelho read-only de agente/áudio/fontes (Task 1-3,9) ✓; deploy isolado (Pós-Fase 0) ✓. Edição (Fases 1-2) intencionalmente fora deste plano.
- **Placeholders:** nenhum — todo passo tem código/comando concreto.
- **Type consistency:** `describe_config()` retorna as mesmas chaves consumidas em `admin.py` (Task 5) e na página `/agente` (Task 9): `agent.model`, `agent.tools[].name`, `audio.tts_voice`, `news.sources_finance`, `news.rss_feeds[].nome`. `verify_supabase_jwt`/`decode_token` consistentes entre Task 4 e 5.
