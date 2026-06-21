# Editor de prompts do relatório no painel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao admin uma tela no painel para editar, resetar e testar os 6 prompts de seção do relatório diário, persistidos em `agent_config`.

**Architecture:** Backend ganha uma camada de escrita em `agent_config` (`supabase.upsert_config`/`delete_config`), um helper `report_prompts.describe_prompts()` (efetivo + is_custom + default), suporte a prompt-override no preview (`report_engine.preview_section`) e 4 endpoints admin. Frontend ganha uma aba "Relatório" com um card por seção (textarea, contador, badge default/custom, Salvar/Resetar/Testar).

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend); Next.js (App Router) / React / TypeScript / Tailwind (frontend); Supabase PostgREST; Anthropic SDK.

## Global Constraints

- Todos os endpoints novos são admin-only: `Depends(auth.verify_supabase_jwt)`.
- Seções válidas (ordem canônica): `commodities, bolsas, cambio_cripto, noticias, analise, politica` — fonte: `report_prompts.SECTIONS`.
- Chave de config por seção: `report_prompt_<section>` — usar `report_prompts._CONFIG_KEY[section]`, nunca concatenar à mão.
- Após qualquer escrita de prompt, chamar `config.clear_cache()` (cache TTL 60s por instância; propagação entre instâncias serverless pode levar até 60s — aceitável, documentado na spec).
- Testes unitários: marcar `@pytest.mark.unit`; fazer monkeypatch na **camada de serviço** (supabase/report_engine/report_prompts/config), nunca DB real. Wrappers PostgREST crus (`upsert_config`/`delete_config`) não recebem teste unit dedicado (segue o padrão de `schedules.replace_for_phone`).
- Gate de CI: `pytest -m unit`. Frontend: `npx tsc --noEmit` limpo.
- Frontend: seguir os padrões existentes (`lib/api.ts` para fetch em server component; `lib/config.ts` para mutações client com `session.access_token`). NÃO introduzir APIs novas do Next — esta versão do Next tem breaking changes (ver `frontend/AGENTS.md`).
- Deploy = `git push` na master (não fazer push automático; só commitar local salvo instrução do usuário).

---

### Task 1: Camada de escrita em `agent_config` + `describe_prompts`

**Files:**
- Modify: `backend/services/supabase.py` (adicionar 2 funções no fim)
- Modify: `backend/services/report_prompts.py` (adicionar `describe_prompts`)
- Test: `backend/tests/test_report_prompts.py` (adicionar testes de `describe_prompts`)

**Interfaces:**
- Produces:
  - `supabase.upsert_config(key: str, value) -> None`
  - `supabase.delete_config(key: str) -> None`
  - `report_prompts.describe_prompts() -> list[dict]` — cada item `{"section": str, "value": str, "is_custom": bool, "default": str}`, na ordem de `SECTIONS`.

- [ ] **Step 1: Escrever o teste que falha para `describe_prompts`**

Em `backend/tests/test_report_prompts.py` (adicionar ao final; manter imports existentes, garantir `import pytest` e `from backend.services import report_prompts, config`):

```python
@pytest.mark.unit
def test_describe_prompts_marks_custom_and_default(monkeypatch):
    overrides = {"report_prompt_bolsas": "MEU PROMPT BOLSAS"}
    monkeypatch.setattr(config, "get", lambda key, default=None: overrides.get(key, default))

    out = {p["section"]: p for p in report_prompts.describe_prompts()}

    assert set(out) == set(report_prompts.SECTIONS)
    assert out["bolsas"]["is_custom"] is True
    assert out["bolsas"]["value"] == "MEU PROMPT BOLSAS"
    assert out["bolsas"]["default"] == report_prompts.DEFAULTS["bolsas"]

    assert out["commodities"]["is_custom"] is False
    assert out["commodities"]["value"] == report_prompts.DEFAULTS["commodities"]


@pytest.mark.unit
def test_describe_prompts_blank_override_is_not_custom(monkeypatch):
    monkeypatch.setattr(config, "get", lambda key, default=None: "   " if key == "report_prompt_analise" else default)
    out = {p["section"]: p for p in report_prompts.describe_prompts()}
    assert out["analise"]["is_custom"] is False
    assert out["analise"]["value"] == report_prompts.DEFAULTS["analise"]
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `python -m pytest backend/tests/test_report_prompts.py -m unit -v`
Expected: FAIL com `AttributeError: module 'backend.services.report_prompts' has no attribute 'describe_prompts'`.

- [ ] **Step 3: Implementar `describe_prompts`**

Em `backend/services/report_prompts.py`, ao final do arquivo:

```python
def describe_prompts() -> list[dict]:
    out = []
    for section in SECTIONS:
        override = config.get(_CONFIG_KEY[section], None)
        is_custom = isinstance(override, str) and override.strip() != ""
        out.append({
            "section": section,
            "value": override if is_custom else DEFAULTS[section],
            "is_custom": is_custom,
            "default": DEFAULTS[section],
        })
    return out
```

- [ ] **Step 4: Implementar `upsert_config`/`delete_config`**

Em `backend/services/supabase.py`, ao final do arquivo:

```python
def upsert_config(key: str, value) -> None:
    with _client() as c:
        r = c.post(
            "/agent_config",
            json={"key": key, "value": value},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        r.raise_for_status()


def delete_config(key: str) -> None:
    with _client() as c:
        r = c.delete(f"/agent_config?key=eq.{_f(key)}")
        r.raise_for_status()
```

- [ ] **Step 5: Rodar os testes e ver passar**

Run: `python -m pytest backend/tests/test_report_prompts.py -m unit -v`
Expected: PASS (todos, incluindo os novos).

- [ ] **Step 6: Commit**

```bash
git add backend/services/supabase.py backend/services/report_prompts.py backend/tests/test_report_prompts.py
git commit -m "feat(backend): agent_config write layer + describe_prompts helper"
```

---

### Task 2: Preview por seção com prompt override (`report_engine.preview_section`)

**Files:**
- Modify: `backend/services/report_engine.py` (`_render` ganha param `prompt`; novo `preview_section`)
- Test: `backend/tests/test_report_engine.py` (adicionar testes)

**Interfaces:**
- Consumes: `report_engine._collect(section)`, `report_prompts.get_prompt(section)`.
- Produces: `report_engine.preview_section(section: str, prompt: str | None, client=None) -> str`.

- [ ] **Step 1: Escrever os testes que falham**

Em `backend/tests/test_report_engine.py` (adicionar ao final; garantir `import pytest` e `from backend.services import report_engine, report_prompts`):

```python
class _FakeBlock:
    def __init__(self, text):
        self.text = text


class _FakeMsg:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, captured):
        self._captured = captured

    def create(self, **kw):
        self._captured.update(kw)
        return _FakeMsg("SAIDA GERADA")


class _FakeClient:
    def __init__(self, captured):
        self.messages = _FakeMessages(captured)


@pytest.mark.unit
def test_preview_section_uses_given_prompt(monkeypatch):
    monkeypatch.setattr(report_engine, "_collect", lambda section: {"data": {"x": 1}})
    captured = {}
    text = report_engine.preview_section("bolsas", "PROMPT_OVERRIDE", client=_FakeClient(captured))
    assert text == "SAIDA GERADA"
    assert captured["system"] == "PROMPT_OVERRIDE"


@pytest.mark.unit
def test_preview_section_falls_back_to_stored_prompt(monkeypatch):
    monkeypatch.setattr(report_engine, "_collect", lambda section: {"data": {"x": 1}})
    monkeypatch.setattr(report_prompts, "get_prompt", lambda section: "STORED_PROMPT")
    captured = {}
    report_engine.preview_section("bolsas", None, client=_FakeClient(captured))
    assert captured["system"] == "STORED_PROMPT"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest backend/tests/test_report_engine.py -m unit -v`
Expected: FAIL com `AttributeError: ... has no attribute 'preview_section'`.

- [ ] **Step 3: Implementar override no `_render` e `preview_section`**

Em `backend/services/report_engine.py`, trocar a assinatura/início de `_render`:

```python
def _render(section: str, ctx: dict, client, prompt: str | None = None) -> str:
    prompt = prompt or report_prompts.get_prompt(section)
    resp = client.messages.create(
```

(o resto de `_render` permanece igual.)

E adicionar, após `generate_sections`:

```python
def preview_section(section: str, prompt: str | None, client=None) -> str:
    if section not in _SECTION_ORDER:
        raise KeyError(section)
    if client is None:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"],
                           timeout=_ANTHROPIC_TIMEOUT, max_retries=1)
    ctx = _collect(section)
    return _render(section, ctx, client, prompt)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest backend/tests/test_report_engine.py -m unit -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/report_engine.py backend/tests/test_report_engine.py
git commit -m "feat(backend): preview_section with prompt override"
```

---

### Task 3: Endpoints admin (GET/PUT/DELETE report-prompts + preview-section)

**Files:**
- Modify: `backend/api/admin.py` (imports + 4 endpoints + 2 Pydantic bodies)
- Test: `backend/tests/test_admin_report_prompts.py` (criar)

**Interfaces:**
- Consumes: `report_prompts.describe_prompts`, `report_prompts.SECTIONS`, `report_prompts._CONFIG_KEY`, `supabase.upsert_config`, `supabase.delete_config`, `config.clear_cache`, `report_engine.preview_section`.
- Produces (rotas no `admin.router`, já incluído em `main.py`):
  - `GET /api/admin/report-prompts` → `{"prompts": [...]}`
  - `PUT /api/admin/report-prompts/{section}` body `{"prompt": str}` → `{"ok": True, "is_custom": True}`
  - `DELETE /api/admin/report-prompts/{section}` → `{"ok": True, "is_custom": False}`
  - `POST /api/admin/preview-section` body `{"section": str, "prompt": str}` → `{"text": str}`

- [ ] **Step 1: Escrever os testes que falham**

Criar `backend/tests/test_admin_report_prompts.py`:

```python
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.services import auth, supabase, config, report_prompts, report_engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_auth():
    app.dependency_overrides[auth.verify_supabase_jwt] = lambda: {"sub": "admin"}
    yield
    app.dependency_overrides.clear()


@pytest.mark.unit
def test_get_report_prompts(monkeypatch):
    monkeypatch.setattr(report_prompts, "describe_prompts",
                        lambda: [{"section": "bolsas", "value": "V", "is_custom": True, "default": "D"}])
    r = client.get("/api/admin/report-prompts")
    assert r.status_code == 200
    assert r.json() == {"prompts": [{"section": "bolsas", "value": "V", "is_custom": True, "default": "D"}]}


@pytest.mark.unit
def test_put_report_prompt_upserts_and_clears_cache(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase, "upsert_config", lambda k, v: captured.update(key=k, val=v))
    monkeypatch.setattr(config, "clear_cache", lambda: captured.update(cleared=True))
    r = client.put("/api/admin/report-prompts/bolsas", json={"prompt": "NOVO PROMPT"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "is_custom": True}
    assert captured == {"key": "report_prompt_bolsas", "val": "NOVO PROMPT", "cleared": True}


@pytest.mark.unit
def test_put_report_prompt_rejects_unknown_section():
    r = client.put("/api/admin/report-prompts/inexistente", json={"prompt": "x"})
    assert r.status_code == 400


@pytest.mark.unit
def test_delete_report_prompt_resets(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase, "delete_config", lambda k: captured.update(key=k))
    monkeypatch.setattr(config, "clear_cache", lambda: captured.update(cleared=True))
    r = client.delete("/api/admin/report-prompts/analise")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "is_custom": False}
    assert captured == {"key": "report_prompt_analise", "cleared": True}


@pytest.mark.unit
def test_preview_section_returns_text(monkeypatch):
    monkeypatch.setattr(report_engine, "preview_section", lambda section, prompt, **k: f"OUT:{section}:{prompt}")
    r = client.post("/api/admin/preview-section", json={"section": "noticias", "prompt": "P"})
    assert r.status_code == 200
    assert r.json() == {"text": "OUT:noticias:P"}


@pytest.mark.unit
def test_preview_section_rejects_unknown_section():
    r = client.post("/api/admin/preview-section", json={"section": "nope", "prompt": "P"})
    assert r.status_code == 400
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest backend/tests/test_admin_report_prompts.py -m unit -v`
Expected: FAIL (404 nas rotas inexistentes / endpoints ausentes).

- [ ] **Step 3: Implementar os endpoints**

Em `backend/api/admin.py`, ajustar imports (linha 4 e 7):

```python
from fastapi import APIRouter, Depends, HTTPException
```
```python
from backend.services import reporter, auth, supabase, report_engine, schedules, config, report_prompts
```

E adicionar ao final do arquivo:

```python
@router.get("/api/admin/report-prompts")
def get_report_prompts(user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    """Os 6 prompts de seção: valor efetivo, se é custom e o default."""
    return {"prompts": report_prompts.describe_prompts()}


class ReportPromptBody(BaseModel):
    prompt: str


@router.put("/api/admin/report-prompts/{section}")
def put_report_prompt(section: str, body: ReportPromptBody,
                      user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    if section not in report_prompts.SECTIONS:
        raise HTTPException(status_code=400, detail="seção inválida")
    supabase.upsert_config(report_prompts._CONFIG_KEY[section], body.prompt)
    config.clear_cache()
    return {"ok": True, "is_custom": True}


@router.delete("/api/admin/report-prompts/{section}")
def delete_report_prompt(section: str,
                         user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    if section not in report_prompts.SECTIONS:
        raise HTTPException(status_code=400, detail="seção inválida")
    supabase.delete_config(report_prompts._CONFIG_KEY[section])
    config.clear_cache()
    return {"ok": True, "is_custom": False}


class PreviewSectionBody(BaseModel):
    section: str
    prompt: str


@router.post("/api/admin/preview-section")
def preview_section(body: PreviewSectionBody,
                    user: dict = Depends(auth.verify_supabase_jwt)) -> dict:
    if body.section not in report_prompts.SECTIONS:
        raise HTTPException(status_code=400, detail="seção inválida")
    text = report_engine.preview_section(body.section, body.prompt)
    return {"text": text}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest backend/tests/test_admin_report_prompts.py -m unit -v`
Expected: PASS.

- [ ] **Step 5: Rodar o gate completo de unit**

Run: `python -m pytest -m unit -q`
Expected: PASS (os 41 anteriores + os novos).

- [ ] **Step 6: Commit**

```bash
git add backend/api/admin.py backend/tests/test_admin_report_prompts.py
git commit -m "feat(backend): admin endpoints to read/edit/reset/preview report prompts"
```

---

### Task 4: Funções de API no frontend

**Files:**
- Modify: `frontend/lib/api.ts` (tipo `ReportPrompt` + `fetchReportPrompts` server-side)
- Modify: `frontend/lib/config.ts` (`saveReportPrompt`, `resetReportPrompt`, `previewSection` client-side)

**Interfaces:**
- Produces:
  - `lib/api.ts`: `type ReportPrompt = { section: string; value: string; is_custom: boolean; default: string }`; `fetchReportPrompts(): Promise<ReportPrompt[]>`
  - `lib/config.ts`: `saveReportPrompt(section, prompt): Promise<void>`, `resetReportPrompt(section): Promise<void>`, `previewSection(section, prompt): Promise<string>`

- [ ] **Step 1: Adicionar `fetchReportPrompts` em `lib/api.ts`**

Ao final de `frontend/lib/api.ts`:

```ts
export type ReportPrompt = {
  section: string;
  value: string;
  is_custom: boolean;
  default: string;
};

export async function fetchReportPrompts(): Promise<ReportPrompt[]> {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/report-prompts`,
    { headers: { Authorization: `Bearer ${session?.access_token}` }, cache: "no-store" },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return (await res.json()).prompts as ReportPrompt[];
}
```

- [ ] **Step 2: Adicionar as mutações em `lib/config.ts`**

Ao final de `frontend/lib/config.ts` (usa `createClient` do client já importado no topo do arquivo):

```ts
export async function saveReportPrompt(section: string, prompt: string): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/report-prompts/${encodeURIComponent(section)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.access_token}` },
      body: JSON.stringify({ prompt }),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function resetReportPrompt(section: string): Promise<void> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/report-prompts/${encodeURIComponent(section)}`,
    { method: "DELETE", headers: { Authorization: `Bearer ${session?.access_token}` } },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
}

export async function previewSection(section: string, prompt: string): Promise<string> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_BACKEND_URL}/api/admin/preview-section`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.access_token}` },
      body: JSON.stringify({ section, prompt }),
    },
  );
  if (!res.ok) throw new Error(`backend ${res.status}`);
  return (await res.json()).text as string;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0 (sem erros). Se reclamar de `createClient` não importado em `lib/config.ts`, conferir o import existente no topo (já usado por `saveUserPrefs`).

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api.ts frontend/lib/config.ts
git commit -m "feat(painel): API client for report-prompts editor"
```

---

### Task 5: Aba "Relatório" — nav, página e editor

**Files:**
- Modify: `frontend/components/shell.tsx` (item de nav)
- Create: `frontend/app/relatorio/page.tsx`
- Create: `frontend/components/report-prompts-editor.tsx`

**Interfaces:**
- Consumes: `fetchReportPrompts`/`ReportPrompt` (`lib/api.ts`), `saveReportPrompt`/`resetReportPrompt`/`previewSection` (`lib/config.ts`), `Shell`, `PageHeader`.

- [ ] **Step 1: Adicionar o item de nav**

Em `frontend/components/shell.tsx`, no array `NAV`, inserir após a linha do `/agente`:

```ts
  { href: "/relatorio", label: "Relatório" },
```

(ordem final: Visão geral, Agente, Relatório, Notícias, Usuários.)

- [ ] **Step 2: Criar a página server `app/relatorio/page.tsx`**

```tsx
import Shell from "@/components/shell";
import { PageHeader } from "@/components/ui";
import { fetchReportPrompts, type ReportPrompt } from "@/lib/api";
import { ReportPromptsEditor } from "@/components/report-prompts-editor";

export default async function RelatorioPage() {
  let prompts: ReportPrompt[] = [];
  let err: string | null = null;
  try {
    prompts = await fetchReportPrompts();
  } catch (e) {
    err = e instanceof Error ? e.message : "erro desconhecido";
  }

  return (
    <Shell active="/relatorio">
      <main className="mx-auto max-w-3xl px-8 py-12">
        <PageHeader eyebrow="Editar" title="Relatório">
          Prompts das 6 seções do relatório diário. Salvar vale no próximo envio.
        </PageHeader>
        {err ? (
          <p className="text-sm text-muted-foreground">Não foi possível carregar os prompts: {err}</p>
        ) : (
          <ReportPromptsEditor initial={prompts} />
        )}
      </main>
    </Shell>
  );
}
```

- [ ] **Step 3: Criar o editor client `components/report-prompts-editor.tsx`**

```tsx
"use client";

import { useState } from "react";
import { saveReportPrompt, resetReportPrompt, previewSection } from "@/lib/config";
import type { ReportPrompt } from "@/lib/api";

const LABELS: Record<string, string> = {
  commodities: "Commodities",
  bolsas: "Bolsas",
  cambio_cripto: "Câmbio & Cripto",
  noticias: "Notícias",
  analise: "Análise",
  politica: "Política",
};

export function ReportPromptsEditor({ initial }: { initial: ReportPrompt[] }) {
  return (
    <div className="space-y-5">
      {initial.map((p) => (
        <PromptCard key={p.section} prompt={p} />
      ))}
    </div>
  );
}

function PromptCard({ prompt }: { prompt: ReportPrompt }) {
  const [text, setText] = useState(prompt.value);
  const [isCustom, setIsCustom] = useState(prompt.is_custom);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setStatus("Salvando…");
    try {
      await saveReportPrompt(prompt.section, text);
      setIsCustom(true);
      setStatus("Salvo. Vale no próximo relatório (até ~60s para propagar).");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (!window.confirm("Resetar para o prompt padrão? O texto customizado será perdido.")) return;
    setBusy(true);
    setStatus("Resetando…");
    try {
      await resetReportPrompt(prompt.section);
      setText(prompt.default);
      setIsCustom(false);
      setPreview(null);
      setStatus("Resetado para o padrão.");
    } catch (e) {
      setStatus("Erro: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setPreview(null);
    setStatus("Gerando teste (motor real, pode levar ~30s)…");
    try {
      const out = await previewSection(prompt.section, text);
      setPreview(out);
      setStatus(out ? null : "Motor não retornou texto.");
    } catch (e) {
      setStatus("Erro no teste: " + (e instanceof Error ? e.message : "desconhecido"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">
          {LABELS[prompt.section] ?? prompt.section}
        </h2>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            isCustom ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"
          }`}
        >
          {isCustom ? "customizado" : "padrão"}
        </span>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={10}
        className="block w-full rounded-md border border-border bg-input px-3 py-2 text-xs leading-relaxed text-foreground"
      />
      <p className="mt-1 text-right text-xs text-muted-foreground">{text.length} caracteres</p>

      {status && <p className="mt-1 text-sm text-primary">{status}</p>}

      <div className="mt-3 flex flex-wrap gap-3">
        <button
          onClick={save}
          disabled={busy}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          Salvar
        </button>
        <button
          onClick={reset}
          disabled={busy}
          className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          Resetar padrão
        </button>
        <button
          onClick={test}
          disabled={busy}
          className="rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          Testar
        </button>
      </div>

      {preview && (
        <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-background p-3 text-xs leading-relaxed text-foreground">
          {preview}
        </pre>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Typecheck + lint do build**

Run: `cd frontend && npx tsc --noEmit`
Expected: exit 0.

Run: `cd frontend && npx next build`
Expected: build conclui sem erro (a nova rota `/relatorio` aparece na lista). Se o lint reclamar de `window.confirm`, é aceitável; se reclamar de `confirm` global use `window.confirm` (já está usado).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/shell.tsx frontend/app/relatorio/page.tsx frontend/components/report-prompts-editor.tsx
git commit -m "feat(painel): Relatório tab to edit/reset/test the 6 report prompts"
```

---

## Verificação final (após todas as tasks)

- [ ] `python -m pytest -m unit -q` → todos verdes.
- [ ] `cd frontend && npx tsc --noEmit` → exit 0.
- [ ] Smoke manual (opcional, com o painel rodando): abrir "Relatório", editar um prompt, Salvar, Testar (gera a seção sem enviar), Resetar.
- [ ] Deploy: `git push origin master` (confirmar com o usuário antes; deploy de produção).
