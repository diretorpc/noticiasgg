# Design — Edição dos prompts do relatório no painel (item 3 da migração)

**Data:** 2026-06-21
**Status:** aprovado, pronto para plano

## Contexto

Os prompts das 6 seções do relatório diário (motor novo, `report_engine.py`) já são
data-driven: `report_prompts.get_prompt(section)` lê a chave `report_prompt_<section>`
da tabela `agent_config` (via `config.get_str`, cache TTL 60s) e cai no default
hardcoded em `report_prompts.DEFAULTS` quando não há override.

Hoje **não existe tela nem endpoint de escrita** para esses prompts — só
`get_agent_config` (snapshot read-only). Editar um prompt exige mudar o código e
fazer deploy. Este é o item 3 da migração n8n→backend: dar ao admin uma tela para
editar os 6 prompts pelo painel.

Itens 1, 2 e 4 (motor, agendamento+cron, cutover) já estão em produção.

## Escopo

**Dentro:**
- Editar os 6 prompts de seção: `commodities`, `bolsas`, `cambio_cripto`,
  `noticias`, `analise`, `politica`.
- Por prompt: editar/salvar, resetar para o default, indicador default vs
  customizado, contador de caracteres, testar (preview sem enviar).
- Nova aba "Relatório" no painel.
- Admin-only (mesma auth `verify_supabase_jwt` das outras telas).

**Fora (YAGNI / outros trilhos):**
- "Config global" (modelo Claude, toggles de coleta, saudação, limites de char).
- Edição por usuário não-admin (Trilho 2 — self-service).
- Limpeza do `report_time` no webhook (`main.py`).

## Arquitetura

### Backend

**`backend/services/supabase.py`** — camada de escrita no `agent_config`:
- `upsert_config(key: str, value) -> None`: POST em `/agent_config` com
  `Prefer: resolution=merge-duplicates` (upsert por `key`). Segue o padrão dos
  outros upserts do módulo.
- `delete_config(key: str) -> None`: DELETE em `/agent_config?key=eq.{key}`.

**`backend/services/report_engine.py`** — suportar prompt override no preview:
- `_render(section, ctx, client, prompt=None)`: `prompt = prompt or report_prompts.get_prompt(section)`.
  Comportamento atual inalterado quando `prompt` é None.
- `preview_section(section: str, prompt: str | None, client=None) -> str`:
  monta o client (igual a `generate_sections`), `ctx = _collect(section)`,
  retorna `_render(section, ctx, client, prompt)`. Reusa `_collect` e a validação
  `integrity` das seções de texto. Sem saudação, sem envio.

**`backend/api/admin.py`** — endpoints (todos `Depends(auth.verify_supabase_jwt)`):
- `GET /api/admin/report-prompts` → `{prompts: [{section, value, is_custom, default}]}`
  para cada seção em `report_prompts.SECTIONS`, onde:
  - `value` = prompt efetivo (override salvo ou default)
  - `is_custom` = existe override salvo para a chave
  - `default` = `report_prompts.DEFAULTS[section]`
  - (o contador de caracteres é puramente do tamanho do textarea no frontend — não
    precisa de campo no backend)
- `PUT /api/admin/report-prompts/{section}` body `{prompt: str}` →
  valida `section ∈ SECTIONS`, `supabase.upsert_config("report_prompt_"+section, prompt)`,
  `config.clear_cache()`, retorna `{ok: True, is_custom: True}`.
- `DELETE /api/admin/report-prompts/{section}` →
  `supabase.delete_config("report_prompt_"+section)`, `config.clear_cache()`,
  retorna `{ok: True, is_custom: False}`.
- `POST /api/admin/preview-section` body `{section: str, prompt: str}` →
  valida `section`, `report_engine.preview_section(section, prompt)`, retorna `{text}`.

A construção da chave (`report_prompt_<section>`) reusa `report_prompts._CONFIG_KEY`
em vez de concatenar à mão, para uma fonte única da verdade.

### Frontend

**`frontend/components/shell.tsx`** — adicionar `{ href: "/relatorio", label: "Relatório" }`
ao `NAV` (entre "Agente" e "Notícias").

**`frontend/app/relatorio/page.tsx`** (server component) — `Shell active="/relatorio"`,
`PageHeader`, busca inicial dos prompts e renderiza o editor client. Degrada para
mensagem de erro se o backend falhar (padrão das outras telas).

**`frontend/components/report-prompts-editor.tsx`** (client) — 6 cards, um por seção:
- `<textarea>` com o valor efetivo
- contador de caracteres (do texto atual)
- badge "padrão" / "customizado" (de `is_custom`, atualiza após salvar/resetar)
- botões: **Salvar** (PUT), **Resetar** (DELETE, com confirmação), **Testar** (POST
  preview-section com o texto atual do textarea → exibe a saída gerada abaixo do card)
- estado de status/erro por card

**`frontend/lib/config.ts`** — `fetchReportPrompts()`, `saveReportPrompt(section, prompt)`,
`resetReportPrompt(section)`, `previewSection(section, prompt)`. Mesmo padrão de auth
(`session.access_token`) e `NEXT_PUBLIC_BACKEND_URL` das funções existentes.

## Fluxo de dados

1. **Carregar:** `page.tsx` → `GET report-prompts` → renderiza 6 textareas com
   `value` + `is_custom`.
2. **Salvar:** Salvar → `PUT` → upsert + clear cache → vale no próximo relatório
   (sujeito ao caveat de cache abaixo). Badge vira "customizado".
3. **Resetar:** Resetar → `DELETE` → remove override → textarea recarrega com o
   default; badge vira "padrão".
4. **Testar:** Testar → `POST preview-section` com o texto atual (não-salvo) →
   exibe o texto gerado. Não envia ao WhatsApp.

## Tratamento de erros

- Endpoints validam `section` contra `SECTIONS` → 4xx em seção inválida.
- Preview/geração pode falhar (timeout Anthropic, coletor caindo): o endpoint
  propaga erro legível; a UI mostra "Erro no teste: …" sem quebrar a tela.
- `config.get_all_config`/leitura já degradam para default no backend.

## Caveat de cache (documentado, não resolvido)

`config._load` tem cache TTL 60s **por instância de processo**. Em serverless
(Vercel, Fluid Compute) há múltiplas instâncias; `config.clear_cache()` no PUT/DELETE
limpa apenas a instância que atendeu a requisição. Outras instâncias quentes podem
servir o prompt antigo por **até 60s**. Aceitável para config de admin de baixa
frequência. Não vamos adicionar invalidação distribuída (YAGNI).

## Testes

- **Backend (pytest -m unit, mock supabase):**
  - `upsert_config`/`delete_config` chamam o endpoint PostgREST certo.
  - `GET report-prompts`: `is_custom` true quando há override, false no default;
    `value` reflete override ou default.
  - `PUT`/`DELETE`: chamam upsert/delete + `clear_cache`.
  - `preview_section`: usa o prompt passado (override) e não o salvo; mock do client
    Anthropic.
  - validação de seção inválida.
- **Frontend:** `tsc --noEmit` limpo. Sem envio real no preview.

## Critérios de aceite

- Admin abre "Relatório", vê os 6 prompts com badge correto.
- Edita e salva um prompt → próximo relatório/preview usa o novo texto.
- Reseta → volta ao default hardcoded.
- "Testar" gera a seção com o texto não-salvo, sem enviar ao WhatsApp.
- `pytest -m unit` e `tsc --noEmit` verdes.
