# Design — Link self-service por usuário (Trilho 2, opção B)

**Data:** 2026-06-22
**Status:** aprovado, pronto para plano

## Contexto

Hoje o painel é single-admin: login Supabase (email/senha) e qualquer usuário
autenticado é tratado como admin (`auth.verify_supabase_jwt` valida o JWT mas não
checa identidade). Os usuários do agente são linhas em `authorized_users` (por
telefone), separadas das contas de Auth. Só o Matheus loga no painel.

O objetivo do Trilho 2: deixar cada usuário editar **a própria** config (grade de
agendamento, seções do chat, áudio) sem depender do admin. Decidimos a **opção B
(leve)**: um link self-service por usuário, gerado pelo admin no painel e enviado
manualmente pelo WhatsApp, que abre uma página escopada `/me?token=…` sem login.
Auth multi-tenant completa (opção A) foi descartada por custo (YAGNI para 8
usuários; Supabase Auth não cobra, mas o custo é build+manutenção).

## Escopo

**Dentro:**
- Token opaco por usuário, **permanente + revogável**, armazenado em
  `authorized_users.selflink_token`.
- Admin gera/regenera/revoga o link no painel (por usuário).
- Página pública `/me?token=…` (sem login) que edita, **apenas do dono do token**:
  grade de agendamento, seções do chat, preferências de áudio.

**Fora (YAGNI / outros trilhos):**
- Flag `use_new_report_engine` — continua **admin-only** (quem entra no motor é
  decisão do admin).
- RSS/NewsAPI — config global, continua admin-only (aba Notícias).
- Fontes de notícia **por-usuário** — Trilho 3 futuro (mudança arquitetural grande).
- Mudar a auth do admin (segue email/senha Supabase).
- Login/contas Supabase para usuários comuns (essa é a opção A, descartada).

## Modelo do token

Como "permanente + revogável" já exige consulta ao banco para checar revogação,
HMAC com segredo não compensa (perde-se o statelessness). Usamos **token opaco**:

- Coluna nova `authorized_users.selflink_token TEXT` (nullable; null = sem link).
- **Gerar/regenerar:** grava `secrets.token_urlsafe(32)` (≈256 bits) na coluna.
  Regenerar sobrescreve → link anterior morre.
- **Revogar:** seta a coluna para null.
- **Verificar:** busca o usuário por `selflink_token = eq.<token>`; se achar,
  o telefone é resolvido; senão, 401.

Sem segredo novo em env, sem HMAC, revogação trivial.

## Arquitetura

### Backend

**`backend/services/supabase.py`:**
- `set_selflink_token(phone: str) -> str`: gera `secrets.token_urlsafe(32)`,
  faz PATCH em `authorized_users?phone=eq.<phone>` setando `selflink_token`,
  retorna o token.
- `clear_selflink_token(phone: str) -> None`: PATCH setando `selflink_token=null`.
- `get_by_selflink_token(token: str) -> dict | None`: GET
  `authorized_users?selflink_token=eq.<token>&select=*`; retorna a linha ou None.
  Trata token vazio/None retornando None sem consultar (evita casar com nulls).

**`backend/services/selflink.py`** (auth do token):
- `resolve_phone(token: str | None) -> str`: valida e retorna o telefone, ou
  levanta `HTTPException(401)`. Rejeita token ausente/vazio sem ir ao banco.
- `selflink_phone(token: str | None = Query(default=None)) -> str`: dependência
  FastAPI que extrai `?token=` e chama `resolve_phone`.

**`backend/api/admin.py`** (JWT admin):
- `POST /api/admin/selflink/{phone}` → valida `phone ∈ authorized_users`
  (`get_authorized_by_phone`), `set_selflink_token`, retorna
  `{"url": f"{PANEL_URL}/me?token=<token>", "token": <token>}`.
- `DELETE /api/admin/selflink/{phone}` → `clear_selflink_token`, `{"ok": True}`.
- `PANEL_URL` vem de env (`PANEL_BASE_URL`, default `https://noticiasgg.vercel.app`).

**`backend/api/me.py`** (novo router, auth por token via `selflink_phone`):
- `GET /api/me?token=…` → `{name, schedule, sections, audio}` onde:
  - `name` = `authorized_users.name`
  - `schedule` = `schedules.rows_to_grid(schedules.get_for_phone(phone))`
  - `sections` = `user_preferences.sections`
  - `audio` = `{audio_for_text, audio_for_media, tts_voice, tts_speed}`
- `PUT /api/me?token=…` body `{sections, audio_for_text, audio_for_media,
  tts_voice, tts_speed}` → lê `supabase.get_preferences(phone)` para pegar o
  `report_time` atual e o repassa em `supabase.save_preferences(...)` (preserva, não
  destrói). Retorna `{ok: True}`.
- `PUT /api/me/schedule?token=…` body `{schedule}` → `schedules.grid_to_rows` +
  `schedules.replace_for_phone`. **NÃO** chama `set_engine_flag` (flag é admin-only).
  Retorna `{ok: True}`.
- Registrar o router em `main.py` (`app.include_router(me.router)`).

**Isolamento:** todos os endpoints `/api/me*` derivam o telefone do token (nunca de
parâmetro do cliente). Impossível ler/editar outro telefone.

### Frontend

**`frontend/lib/selflink.ts`** (client): `fetchMe(token)`, `saveMePrefs(token, body)`,
`saveMeSchedule(token, schedule)` — todas batem em `/api/me*` com `?token=`,
**sem** header de auth Supabase.

**`frontend/lib/config.ts`** (admin, JWT): `generateSelflink(phone) -> {url}`,
`revokeSelflink(phone)`.

**`frontend/app/me/page.tsx`** (rota pública, sem `Shell`, sem login):
- Client component (precisa ler `?token=` e limpar a URL). Lê o token, chama
  `fetchMe`, renderiza `MeEditor`. Após carregar, `history.replaceState` remove o
  `?token=` da URL (reduz vazamento em histórico/referrer). Sem token ou inválido:
  mensagem "link inválido ou revogado".

**`frontend/components/me-editor.tsx`** (client): grade + seções + áudio + salvar,
escopado ao token. Reusa a grade extraindo `ScheduleGridEditor` de `users-manager`
para um componente compartilhado que recebe por prop: as funções `fetchSchedule`/
`saveSchedule` e um booleano `showEngineToggle` (true no admin, false no /me). No
/me o save da grade não envia o flag do motor.

**`frontend/components/users-manager.tsx`** (admin): no `UserForm`, botões
**"Gerar link"** (chama `generateSelflink`, mostra a URL para copiar) e
**"Revogar"** (chama `revokeSelflink`).

## Fluxo de dados

1. Admin abre Usuários → usuário X → **Gerar link** → copia a URL → manda no WhatsApp.
2. Usuário abre `/me?token=…` → `GET /api/me` resolve o telefone pelo token →
   renderiza grade/seções/áudio dele. URL é limpa do token após o load.
3. Usuário edita e salva → `PUT /api/me` / `PUT /api/me/schedule` (escopados pelo token).
4. Admin **Revoga** quando quiser → `selflink_token=null` → link velho retorna 401.

## Tratamento de erros

- Token ausente/inválido/revogado → 401 nos `/api/me*`; a página `/me` mostra
  "link inválido ou revogado, peça um novo".
- `phone` inexistente no gerar → 404.
- Falhas de save propagam mensagem legível; a UI não quebra.

## Segurança

- Token opaco aleatório de 256 bits (`secrets.token_urlsafe(32)`).
- Escopo rígido: telefone sempre derivado do token, nunca de input do cliente.
- URL limpa do token após o load (mitiga referrer/histórico).
- `/me` sem scripts de terceiros.
- Sem rate-limit (8 usuários; YAGNI). Documentado como aceito.
- Stakes baixos: o token só expõe/edita prefs de relatório de um telefone — não dá
  acesso a conversas, dados de outros usuários, nem à área admin.

## Banco

- Migration manual no Supabase (como as demais):
  `ALTER TABLE authorized_users ADD COLUMN selflink_token text;`
  Opcional: índice único parcial em `selflink_token WHERE selflink_token IS NOT NULL`.

## Env

- `PANEL_BASE_URL` (default `https://noticiasgg.vercel.app`) para montar a URL do link.
  Sem segredo novo (token é opaco no banco).

## Testes

- **Backend (pytest -m unit, monkeypatch na camada de serviço):**
  - `set_selflink_token`/`clear_selflink_token`/`get_by_selflink_token`: cobertos via
    os endpoints (wrappers PostgREST crus seguem o padrão sem teste unit dedicado).
  - `selflink.resolve_phone`: token válido → telefone; ausente/None → 401; token
    desconhecido → 401.
  - `GET /api/me`: monta `{name, schedule, sections, audio}` do telefone do token;
    token inválido → 401; nunca retorna outro telefone.
  - `PUT /api/me`: chama `save_preferences` preservando `report_time`.
  - `PUT /api/me/schedule`: chama `replace_for_phone` e **não** chama `set_engine_flag`.
  - Admin `POST/DELETE /api/admin/selflink/{phone}`: gera/limpa token; 404 em phone
    inexistente.
- **Frontend:** `tsc --noEmit` limpo.

## Critérios de aceite

- Admin gera um link no painel e o copia.
- Abrir `/me?token=…` mostra só a config do dono do token; token some da URL.
- Usuário edita grade/seções/áudio e salva; mudanças persistem (e o flag do motor
  não muda).
- Admin revoga → o link antigo para de funcionar (401 / "link inválido").
- Token de um usuário nunca acessa dados de outro.
- `pytest -m unit` e `tsc --noEmit` verdes.
