# Painel de Configuração Admin — Design

**Data:** 2026-06-15
**Status:** Aprovado para planejamento
**Escopo:** Fases 0 + 1 + 2

## Problema

Hoje boa parte da configuração do agente vive hardcoded em Python. Para mudar
fontes de notícia, queries de busca, voz da TTS ou tamanho de resposta é preciso
editar código e fazer deploy. O dono do projeto quer um painel web onde ele
(e 1-2 pessoas de confiança) consigam ver e controlar o máximo possível de
configurações sem depender de alteração de código.

## Princípio de risco

O system prompt contém as regras de **integridade factual** que impedem o agente
de alucinar preços, empresas e relações causais. Editar isso errado degrada o
agente silenciosamente — o erro só aparece quando ele manda besteira no WhatsApp.

Decisão: **o núcleo de comportamento (prompts, tools, modelo, timeouts) é
read-only no painel.** Apenas configs operacionais seguras são editáveis.

## O que é editável vs read-only

| Área | No painel | Editável? | Fonte hoje |
|------|-----------|-----------|------------|
| Prompts do agente (integridade factual) | ✅ visível | 🔒 read-only | `reporter.py` |
| Tools, modelo Claude, timeouts, max tool rounds, validador | ✅ visível | 🔒 read-only | `reporter.py` |
| Áudio: voz TTS, velocidade, toggles de áudio | ✅ | ✏️ editável | `media.py` + `user_preferences` |
| Texto: max_tokens da resposta, profundidade do histórico | ✅ | ✏️ editável | `reporter.py` / `supabase.py` |
| Fontes NewsAPI, feeds RSS, sites de busca | ✅ | ✏️ editável | `news.py` |
| Filtros de notícia (temas/keywords) | ✅ | ✏️ editável | `news.py` |
| Relatório: seções + horário | ✅ | ✏️ editável | `user_preferences` |
| Configurações gerais (toggles/limites seguros) | ✅ | ✏️ editável | diversos |

## Arquitetura

Dois canais, um por tipo de config:

```
Painel (Next.js, frontend/)
  ├── config editável  ──► Supabase (Auth + RLS) ◄── backend lê (config.py, cache+fallback)
  └── config do agente ──► GET /api/admin/agent-config (Python, read-only, sem secrets)
```

- **Config editável:** o painel lê/escreve direto no Supabase com Auth + RLS.
  Evita criar CRUD no FastAPI. O backend Python lê as mesmas tabelas.
- **Config read-only do agente:** vive no código Python. Um endpoint
  `GET /api/admin/agent-config` serializa prompts, tools, modelo e timeouts para
  exibição. **Nunca expõe secrets** (chaves de API ficam fora do payload).
- **Deploy isolado:** o painel é um projeto Vercel separado do backend. Se o
  build do painel quebrar, o agente em produção continua rodando.

### Serviço de config no backend (`backend/services/config.py`)

- Busca todas as linhas de `agent_config` do Supabase e cacheia em memória com
  TTL ~60s.
- API: `get(key, default)` → valor do Supabase, ou `default` se o banco falhar
  ou o dado vier malformado.
- As constantes hardcoded de hoje (`SOURCES_FINANCE`, `_FINANCE_QUERY`, voz/
  velocidade da TTS, `max_tokens`, etc.) viram os **defaults** passados em `get`.
  Fallback é automático: **o agente nunca quebra por causa de config ruim.**

### Resolução de configs por-usuário (áudio/texto)

Ordem de precedência:

```
valor do usuário (user_preferences) → padrão global (agent_config) → default hardcoded
```

`config.py` expõe `get_conversation_setting(phone, key, default)` que aplica essa
cascata. Os pontos de integração que passam a usá-la: `reporter.py` (max_tokens,
profundidade do histórico), `media.py` (voz, velocidade) e o fluxo de webhook em
`main.py` (toggles de áudio).

## Modelo de dados

### Tabela nova: `agent_config` (Supabase)

Chave/JSON, flexível para não exigir migração de schema a cada config nova.

| coluna | tipo | exemplo |
|--------|------|---------|
| `key` | text (PK) | `news.sources_finance`, `news.rss_feeds`, `conversation.tts_voice` |
| `value` | jsonb | `["reuters","cnbc"]` / `"nova"` / `0.85` |
| `updated_at` | timestamptz | — |
| `updated_by` | text | email do admin |

Chaves previstas:
- `news.sources_finance`, `news.sources_tech` — listas de IDs NewsAPI
- `news.rss_feeds`, `news.rss_feeds_ai` — listas de `{nome, url}`
- `news.finance_query`, `news.ai_query` — strings de query
- `news.search_sites` — sites permitidos na busca
- `conversation.tts_voice`, `conversation.tts_speed`
- `conversation.audio_for_text`, `conversation.audio_for_media`
- `conversation.max_tokens`, `conversation.history_depth`
- `general.*` — toggles/limites gerais (definidos na Fase 2)

### Tabela existente: `user_preferences`

Já guarda overrides por-usuário (`sections`, `report_time`, `audio_for_text`,
`audio_for_media`, `tts_voice`, `tts_speed`). Reaproveitada para os overrides
por-usuário das configs de conversação. A Fase 2 expõe a edição dela no painel.

## Páginas do painel

- `/login` — Supabase Auth (signup fechado; usuários criados por convite manual)
- `/` — visão geral (status do sistema, atalhos)
- `/agente` — áudio + texto editáveis (padrão global); prompts/tools/modelo/
  timeouts read-only (Fase 0 read-only; edição de conversação na Fase 2)
- `/noticias/fontes` — fontes NewsAPI, feeds RSS, sites de busca (Fase 1)
- `/noticias/filtros` — temas/keywords (Fase 2)
- `/relatorio` — seções + horário, incl. override por-usuário (Fase 2)
- `/config` — configurações gerais (Fase 2)

## Fluxo de dados

1. Admin faz login (Supabase Auth) → sessão.
2. Config editável: painel → Supabase (RLS) → renderiza formulários.
3. Config do agente: painel → `GET /api/admin/agent-config` → renderiza read-only.
4. Admin edita → escreve em `agent_config` (ou `user_preferences` para override).
5. Próxima execução do collector/reporter: `config.py` busca valor fresco (cache
   expirado) e usa; se o Supabase cair → default hardcoded.

## Segurança

- **RLS em `agent_config`:** apenas usuário autenticado lê/escreve. Sem isso,
  qualquer um muda as fontes do agente.
- **`/api/admin/agent-config` exige auth** e filtra secrets (nenhuma chave de API
  no payload).
- **Signup fechado:** usuários criados manualmente no Supabase Auth.

## Tratamento de erros e validação

- **Fallback:** falha de leitura de config → default hardcoded. Logar o evento.
- **Cache TTL ~60s:** edições propagam em até ~1 min.
- **Validação no painel:** formato de URL de RSS, IDs de fonte NewsAPI válidos,
  velocidade dentro de 0.25–4.0, voz dentro da lista OpenAI, antes de gravar.
- **Validação defensiva no backend:** na leitura, ignora entradas malformadas e
  cai no default em vez de quebrar a coleta.

## Testes

- **Backend (foco):**
  - `config.py`: cache, fallback com Supabase fora do ar, dado malformado,
    cascata de resolução por-usuário.
  - `news.py`: lê config do banco com fallback para os defaults.
  - Os 116 testes atuais continuam verdes.
- **Frontend:** testes leves (YAGNI) — validação de formulário onde houver risco.

## Faseamento

- **Fase 0 — Espelho read-only + esqueleto:** Next.js + Supabase Auth + `/agente`
  read-only exibindo prompts/tools/modelo/timeouts e config atual. Risco zero.
- **Fase 1 — Fontes e sites editáveis:** `agent_config` + `config.py` + refatorar
  `news.py`. Edição de fontes NewsAPI, RSS e sites de busca. Mata a dor principal.
- **Fase 2 — Conversação, filtros, relatório e gerais editáveis:** edição de
  áudio/texto (global + override por-usuário), temas/keywords, seções/horário,
  configs gerais.

## Fora de escopo

- Edição livre do system prompt (núcleo de integridade factual permanece read-only).
- Fase 3 (tuning estruturado do agente) — spec próprio no futuro, se desejado.
- Adoção de framework de agente (Agno/etc.) — avaliado e descartado nesta etapa.
