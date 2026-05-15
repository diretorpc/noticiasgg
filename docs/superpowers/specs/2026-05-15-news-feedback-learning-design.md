# Design: Aprendizado de Preferências de Notícias via Feedback

**Data:** 2026-05-15
**Branch:** feature/supabase-history
**Status:** Aprovado

---

## Contexto

O agente já salva o histórico de conversas no Supabase (`conversation_history`) e já envia relatórios financeiros com uma seção de notícias coletadas via NewsAPI. O problema: o agente não aprende quais notícias o usuário considera relevantes. Com 5 notícias por relatório, só 1 pode ser de real interesse — e esse sinal nunca é capturado.

## Objetivo

Quando o usuário dá feedback sobre quais notícias foram úteis ("só a notícia 1 foi importante"), o agente deve:
1. Detectar e armazenar esse feedback de forma estruturada (persistente, além do histórico de 10 mensagens)
2. Confirmar o recebimento e fazer uma pergunta de refinamento natural
3. Usar o histórico de feedbacks para priorizar temas relevantes em todos os relatórios futuros
4. Permitir reset das preferências via linguagem natural

---

## Arquitetura

### 1. Dados — Nova tabela `news_feedback`

```sql
CREATE TABLE public.news_feedback (
    id       bigint generated always as identity primary key,
    phone    text        not null,
    important_topics   jsonb not null default '[]'::jsonb,
    unimportant_topics jsonb not null default '[]'::jsonb,
    raw_feedback       text,
    created_at         timestamptz not null default now()
);
CREATE INDEX news_feedback_phone_idx ON public.news_feedback (phone);
```

- `important_topics`: lista de temas que o usuário considerou relevantes (ex: `["Fed", "juros americanos"]`)
- `unimportant_topics`: lista de temas desconsiderados (ex: `["política brasileira"]`)
- `raw_feedback`: mensagem original do usuário para auditoria
- Todos os feedbacks acumulam — sem expiração automática

Novas funções em `backend/services/supabase.py`:
- `save_news_feedback(phone, important, unimportant, raw)` — insere um registro
- `get_news_feedback(phone, limit=15)` — busca os mais recentes por `phone`
- `delete_news_feedback(phone)` — apaga todos os registros do usuário (para reset)

### 2. Detecção — `_detect_news_feedback()` em `main.py`

Nova função usando Claude Haiku (padrão já usado por `_detect_preference_intent`).

**Input:**
- `text`: mensagem do usuário
- `last_report`: último `content` com `role=assistant` no histórico (para o Haiku saber quais notícias foram enviadas e mapear "notícia 1" para o tema correto)

**System prompt `_NEWS_FEEDBACK_SYSTEM`** detecta dois intents:

```json
// Feedback de notícias
{
  "intent": "news_feedback",
  "important": ["Fed", "juros americanos"],
  "unimportant": ["política brasileira", "pesquisas eleitorais"]
}

// Reset de preferências
{ "intent": "news_reset" }

// Qualquer outra coisa
{ "intent": "message" }
```

**Regras de segurança:**
- Se `important` e `unimportant` estiverem ambos vazios mesmo com `intent: news_feedback` → trata como `message` (evita salvar registros vazios)
- Fallback em qualquer exceção: `{"intent": "message"}`

**Exemplos de frases que disparam detecção:**
- "só a notícia 1 foi relevante"
- "a notícia sobre o Fed foi ótima, o resto não me interessa"
- "me manda mais sobre SELIC, menos sobre eleições"
- "esquece o que eu disse sobre notícias" → `news_reset`
- "apaga minhas preferências de notícias" → `news_reset`

### 3. Fluxo do Webhook — `main.py`

Ordem de processamento (sem quebrar o fluxo atual):

```
1. fromMe? → ignora
2. Autorizado? → se não, cria pendência e notifica admin
3. Admin command? → processa e retorna
4. _detect_preference_intent() → se "preference", salva e retorna
5. get_history(limit=10) → busca histórico
6. _detect_news_feedback(text, last_report) ← NOVO
   ├── "news_feedback" → save_news_feedback() + resposta de confirmação → retorna
   ├── "news_reset"   → delete_news_feedback() + confirmação → retorna
   └── "message"      → continua
7. get_news_feedback(phone) → busca preferências acumuladas
8. save_message(phone, "user", text)
9. generate_report(..., news_feedback=feedback)
10. save_message(phone, "assistant", reply)
11. send_message(phone, reply)
```

**Resposta de confirmação de feedback** — não é texto fixo. O Claude gera a resposta com um prompt simples:

```
Tópicos importantes identificados: {important}
Tópicos irrelevantes identificados: {unimportant}

Confirme o recebimento de forma amigável (2-3 linhas, tom de WhatsApp)
e faça UMA pergunta de refinamento para entender melhor a preferência.
```

Isso permite que o agente pergunte, por exemplo: "Você prefere notícias sobre decisões do Fed ou também sobre os discursos dos membros do FOMC?"

**Resposta de reset** — texto fixo curto: "Preferências de notícias apagadas! Voltarei a enviar a curadoria padrão nos próximos relatórios."

### 4. Uso no Relatório — `reporter.py`

`generate_report` recebe novo parâmetro `news_feedback: list[dict] | None = None`.

Quando presente e não vazio, agrega os feedbacks e injeta ao final do system prompt:

```
PREFERÊNCIAS DE NOTÍCIAS DO USUÁRIO (baseado em feedbacks anteriores):
PRIORIZAR temas: Fed, juros americanos, SELIC
EVITAR ou desprioritizar: política brasileira, pesquisas eleitorais

Ao selecionar e destacar notícias no relatório, filtre de acordo com essas preferências.
```

- Tópicos são deduplicados antes de injetar (múltiplos feedbacks podem repetir o mesmo tema)
- A injeção só ocorre para `_SYSTEM_MARKET` (relatórios com dados) — não afeta `_SYSTEM_CHAT` (conversas casuais sem dados de mercado)

---

## Tratamento de Erros

- Falha no Haiku de detecção → `{"intent": "message"}` — seguro, fluxo normal
- Falha no `save_news_feedback` → logar e continuar (não bloquear a resposta)
- Falha no `get_news_feedback` → retornar lista vazia, relatório gerado sem preferências
- Reset quando não há feedback → confirmar mesmo assim ("Preferências já estavam vazias")

---

## Arquivos Modificados

| Arquivo | Tipo de mudança |
|---------|----------------|
| `backend/services/supabase.py` | +3 funções: `save_news_feedback`, `get_news_feedback`, `delete_news_feedback` |
| `backend/api/main.py` | +system prompt `_NEWS_FEEDBACK_SYSTEM`, +`_detect_news_feedback()`, webhook atualizado |
| `backend/services/reporter.py` | +parâmetro `news_feedback`, injeção no system prompt |
| `backend/api/cron_report.py` | passar `news_feedback=supabase.get_news_feedback(phone)` no loop do cron diário |
| Supabase (migration) | Nova tabela `news_feedback` + índice |

---

## Fora de Escopo

- Aprendizado de preferências para outras seções além de notícias (mercado, cripto, etc.)
- Pesos diferentes para feedbacks mais recentes (todos acumulam igualmente)
- Interface de visualização das preferências salvas
- Limite de feedbacks por usuário
