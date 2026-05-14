# Design Spec — Preferências de Relatório por Usuário

**Data:** 2026-05-14
**Status:** Aguardando revisão

---

## Visão Geral

Permitir que cada usuário do agente financeiro customize o relatório diário via WhatsApp em linguagem natural, sem comandos. As customizações incluem: quais seções receber e em qual horário. O agente também passa a endereçar cada pessoa pelo nome no relatório diário.

---

## Contexto e Restrições

- **n8n NÃO pode ter nodes modificados** — apenas o campo `url` dos nós "Enviar WhatsApp" será atualizado (de Evolution API direto → Vercel `/api/send-report`).
- **Stack:** Python 3.12 + FastAPI + Vercel Serverless + Supabase + Evolution API v1.8.2.
- **Usuários iniciais:** Matheus (5534999945010), Ricardim (5534999301855), Cassiano (5534996568291), Jorge (5534988162802).
- **Seções disponíveis:** market, crypto, indicators_us, indicators_br, news, commodities_br, politics_br, polls_br.
- **Fuso horário:** todos os horários de relatório são em BRT (UTC-3).

---

## Modelo de Dados

### Tabela `user_preferences` (nova no Supabase)

```sql
CREATE TABLE user_preferences (
  phone       TEXT PRIMARY KEY,
  sections    JSONB,        -- null = todas as seções (padrão)
  report_time TEXT,         -- ex: "08:00" BRT, null = horário padrão do n8n
  updated_at  TIMESTAMPTZ DEFAULT now()
);
```

**Exemplo de `sections`:**
```json
{
  "market": true,
  "crypto": true,
  "indicators_us": false,
  "indicators_br": true,
  "news": true,
  "commodities_br": false,
  "politics_br": false,
  "polls_br": false
}
```

`sections = null` → sem preferência → recebe tudo.
`report_time = null` → sem preferência → recebe no horário do n8n.
`report_time` aceita apenas horas cheias no formato `"HH:00"` (ex: `"08:00"`, `"19:00"`), pois o Vercel Cron dispara de hora em hora. Se o usuário pedir "8h e meia", arredondar para `"09:00"` e confirmar.

### Tabela `authorized_users` (já existe — sem alteração de schema)

Seed inicial via `scripts/seed_users.py` para inserir os 4 usuários com nome e número.

---

## Componentes

### 1. `POST /api/send-report` (novo endpoint)

Substitui o envio direto do n8n para a Evolution API. Recebe o payload já gerado pelo n8n e decide o que fazer.

**Payload recebido do n8n:**
```json
{
  "number": "5534999945010",
  "textMessage": { "text": "..." }
}
```

**Lógica:**
1. Busca preferências do usuário em `user_preferences` pelo `number`.
2. **Tem `report_time` customizado?** → pula o envio (Vercel Cron vai enviar no horário certo). Retorna `{"status": "skipped", "reason": "custom_time"}`.
3. **Tem `sections` customizadas?** → ignora o texto do n8n, re-coleta apenas as seções ativas, gera novo relatório via `reporter.generate_report()` com o nome do usuário, envia via `whatsapp.send_message()`.
4. **Sem preferências?** → envia o texto do n8n como está via `whatsapp.send_message()`. Busca o nome do usuário em `authorized_users` e faz um prepend simples (ex: `"Bom dia, Ricardim!\n\n" + text`).

### 2. `GET /api/cron/report` (novo endpoint)

Chamado pelo Vercel Cron todo hora. Envia relatórios para usuários com `report_time` customizado.

**Lógica:**
1. Calcula hora atual em BRT.
2. Busca no Supabase usuários com `report_time` igual à hora atual (formato `"HH:00"`).
3. Para cada usuário: coleta seções preferidas (ou todas se `sections = null`) → gera relatório com nome → envia via Evolution API.

**`vercel.json`:**
```json
"crons": [
  { "path": "/api/cron/report", "schedule": "0 * * * *" }
]
```

### 3. Detecção de preferência no webhook (`api/main.py`)

Antes de chamar `reporter.generate_report()`, um call leve ao Claude detecta se a mensagem é uma intenção de configuração.

**Exemplos de intenção:**
- "quero só notícias e crypto"
- "remove política do meu relatório"
- "pode me mandar às 8h da manhã"
- "volta pro padrão"
- "quero receber tudo de novo"

**Lógica:**
1. Claude recebe a mensagem e retorna JSON estruturado:
```json
{
  "intent": "preference",
  "changes": {
    "sections": {"news": true, "crypto": true, "market": false},
    "report_time": null
  }
}
```
ou `{"intent": "message"}` se não for configuração.

2. Se `intent = "preference"`: aplica `changes` nas preferências existentes (merge, não sobrescreve tudo), salva no Supabase, responde confirmando com o nome do usuário.
3. Se `intent = "message"`: segue fluxo normal.

**Merge de preferências:** ao dizer "remove política", apenas `politics_br` é desativado — o restante permanece como estava.

**"Volta pro padrão":** chama `save_preferences(phone, sections=None, report_time=None)` — apaga as preferências e o usuário volta a receber tudo no horário do n8n.

### 4. `reporter.py` — parâmetro `sections`

```python
def _collect_all(sections: dict | None = None) -> dict:
    all_collectors = {
        "market": market.collect,
        "crypto": crypto.collect,
        "indicators_us": indicators_us.collect,
        "indicators_br": indicators_br.collect,
        "news": news.collect,
        "commodities_br": commodities_br.collect,
        "politics_br": politics_br.collect,
        "polls_br": polls_br.collect,
    }
    active = sections or {k: True for k in all_collectors}
    return {
        k: _safe_collect(fn)
        for k, fn in all_collectors.items()
        if active.get(k, False)
    }
```

`generate_report()` passa `sections` para `_collect_all()`.

### 5. `supabase.py` — funções novas

```python
def get_preferences(phone: str) -> dict | None
def save_preferences(phone: str, sections: dict | None, report_time: str | None) -> None
def get_users_for_hour(hour_brt: str) -> list[dict]  # retorna usuários com report_time = hour_brt
```

### 6. `scripts/seed_users.py`

Script standalone que insere os 4 usuários na tabela `authorized_users` com upsert (não duplica se já existir).

```python
users = [
    {"phone": "5534999945010", "name": "Matheus",  "lid": "5534999945010"},
    {"phone": "5534999301855", "name": "Ricardim", "lid": "5534999301855"},
    {"phone": "5534996568291", "name": "Cassiano", "lid": "5534996568291"},
    {"phone": "5534988162802", "name": "Jorge",    "lid": "5534988162802"},
]
```

**Nota:** `lid` usa o próprio phone como placeholder para evitar conflito de unique constraint. Quando o usuário mandar a primeira mensagem pelo WhatsApp, o webhook fará upsert com o lid real via `add_authorized()`.

---

## Fluxo Completo

### Relatório diário — sem preferências
```
n8n (cron) → coleta + Claude → POST /api/send-report
  → sem preferências → prepend nome + envia texto n8n → Evolution API → WhatsApp
```

### Relatório diário — com seções customizadas
```
n8n (cron) → coleta + Claude → POST /api/send-report
  → tem sections → re-coleta filtrado + re-gera com Claude + nome → Evolution API → WhatsApp
```

### Relatório diário — com horário customizado
```
n8n (cron) → POST /api/send-report → tem report_time → pula

Vercel Cron (hora certa) → GET /api/cron/report
  → busca usuários do horário → coleta + gera com seções + nome → Evolution API → WhatsApp
```

### Usuário configura preferências
```
WhatsApp: "quero só notícias e crypto"
  → webhook → intent detection (Claude) → intent = "preference"
  → merge sections no Supabase → responde: "Feito, Ricardim! ..."
```

---

## Mudança no n8n

Em cada nó "Enviar WhatsApp" dos workflows, alterar manualmente o campo `url` de:
```
http://46.202.179.33:8080/message/sendText/noticiasgg
```
para:
```
https://noticiasgg.vercel.app/api/send-report
```

Workflows afetados: `Relatório 12h`, `Relatório 12h v2`, `Commodities`.

---

## O Que Não Muda

- Lógica de autorização de usuários (`/api/webhook`, `pending_auth`, `authorized_users`)
- Geração de relatório do n8n (Claude node do n8n continua rodando)
- Schedules do n8n (horários dos triggers permanecem)
- `services/whatsapp.py` (sem alteração)

---

## Fora de Escopo

- Sub-filtros dentro de uma seção (ex: só soja dentro de commodities) — pode ser adicionado futuramente
- Interface web para gerenciar preferências
- Múltiplos horários de relatório por usuário
