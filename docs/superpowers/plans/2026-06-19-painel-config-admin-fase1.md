# Painel de Configuração Admin — Fase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar editáveis pelo painel as fontes de notícia (NewsAPI finance/tech), os feeds RSS (geral/IA) e as queries de busca (`finance_query`/`ai_query`), com o backend lendo a config do Supabase e caindo nos defaults hardcoded quando ausente.

**Architecture:** Tabela `agent_config` (key/jsonb) no Supabase. O painel escreve direto via client do browser (RLS, role `authenticated`). O backend lê via `backend/services/config.py` (cache ~60s + fallback) usando a service role (bypassa RLS). `news.py` passa a ler as 6 chaves do config, com os valores atuais como default. Edição da lista de fontes valida contra a lista oficial da NewsAPI, servida por um endpoint backend (`/api/admin/newsapi-sources`) pra não expor a `NEWS_API_KEY` no browser.

**Tech Stack:** Python 3.12 / FastAPI / httpx (backend); Next.js 16 / TypeScript / @supabase/ssr (frontend); Supabase Postgres (config store).

## Global Constraints

- Backend: Python 3.12, FastAPI. snake_case funções/variáveis.
- Frontend: TypeScript, camelCase variáveis/funções, PascalCase componentes.
- Commits: mensagens em inglês, imperativas.
- TDD no backend; frontend valida via `npm run build` (sem testes de UI — YAGNI).
- O backend **nunca** quebra por config ausente/malformada: fallback pros defaults hardcoded.
- Auth backend já existe: `auth.verify_supabase_jwt` (JWKS, ES256/RS256).
- O painel lê config efetiva do endpoint `GET /api/admin/agent-config` (já existe) e escreve overrides direto no Supabase.
- Os testes atuais (127) continuam verdes. Em especial, `backend/tests/test_news.py` importa `SOURCES_FINANCE`, `SOURCES_TECH`, `_AI_QUERY`, `_RSS_FEEDS_AI` e chama `_collect_rss` com **tuplas `(nome, url)`** — esses contratos NÃO mudam.
- Backend lê Supabase com `SUPABASE_KEY` (service role) → bypassa RLS. Painel escreve com a publishable key + JWT do usuário → role `authenticated` → depende das policies de RLS.

---

### Task 1: Tabela `agent_config` no Supabase + leitura no backend

**Files:**
- Manual: SQL no Supabase SQL Editor (não versionado)
- Modify: `backend/services/supabase.py` (adicionar função no fim, antes de nenhuma — append)
- Test: `backend/tests/test_config_store.py`

**Interfaces:**
- Produces: `supabase.get_all_config() -> list[dict]` — retorna linhas `[{"key": str, "value": <json>}, ...]` da tabela `agent_config` (lista vazia se não houver linhas).

- [ ] **Step 1: Criar a tabela + RLS no Supabase**

No painel do Supabase → **SQL Editor** → rode:

```sql
create table if not exists public.agent_config (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now(),
  updated_by text
);

alter table public.agent_config enable row level security;

-- Painel (role authenticated) pode ler e escrever toda a config
create policy "authenticated read agent_config"
  on public.agent_config for select to authenticated using (true);
create policy "authenticated insert agent_config"
  on public.agent_config for insert to authenticated with check (true);
create policy "authenticated update agent_config"
  on public.agent_config for update to authenticated using (true) with check (true);
create policy "authenticated delete agent_config"
  on public.agent_config for delete to authenticated using (true);

grant select, insert, update, delete on public.agent_config to authenticated;
```

Confirme que a tabela aparece em **Table Editor → agent_config**.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_config_store.py
import os
from dotenv import load_dotenv
load_dotenv()
from backend.services import supabase


def test_get_all_config_returns_list():
    rows = supabase.get_all_config()
    assert isinstance(rows, list)
    for row in rows:
        assert "key" in row and "value" in row
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest backend/tests/test_config_store.py -v`
Expected: FAIL — `AttributeError: module 'backend.services.supabase' has no attribute 'get_all_config'`

- [ ] **Step 4: Add `get_all_config()` to supabase.py**

No fim de `backend/services/supabase.py`, adicione:

```python
def get_all_config() -> list[dict]:
    """Lê todas as linhas da tabela agent_config (key/value)."""
    with _client() as c:
        r = c.get("/agent_config?select=key,value")
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_config_store.py -v`
Expected: PASS (1 passed) — exige a tabela criada no Step 1.

- [ ] **Step 6: Commit**

```bash
git add backend/services/supabase.py backend/tests/test_config_store.py
git commit -m "feat: read agent_config rows from supabase"
```

---

### Task 2: Serviço `config.py` (cache + fallback + getters tipados)

**Files:**
- Create: `backend/services/config.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: `supabase.get_all_config()`.
- Produces:
  - `config.get(key: str, default)` — valor do Supabase ou `default`.
  - `config.get_list(key: str, default: list) -> list` — valor se for `list`, senão `default`.
  - `config.get_str(key: str, default: str) -> str` — valor se for `str` não-vazia, senão `default`.
  - `config.clear_cache()` — zera o cache (uso em testes).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config.py
from unittest.mock import patch

from backend.services import config


def _rows(d):
    return [{"key": k, "value": v} for k, v in d.items()]


def setup_function():
    config.clear_cache()


def test_get_returns_default_when_absent():
    with patch("backend.services.config.supabase.get_all_config", return_value=[]):
        assert config.get("news.x", "fallback") == "fallback"


def test_get_returns_value_when_present():
    with patch("backend.services.config.supabase.get_all_config",
               return_value=_rows({"news.x": ["a", "b"]})):
        assert config.get("news.x", None) == ["a", "b"]


def test_get_list_falls_back_on_type_mismatch():
    with patch("backend.services.config.supabase.get_all_config",
               return_value=_rows({"news.x": "not-a-list"})):
        assert config.get_list("news.x", ["d"]) == ["d"]


def test_get_str_falls_back_on_empty():
    with patch("backend.services.config.supabase.get_all_config",
               return_value=_rows({"news.q": "   "})):
        assert config.get_str("news.q", "default-q") == "default-q"


def test_falls_back_to_default_when_supabase_errors():
    with patch("backend.services.config.supabase.get_all_config",
               side_effect=RuntimeError("supabase down")):
        assert config.get("news.x", "fallback") == "fallback"


def test_cache_avoids_refetch_within_ttl():
    with patch("backend.services.config.supabase.get_all_config",
               return_value=_rows({"news.x": 1})) as m:
        config.get("news.x", None)
        config.get("news.x", None)
    assert m.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.config'`

- [ ] **Step 3: Create `backend/services/config.py`**

```python
import time

from backend.services import supabase

_CACHE_TTL = 60.0
_cache: dict | None = None
_cache_at: float = 0.0


def clear_cache() -> None:
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0


def _load() -> dict:
    """Carrega todas as configs (cache com TTL). Em falha, mantém o cache
    anterior ou retorna {} (tudo cai no default) — nunca propaga exceção."""
    global _cache, _cache_at
    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        return _cache
    try:
        rows = supabase.get_all_config()
        _cache = {r["key"]: r["value"] for r in rows}
        _cache_at = now
    except Exception:
        if _cache is None:
            return {}
        _cache_at = now  # mantém cache velho, evita martelar o banco
    return _cache if _cache is not None else {}


def get(key: str, default):
    val = _load().get(key)
    return default if val is None else val


def get_list(key: str, default: list) -> list:
    val = get(key, None)
    return val if isinstance(val, list) else default


def get_str(key: str, default: str) -> str:
    val = get(key, None)
    return val if isinstance(val, str) and val.strip() else default
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_config.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/services/config.py backend/tests/test_config.py
git commit -m "feat: add cached config service with hardcoded fallback"
```

---

### Task 3: `news.py` lê fontes/queries/feeds do config

**Files:**
- Modify: `backend/collectors/news.py`
- Test: `backend/tests/test_news_config.py`

**Interfaces:**
- Consumes: `config.get`, `config.get_list`, `config.get_str`.
- Produces (internos, novos): `news._sources_param(key: str, default_csv: str) -> str`, `news._feeds(key: str, default_tuples: list[tuple]) -> list[tuple]`.
- Mantém inalterados: `SOURCES_FINANCE`, `SOURCES_TECH`, `_FINANCE_QUERY`, `_AI_QUERY` (strings), `_RSS_FEEDS`, `_RSS_FEEDS_AI` (list[tuple]), assinatura de `_collect_rss(client, feeds, vistos)` com `feeds` = list[tuple], e o shape de `describe_config()`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_news_config.py
from unittest.mock import patch

from backend.collectors import news


def test_describe_config_reflects_override():
    def fake_get(key, default=None):
        overrides = {
            "news.sources_finance": ["reuters", "cnbc"],
            "news.finance_query": "custom query",
            "news.rss_feeds": [{"nome": "Meu Feed", "url": "https://x.com/rss"}],
        }
        return overrides.get(key, default)

    with patch("backend.collectors.news.config.get", side_effect=fake_get):
        cfg = news.describe_config()

    assert cfg["sources_finance"] == ["reuters", "cnbc"]
    assert cfg["finance_query"] == "custom query"
    assert cfg["rss_feeds"] == [{"nome": "Meu Feed", "url": "https://x.com/rss"}]


def test_describe_config_uses_defaults_when_no_override():
    with patch("backend.collectors.news.config.get", side_effect=lambda k, d=None: d):
        cfg = news.describe_config()
    assert "reuters" in cfg["sources_finance"]
    assert "inflation" in cfg["finance_query"]
    assert any(f["nome"] == "MIT Technology Review" for f in cfg["rss_feeds_ai"])


def test_feeds_helper_converts_config_dicts_to_tuples():
    with patch("backend.collectors.news.config.get",
               return_value=[{"nome": "F", "url": "https://f.com/rss"}]):
        assert news._feeds("rss_feeds", []) == [("F", "https://f.com/rss")]


def test_feeds_helper_falls_back_on_empty_config():
    with patch("backend.collectors.news.config.get", return_value=None):
        assert news._feeds("rss_feeds", [("D", "https://d.com")]) == [("D", "https://d.com")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_news_config.py -v`
Expected: FAIL — `AttributeError: module 'backend.collectors.news' has no attribute 'config'` (e `_feeds` inexistente)

- [ ] **Step 3: Import config and add helpers in news.py**

Em `backend/collectors/news.py`, no topo (após `import httpx`), adicione:

```python
from backend.services import config
```

Logo após a definição de `_RSS_FEEDS_AI` (linha ~68), adicione os helpers:

```python
def _sources_param(key: str, default_csv: str) -> str:
    """Lista de fontes do config (list[str]) → CSV; senão o default CSV."""
    val = config.get("news." + key, None)
    if isinstance(val, list) and val:
        return ",".join(str(s) for s in val)
    return default_csv


def _feeds(key: str, default_tuples: list[tuple]) -> list[tuple]:
    """Feeds do config (list[{nome,url}]) → list[(nome,url)]; senão o default."""
    val = config.get("news." + key, None)
    if isinstance(val, list) and val:
        out = [
            (str(f.get("nome", "")), f["url"])
            for f in val
            if isinstance(f, dict) and isinstance(f.get("url"), str) and f.get("url")
        ]
        if out:
            return out
    return default_tuples
```

- [ ] **Step 4: Use config in `collect()`**

Em `collect()`, substitua os usos diretos das constantes. Troque o bloco da chamada finance:

```python
            artigos.extend(_fetch_newsapi(client, NEWSAPI_EVERYTHING, {
                "apiKey": api_key,
                "sources": SOURCES_FINANCE,
                "q": _FINANCE_QUERY,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 15,
            }, vistos, errors, "finance"))
```

por:

```python
            artigos.extend(_fetch_newsapi(client, NEWSAPI_EVERYTHING, {
                "apiKey": api_key,
                "sources": _sources_param("sources_finance", SOURCES_FINANCE),
                "q": config.get_str("news.finance_query", _FINANCE_QUERY),
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 15,
            }, vistos, errors, "finance"))
```

Troque o bloco da chamada AI/tech:

```python
                artigos.extend(_fetch_newsapi(client, NEWSAPI_EVERYTHING, {
                    "apiKey": api_key,
                    "sources": SOURCES_TECH,
                    "q": _AI_QUERY,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                }, vistos, errors, "ai"))
```

por:

```python
                artigos.extend(_fetch_newsapi(client, NEWSAPI_EVERYTHING, {
                    "apiKey": api_key,
                    "sources": _sources_param("sources_tech", SOURCES_TECH),
                    "q": config.get_str("news.ai_query", _AI_QUERY),
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                }, vistos, errors, "ai"))
```

Troque a coleta de RSS:

```python
        artigos.extend(_collect_rss(client, _RSS_FEEDS + _RSS_FEEDS_AI, vistos))
```

por:

```python
        feeds = _feeds("rss_feeds", _RSS_FEEDS) + _feeds("rss_feeds_ai", _RSS_FEEDS_AI)
        artigos.extend(_collect_rss(client, feeds, vistos))
```

- [ ] **Step 5: Update `describe_config()` to reflect effective config**

Substitua o corpo de `describe_config()` por:

```python
def describe_config() -> dict:
    """Snapshot read-only da config efetiva (override do banco ou default)."""
    return {
        "sources_finance": _sources_param("sources_finance", SOURCES_FINANCE).split(","),
        "sources_tech": _sources_param("sources_tech", SOURCES_TECH).split(","),
        "finance_query": config.get_str("news.finance_query", _FINANCE_QUERY),
        "ai_query": config.get_str("news.ai_query", _AI_QUERY),
        "rss_feeds": [{"nome": n, "url": u} for n, u in _feeds("rss_feeds", _RSS_FEEDS)],
        "rss_feeds_ai": [{"nome": n, "url": u} for n, u in _feeds("rss_feeds_ai", _RSS_FEEDS_AI)],
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest backend/tests/test_news_config.py backend/tests/test_news.py backend/tests/test_news_describe.py -v`
Expected: PASS — novos testes + os 21 de `test_news.py` + o de `test_news_describe.py` continuam verdes (sem override, tudo cai nos defaults).

- [ ] **Step 7: Commit**

```bash
git add backend/collectors/news.py backend/tests/test_news_config.py
git commit -m "feat: read news sources, feeds and queries from config"
```

---

### Task 4: Endpoint `GET /api/admin/newsapi-sources`

**Files:**
- Modify: `backend/api/admin.py`
- Test: `backend/tests/test_admin_sources.py`

**Interfaces:**
- Consumes: `auth.verify_supabase_jwt`, `os.environ["NEWS_API_KEY"]`, httpx.
- Produces: rota `GET /api/admin/newsapi-sources` → `{"sources": [{"id","name","category","language","country"}, ...]}`; 401 sem token.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_sources.py
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


_NEWSAPI_PAYLOAD = {
    "status": "ok",
    "sources": [
        {"id": "reuters", "name": "Reuters", "category": "general",
         "language": "en", "country": "us", "description": "x", "url": "x"},
    ],
}


def test_newsapi_sources_requires_auth():
    resp = client.get("/api/admin/newsapi-sources")
    assert resp.status_code == 401


def test_newsapi_sources_returns_simplified_list():
    fake = SimpleNamespace(
        status_code=200,
        json=lambda: _NEWSAPI_PAYLOAD,
        raise_for_status=lambda: None,
    )
    with patch.object(auth, "_get_jwks_client", return_value=_FakeJWKS()), \
         patch("backend.api.admin.httpx.get", return_value=fake):
        resp = client.get("/api/admin/newsapi-sources",
                          headers={"Authorization": f"Bearer {_token()}"})
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    assert sources == [{"id": "reuters", "name": "Reuters", "category": "general",
                        "language": "en", "country": "us"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_admin_sources.py -v`
Expected: FAIL — 404 (rota não existe)

- [ ] **Step 3: Add the endpoint to admin.py**

Em `backend/api/admin.py`, adicione no topo:

```python
import os

import httpx
```

E adicione a rota (após `get_agent_config`):

```python
@router.get("/api/admin/newsapi-sources")
def get_newsapi_sources(user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Lista as fontes disponíveis na NewsAPI (id/name/category) para o painel.
    Busca server-side para não expor a NEWS_API_KEY no browser."""
    api_key = os.environ.get("NEWS_API_KEY", "")
    if not api_key:
        return {"sources": []}
    resp = httpx.get(
        "https://newsapi.org/v2/top-headlines/sources",
        params={"apiKey": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    raw = resp.json().get("sources", [])
    sources = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "category": s.get("category"),
            "language": s.get("language"),
            "country": s.get("country"),
        }
        for s in raw
    ]
    return {"sources": sources}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_admin_sources.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run full backend suite**

Run: `pytest backend/tests/ -q`
Expected: PASS — todos verdes (Tasks 1-4 + os anteriores)

- [ ] **Step 6: Commit**

```bash
git add backend/api/admin.py backend/tests/test_admin_sources.py
git commit -m "feat: add newsapi sources listing endpoint for the panel"
```

---

### Task 5: Frontend — helpers de escrita no Supabase + API de fontes

**Files:**
- Modify: `frontend/lib/api.ts`
- Create: `frontend/lib/config.ts`

**Interfaces:**
- Produces: `fetchNewsApiSources()` em `lib/api.ts` → `Promise<NewsApiSource[]>` com `type NewsApiSource = { id: string; name: string; category: string; language: string; country: string }`.
- Produces: `upsertConfig(key: string, value: unknown)` e `deleteConfig(key: string)` em `lib/config.ts` (escrevem em `agent_config` via client do browser).

- [ ] **Step 1: Add `fetchNewsApiSources` to lib/api.ts**

No fim de `frontend/lib/api.ts`, adicione:

```typescript
export type NewsApiSource = {
  id: string;
  name: string;
  category: string;
  language: string;
  country: string;
};

export async function fetchNewsApiSources(): Promise<NewsApiSource[]> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/newsapi-sources`,
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
  );
  if (!res.ok) {
    throw new Error(`backend ${res.status}`);
  }
  const body = await res.json();
  return body.sources as NewsApiSource[];
}
```

- [ ] **Step 2: Create lib/config.ts (browser write helpers)**

```typescript
// frontend/lib/config.ts
"use client";

import { createClient } from "@/lib/supabase/client";

export async function upsertConfig(key: string, value: unknown): Promise<void> {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  const { error } = await supabase.from("agent_config").upsert(
    {
      key,
      value,
      updated_by: user?.email ?? null,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "key" },
  );
  if (error) throw new Error(error.message);
}

export async function deleteConfig(key: string): Promise<void> {
  const supabase = createClient();
  const { error } = await supabase.from("agent_config").delete().eq("key", key);
  if (error) throw new Error(error.message);
}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build && cd ..`
Expected: build conclui sem erro de tipos.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api.ts frontend/lib/config.ts
git commit -m "feat: add newsapi sources fetch and agent_config write helpers"
```

---

### Task 6: Frontend — página `/noticias/fontes` + formulário + nav

**Files:**
- Create: `frontend/app/noticias/fontes/page.tsx`
- Create: `frontend/components/fontes-form.tsx`
- Modify: `frontend/components/shell.tsx` (adicionar item de nav)

**Interfaces:**
- Consumes: `fetchAgentConfig` (config efetiva), `fetchNewsApiSources`, `upsertConfig`, `deleteConfig`, `Shell`.
- Produces: rota `/noticias/fontes` (server component que injeta dados no `<FontesForm>`).

- [ ] **Step 1: Add "Notícias" to the nav shell**

Em `frontend/components/shell.tsx`, no array `NAV`, adicione a entrada:

```typescript
const NAV = [
  { href: "/", label: "Visão geral" },
  { href: "/agente", label: "Agente" },
  { href: "/noticias/fontes", label: "Notícias" },
];
```

- [ ] **Step 2: Create the FontesForm client component**

```tsx
// frontend/components/fontes-form.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { upsertConfig, deleteConfig } from "@/lib/config";
import type { NewsApiSource } from "@/lib/api";

type Feed = { nome: string; url: string };

type Props = {
  initial: {
    sourcesFinance: string[];
    sourcesTech: string[];
    rssFeeds: Feed[];
    rssFeedsAi: Feed[];
    financeQuery: string;
    aiQuery: string;
  };
  available: NewsApiSource[];
};

function SourcePicker({
  label,
  selected,
  onToggle,
  options,
}: {
  label: string;
  selected: string[];
  onToggle: (id: string) => void;
  options: NewsApiSource[];
}) {
  const [filter, setFilter] = useState("");
  const shown = options.filter((o) =>
    o.name.toLowerCase().includes(filter.toLowerCase()),
  );
  return (
    <div>
      <span className="eyebrow">{label}</span>
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="filtrar fontes"
        className="mt-1 w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-bone placeholder:text-slate/50 focus:border-gold focus:outline-none"
      />
      <div className="mt-2 max-h-48 overflow-auto rounded-md border border-line">
        {shown.map((o) => (
          <label key={o.id} className="flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-raised/40">
            <input
              type="checkbox"
              checked={selected.includes(o.id)}
              onChange={() => onToggle(o.id)}
            />
            <span className="readout text-bone">{o.id}</span>
            <span className="text-slate">· {o.name}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

function FeedEditor({
  label,
  feeds,
  setFeeds,
}: {
  label: string;
  feeds: Feed[];
  setFeeds: (f: Feed[]) => void;
}) {
  return (
    <div>
      <span className="eyebrow">{label}</span>
      <div className="mt-2 space-y-2">
        {feeds.map((f, i) => (
          <div key={i} className="flex gap-2">
            <input
              value={f.nome}
              onChange={(e) => setFeeds(feeds.map((x, j) => (j === i ? { ...x, nome: e.target.value } : x)))}
              placeholder="nome"
              className="w-1/3 rounded-md border border-line bg-ink px-2 py-1.5 text-sm text-bone"
            />
            <input
              value={f.url}
              onChange={(e) => setFeeds(feeds.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))}
              placeholder="https://…/rss"
              className="flex-1 rounded-md border border-line bg-ink px-2 py-1.5 text-sm text-bone"
            />
            <button
              type="button"
              onClick={() => setFeeds(feeds.filter((_, j) => j !== i))}
              className="rounded-md border border-line px-2 text-slate hover:text-bone"
            >
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setFeeds([...feeds, { nome: "", url: "" }])}
          className="text-sm text-gold hover:text-bone"
        >
          + adicionar feed
        </button>
      </div>
    </div>
  );
}

export default function FontesForm({ initial, available }: Props) {
  const router = useRouter();
  const [sourcesFinance, setSourcesFinance] = useState(initial.sourcesFinance);
  const [sourcesTech, setSourcesTech] = useState(initial.sourcesTech);
  const [rssFeeds, setRssFeeds] = useState(initial.rssFeeds);
  const [rssFeedsAi, setRssFeedsAi] = useState(initial.rssFeedsAi);
  const [financeQuery, setFinanceQuery] = useState(initial.financeQuery);
  const [aiQuery, setAiQuery] = useState(initial.aiQuery);
  const [status, setStatus] = useState<string | null>(null);

  const toggle = (list: string[], set: (v: string[]) => void, id: string) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  async function save() {
    setStatus("Salvando…");
    try {
      const cleanFeeds = (f: Feed[]) => f.filter((x) => x.url.trim());
      await upsertConfig("news.sources_finance", sourcesFinance);
      await upsertConfig("news.sources_tech", sourcesTech);
      await upsertConfig("news.rss_feeds", cleanFeeds(rssFeeds));
      await upsertConfig("news.rss_feeds_ai", cleanFeeds(rssFeedsAi));
      await upsertConfig("news.finance_query", financeQuery);
      await upsertConfig("news.ai_query", aiQuery);
      setStatus("Salvo. As mudanças valem na próxima coleta (~1 min de cache).");
      router.refresh();
    } catch (e) {
      setStatus("Erro ao salvar: " + (e instanceof Error ? e.message : "desconhecido"));
    }
  }

  async function restoreDefaults() {
    setStatus("Restaurando padrões…");
    try {
      for (const key of [
        "news.sources_finance", "news.sources_tech", "news.rss_feeds",
        "news.rss_feeds_ai", "news.finance_query", "news.ai_query",
      ]) {
        await deleteConfig(key);
      }
      setStatus("Padrões restaurados. Recarregue a página para ver os valores originais.");
      router.refresh();
    } catch (e) {
      setStatus("Erro ao restaurar: " + (e instanceof Error ? e.message : "desconhecido"));
    }
  }

  return (
    <div className="space-y-8">
      <section className="rounded-lg border border-line bg-surface p-5 space-y-4">
        <h2 className="font-display text-sm font-medium uppercase tracking-wide text-slate">Fontes NewsAPI</h2>
        <SourcePicker label="Finanças" selected={sourcesFinance} options={available}
          onToggle={(id) => toggle(sourcesFinance, setSourcesFinance, id)} />
        <SourcePicker label="Tech / IA" selected={sourcesTech} options={available}
          onToggle={(id) => toggle(sourcesTech, setSourcesTech, id)} />
      </section>

      <section className="rounded-lg border border-line bg-surface p-5 space-y-4">
        <h2 className="font-display text-sm font-medium uppercase tracking-wide text-slate">Feeds RSS</h2>
        <FeedEditor label="Geral" feeds={rssFeeds} setFeeds={setRssFeeds} />
        <FeedEditor label="IA" feeds={rssFeedsAi} setFeeds={setRssFeedsAi} />
      </section>

      <section className="rounded-lg border border-line bg-surface p-5 space-y-4">
        <h2 className="font-display text-sm font-medium uppercase tracking-wide text-slate">Queries de busca</h2>
        <label className="block">
          <span className="eyebrow">Finanças</span>
          <textarea value={financeQuery} onChange={(e) => setFinanceQuery(e.target.value)} rows={3}
            className="mt-1 w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-bone" />
        </label>
        <label className="block">
          <span className="eyebrow">IA</span>
          <textarea value={aiQuery} onChange={(e) => setAiQuery(e.target.value)} rows={3}
            className="mt-1 w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-bone" />
        </label>
      </section>

      {status && <p className="text-sm text-gold">{status}</p>}

      <div className="flex gap-3">
        <button onClick={save}
          className="rounded-md bg-gold px-4 py-2 font-medium text-ink hover:bg-bone">
          Salvar
        </button>
        <button onClick={restoreDefaults}
          className="rounded-md border border-line px-4 py-2 text-sm text-slate hover:text-bone">
          Restaurar padrões
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create the page (server component)**

```tsx
// frontend/app/noticias/fontes/page.tsx
import Shell from "@/components/shell";
import FontesForm from "@/components/fontes-form";
import { fetchAgentConfig, fetchNewsApiSources, type NewsApiSource } from "@/lib/api";

export default async function FontesPage() {
  let initial = null;
  let available: NewsApiSource[] = [];
  let err: string | null = null;
  try {
    const [cfg, sources] = await Promise.all([fetchAgentConfig(), fetchNewsApiSources()]);
    available = sources;
    initial = {
      sourcesFinance: cfg.news.sources_finance,
      sourcesTech: cfg.news.sources_tech,
      rssFeeds: cfg.news.rss_feeds,
      rssFeedsAi: cfg.news.rss_feeds_ai,
      financeQuery: cfg.news.finance_query,
      aiQuery: cfg.news.ai_query,
    };
  } catch (e) {
    err = e instanceof Error ? e.message : "erro desconhecido";
  }

  return (
    <Shell active="/noticias/fontes">
      <main className="mx-auto max-w-3xl px-8 py-12">
        <span className="eyebrow">Notícias</span>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-bone">
          Fontes & buscas
        </h1>
        <p className="mt-2 max-w-xl text-sm text-slate">
          Controle de quais fontes e termos o agente usa para coletar notícias.
          Mudanças valem na próxima coleta (cache de ~1 min).
        </p>

        <div className="mt-8">
          {err || !initial ? (
            <div className="rounded-lg border border-line bg-surface p-6">
              <p className="text-sm text-bone">Não foi possível carregar a config.</p>
              <p className="mt-1 readout text-xs text-slate">backend: {err}</p>
            </div>
          ) : (
            <FontesForm initial={initial} available={available} />
          )}
        </div>
      </main>
    </Shell>
  );
}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build && cd ..`
Expected: build conclui; rota `/noticias/fontes` aparece como `ƒ` (dynamic).

- [ ] **Step 5: Manual end-to-end check**

Com `npm run dev` + backend local (`uvicorn backend.api.main:app --port 8000`) e `.env.local` com `NEXT_PUBLIC_BACKEND_URL=http://localhost:8000`:
1. Logar, abrir `/noticias/fontes`
2. Confirmar que as fontes atuais vêm marcadas, feeds e queries preenchidos
3. Desmarcar uma fonte, salvar → ver "Salvo"
4. Conferir na tabela `agent_config` do Supabase que a linha `news.sources_finance` foi gravada
5. Abrir `/agente` → a seção Fontes reflete a mudança
6. "Restaurar padrões" → as linhas somem da tabela

- [ ] **Step 6: Commit**

```bash
git add frontend/app/noticias frontend/components/fontes-form.tsx frontend/components/shell.tsx
git commit -m "feat: add editable news sources, feeds and queries page"
```

---

## Pós-Fase 1 (deploy)

- Push na `master` → backend e painel redeployam (deploy de produção).
- Garantir que a tabela `agent_config` (Task 1) foi criada no Supabase **antes** do deploy, senão o painel grava com erro de RLS/tabela inexistente (o backend só cai no fallback, sem quebrar).

## Self-Review

- **Spec coverage:** config store (Task 1) ✓; serviço cache+fallback (Task 2) ✓; `news.py` lê do config (Task 3) ✓; edição validada contra NewsAPI (Task 4 endpoint + Task 6 picker) ✓; escrita via Supabase RLS (Task 5) ✓; página de edição + nav (Task 6) ✓; queries editáveis (Tasks 3,6) ✓.
- **Placeholders:** nenhum — todo passo tem código/SQL/comando concreto.
- **Type consistency:** `config.get/get_list/get_str` (Task 2) usados igual em Task 3. `news._sources_param`/`_feeds` definidos e usados em Task 3. Chaves `news.sources_finance|sources_tech|rss_feeds|rss_feeds_ai|finance_query|ai_query` idênticas entre backend (Task 3) e frontend (Tasks 5,6). `NewsApiSource` (Task 5) consumido em Task 6. `fetchAgentConfig().news.*` shape bate com `reporter`/`news.describe_config()` da Fase 0.
- **Compat dos testes:** `SOURCES_FINANCE`/`SOURCES_TECH` seguem strings CSV, `_FINANCE_QUERY`/`_AI_QUERY` strings, `_RSS_FEEDS(_AI)` list[tuple], `_collect_rss` recebe tuplas — `test_news.py` (21 testes) intacto.
