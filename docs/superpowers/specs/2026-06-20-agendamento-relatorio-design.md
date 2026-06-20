# Agendamento Data-Driven do Relatório — Design

**Data:** 2026-06-20
**Escopo:** Item 2 da migração do motor de relatório (item 1 = motor, entregue). Este item entrega o **agendamento por usuário** (seção × dia × hora) + **cron Vercel confiável** que dispara o motor do item 1 + **grade de edição no painel**. Inclui também ligar o gatilho do **Check Alerts** no cron Vercel. Não desliga o n8n (isso é item 4).

## Contexto

O motor de relatório (item 1) já gera as 6 seções no backend (`report_engine.generate_sections`), validável via `preview-report`. Falta **quem dispara e quando**. Hoje:
- `user_preferences` tem **um** `report_time` ("HH:00") + `sections` (liga/desliga, chaves antigas do reporter). `get_users_for_hour` lê por hora.
- `vercel.json` tem `crons: []` — cron nativo desligado. O **n8n** é o despertador: dispara o relatório (workflow "Noticias finanças") e pinga `/api/check-alerts` a cada 15 min (a lógica de alertas já está 100% no backend; n8n só agenda).
- `/api/cron/report` existe mas está morto e chama o motor **antigo** (`reporter.generate_report`).

Plano da conta Vercel: **Pro** → cron nativo em qualquer frequência.

## Requisitos

- **Agendamento por usuário**, granularidade **hora cheia (BRT)**: cada usuário define, por seção, em quais **dias da semana** e **horas** recebe. Múltiplas horas/dia e horários diferentes por dia são suportados.
- **Cron nativo da Vercel** dispara o dispatcher de hora em hora; o dispatcher resolve o fuso BRT.
- **Flag de opt-in por usuário** (`use_new_report_engine`): o cron novo só envia pra quem está marcado. Permite rodar **em paralelo** ao n8n sem duplicar; cutover (marcar todos + desligar n8n) é o item 4.
- **Grade de edição no painel** (aba Usuários): tabela seção × dia, hora(s) por célula, + toggle do motor novo.
- **Check Alerts**: adicionar cron Vercel de 15 min apontando pro `/api/check-alerts` existente. Desligar o workflow no n8n é ação manual do usuário (não bloqueia este item).
- **Não tocar** `report_engine` (item 1), `reporter.generate_report` (chat) nem o webhook `main.py`. Não migrar `user_preferences.sections` (fica pro caminho n8n/chat).

## Constraints globais

- Python 3.12, FastAPI, deploy Vercel Pro (`vercel.json` legado, `maxDuration` 300s).
- Chaves de seção = chaves do **motor novo**: `commodities, bolsas, cambio_cripto, noticias, analise, politica`.
- `weekday`: int 0-6, seg=0 … dom=6 (convenção `datetime.weekday()`). `hour`: int 0-23, BRT.
- Auth admin: `auth.verify_supabase_jwt` (JWKS). Auth do cron: aceitar `Authorization: Bearer <CRON_SECRET>` (Vercel) **ou** `x-cron-secret` (n8n, transição).
- Sem mock de banco; monkeypatch de Supabase/Claude/WhatsApp nos testes unitários. Testes determinísticos marcados `unit` (entram no CI gate).

## Modelo de dados

### Tabela nova `report_schedules` (Supabase)

| Coluna | Tipo | Nota |
|--------|------|------|
| `phone` | text | número Evolution |
| `section` | text | chave do motor novo |
| `weekday` | int2 | 0-6 (seg=0) |
| `hour` | int2 | 0-23 (BRT) |

- PK composta `(phone, section, weekday, hour)` — evita duplicata.
- RLS habilitada, política `authenticated` (igual `agent_config`). O backend lê/escreve via service role (`SUPABASE_KEY`), bypassando RLS.
- Uma linha = "envia `section` pra `phone` em `weekday` às `hour`".

### Flag em `authorized_users`

- Coluna nova `use_new_report_engine` boolean, default `false`.
- O dispatcher só envia pra `phones` com `true`.

## Componentes

### `backend/services/schedules.py` (novo)

Acesso à `report_schedules` e à flag, via PostgREST (mesmo padrão de `supabase.py`, reusa `_client()` e `_f()`).

- `due_now(weekday: int, hour: int) -> list[dict]` — `GET /report_schedules?weekday=eq.W&hour=eq.H&select=phone,section`. Retorna linhas cruas.
- `get_for_phone(phone: str) -> list[dict]` — todas as linhas de um número (`select=section,weekday,hour`).
- `replace_for_phone(phone: str, rows: list[dict]) -> None` — apaga as linhas do phone e insere as novas (substituição atômica via DELETE + POST em lote).
- `set_engine_flag(phone: str, enabled: bool) -> None` — `PATCH /authorized_users?phone=eq.<phone>` setando `use_new_report_engine`.
- `phones_with_engine_enabled() -> set[str]` — `GET /authorized_users?use_new_report_engine=is.true&select=phone`.

### Dispatcher `/api/cron/report` (reescrito em `backend/api/cron_report.py`)

1. Valida segredo: aceita `Authorization: Bearer <CRON_SECRET>` ou header `x-cron-secret`. 401 se ausente/errado; 503 se `CRON_SECRET` não configurado.
2. `now_brt = datetime.now(BRT)`; `weekday = now_brt.weekday()`, `hour = now_brt.hour`.
3. `rows = schedules.due_now(weekday, hour)`; agrupa por `phone` → `{phone: [sections]}`.
4. `enabled = schedules.phones_with_engine_enabled()`; descarta phones fora do `enabled`.
5. Pra cada `phone` habilitado: monta `sections_dict = {s: True for s in sections_do_phone}`; `user = supabase.get_authorized_by_phone(phone)`; `messages = report_engine.generate_sections(sections_dict, user)`; envia cada uma via `whatsapp.send_message(phone, msg)`. `try/except` por usuário (loga, segue).
6. Retorna `{ "status": "ok", "weekday": W, "hour": H, "users": n, "sent": m, "failed": k }`.

### Auth do cron compartilhada

Helper `_check_cron_secret(request)` (em `cron_report.py`, reusado por `check_alerts.py`): lê `CRON_SECRET`, compara via `hmac.compare_digest` contra `Authorization: Bearer <x>` **ou** `x-cron-secret`. `check_alerts.py` passa a usar esse helper (mantém o `x-cron-secret` atual funcionando + aceita o Bearer da Vercel).

### `vercel.json`

```json
"crons": [
  { "path": "/api/cron/report",  "schedule": "0 * * * *" },
  { "path": "/api/check-alerts", "schedule": "*/15 * * * *" }
]
```

### Endpoints admin (`backend/api/admin.py`)

- `GET /api/admin/schedules/{phone}` → `{ "use_new_engine": bool, "schedule": { section: { weekday: [hours] } } }`. Monta a grade a partir das linhas de `schedules.get_for_phone` + lê a flag.
- `PUT /api/admin/schedules/{phone}` (body `{ use_new_engine: bool, schedule: {section: {weekday: [hours]}} }`) → expande a grade em linhas `(phone, section, weekday, hour)`, chama `schedules.replace_for_phone` + `schedules.set_engine_flag`. Retorna `{ "ok": true }`.

### Frontend (painel)

- `frontend/lib/config.ts`: `fetchSchedule(phone)` e `saveSchedule(phone, {use_new_engine, schedule})` (client-side, Bearer da sessão, padrão do `saveUserPrefs`).
- `frontend/components/users-manager.tsx`: no card do usuário, seção "Agendamento (motor novo)":
  - Toggle **Usar motor novo** (a flag).
  - **Tabela** seção × dia: 6 linhas (seções), 7 colunas (Seg–Dom). Cada célula é um input de texto que aceita horas separadas por vírgula (ex `7,12`); vazio = não envia. Botão Salvar grava via `saveSchedule`.
  - Parse do input: split por vírgula, trim, valida int 0-23, descarta inválidos/duplicados.

## Fluxo

```
Vercel Cron (0 * * * *)  → GET /api/cron/report (Bearer CRON_SECRET)
  → weekday/hour BRT
  → schedules.due_now → agrupa por phone → filtra flag
  → report_engine.generate_sections(sections, user)  [motor do item 1]
  → whatsapp.send_message (uma por seção)

Vercel Cron (*/15)       → GET /api/check-alerts (Bearer) → alert_checker.run_checks  [já existe]

Painel (Usuários) → PUT /api/admin/schedules/{phone} → report_schedules + flag
```

## Erros e limitações

- Cron: `try/except` por usuário (falha de um não derruba os outros); cada seção já é isolada no motor. Hora sem agendamento → no-op (`sent: 0`).
- Auth do cron inválida → 401; `CRON_SECRET` ausente → 503.
- **Limitação documentada:** geração é síncrona dentro da função (300s). Com muitos usuários na mesma hora (×6 seções), pode encostar no teto. Hoje ~4 usuários — folgado. Escala (batch/fila) é problema de outro item, fora de escopo.
- **Duplicata Check Alerts:** enquanto n8n e Vercel pingarem `/api/check-alerts` juntos, o dedup + cooldown do `alert_checker` evita alerta repetido (apenas processamento redundante). Aceitável até o usuário desligar o n8n.

## Testes (pytest, `-m unit`, no CI gate)

- **Dispatcher** (`test_cron_report.py`, reescrito): monkeypatch de `schedules.due_now`, `schedules.phones_with_engine_enabled`, `supabase.get_authorized_by_phone`, `report_engine.generate_sections`, `whatsapp.send_message`. Casos: agrupa seções por usuário; filtra quem não tem a flag; envia uma mensagem por seção retornada; isola falha de um usuário; hora vazia → `sent: 0`.
- **Auth do cron** (`test_cron_auth.py`): aceita `Authorization: Bearer <secret>`; aceita `x-cron-secret: <secret>`; 401 sem segredo; 503 sem `CRON_SECRET`. Cobre `/api/cron/report` e `/api/check-alerts`.
- **Endpoints de schedule** (`test_schedules_admin.py`): GET monta a grade a partir de linhas; PUT expande a grade em linhas e chama `replace_for_phone`/`set_engine_flag` (monkeypatch de `schedules`). Auth via `dependency_overrides`.
- **Parse da grade** (função pura): `"7,12"` → `[7, 12]`; descarta inválidos (`"25"`, `"x"`) e duplicados.
- **Frontend:** `npx tsc --noEmit` + `eslint` nos arquivos alterados (sem framework de teste no front, igual item 1).

## Fora de escopo

- Desligar workflows do n8n (item 4 — ação manual do usuário).
- Migrar `user_preferences.sections` antigo (fica pro caminho n8n/chat).
- Editar prompts/schedules globais no painel além da grade por usuário (item 3).
- Escala de geração em batch/fila (só se o nº de usuários crescer muito).
- Alterar `report_engine`, `reporter.generate_report` ou o webhook `main.py`.
