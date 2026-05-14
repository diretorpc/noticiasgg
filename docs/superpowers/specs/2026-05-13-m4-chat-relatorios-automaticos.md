# M4 — Chat Conversacional + Relatórios Automáticos

**Data:** 2026-05-13  
**Status:** Aprovado para implementação

---

## Visão Geral

Expandir o agente financeiro para:
1. **Relatórios automáticos** por categoria em horários fixos — sem o usuário precisar pedir
2. **Chat conversacional com memória** — o agente decide o que coletar baseado na pergunta e lembra do contexto da conversa (histórico persistido no Supabase)
3. **Notícias priorizadas por impacto real** — o Claude filtra pelo potencial de impacto no cenário global, não por popularidade

---

## Parte 1 — Relatórios Automáticos

### Agenda de Envios

| Categoria | Frequência | Horário (Brasília) | Mensagem |
|-----------|-----------|-------------------|---------|
| Bolsas | Diário | 7h | Separada |
| Notícias | Diário | 7h + 12h | Separada |
| Análise do Cenário | Diário | 7h + 12h | Separada |
| Câmbio + Cripto | Diário | 12h | Separada |
| Commodities | Semanal | Segunda, 7h | Separada |

### Workflows n8n (Schedule Trigger)

**Workflow 7h — diário:**
```
Schedule Trigger (7h todo dia)
  → [Paralelo] GET /api/collectors/market (só bolsas)
  → [Paralelo] GET /api/collectors/news
  → Claude: gera mensagem de BOLSAS → envia WhatsApp
  → Claude: gera mensagem de NOTÍCIAS → envia WhatsApp
  → Claude: gera ANÁLISE DO CENÁRIO → envia WhatsApp
```

**Workflow 12h — diário:**
```
Schedule Trigger (12h todo dia)
  → [Paralelo] GET /api/collectors/market (só câmbio)
  → [Paralelo] GET /api/collectors/crypto
  → [Paralelo] GET /api/collectors/news
  → Claude: gera mensagem de CÂMBIO + CRIPTO → envia WhatsApp
  → Claude: gera mensagem de NOTÍCIAS → envia WhatsApp
  → Claude: gera ANÁLISE DO CENÁRIO → envia WhatsApp
```

**Workflow segunda 7h — semanal:**
```
Schedule Trigger (7h toda segunda)
  → GET /api/collectors/commodities-br
  → Claude: gera mensagem de COMMODITIES → envia WhatsApp
```

### Número de destino
- `5534999945010` (Matheus) — hardcoded nos workflows de schedule (não vem do webhook)

---

## Parte 2 — Chat Conversacional com Memória

### Fluxo do Webhook (mensagem recebida)

```
Webhook (Evolution API)
  → IF fromMe = false (ignora mensagens próprias)
  → Carregar histórico do Supabase (últimas 20 mensagens do número)
  → Claude analisa a mensagem e decide:
      - "relatório", "resumo", "mercado hoje" → coleta TUDO + relatório completo
      - "bolsa", "ibovespa", "s&p" → coleta só market
      - "soja", "boi", "commodity" → coleta só commodities-br
      - "dólar", "câmbio", "euro" → coleta só market (câmbio)
      - "bitcoin", "cripto", "eth" → coleta só crypto
      - "notícia", "news", "o que aconteceu" → coleta só news
      - "selic", "ipca", "juros" → coleta só indicators-br
      - Pergunta geral → responde direto sem coletar nada
  → Salvar mensagem + resposta no Supabase
  → Enviar resposta via Evolution API
```

### Memória no Supabase

**Tabela: `conversation_history`**

```sql
CREATE TABLE conversation_history (
  id          BIGSERIAL PRIMARY KEY,
  phone       TEXT NOT NULL,           -- ex: "5534999945010"
  role        TEXT NOT NULL,           -- "user" ou "assistant"
  content     TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_conversation_phone_created 
  ON conversation_history (phone, created_at DESC);
```

- Carregar: últimas 20 mensagens do número (10 pares user/assistant)
- Salvar: sempre após responder
- Comando `limpar histórico` → deleta todas as linhas do número

---

## Parte 3 — Notícias por Impacto Real

### Critério de priorização

O Claude deve selecionar as 5 notícias que mais se encaixam em:
- **Impacto geopolítico:** guerras, eleições, assassinatos de líderes, sanções, acordos internacionais
- **Impacto de política monetária:** decisões do Fed, Banco Central, FMI, Banco Mundial
- **Impacto financeiro direto:** falências, fusões bilionárias, reembolsos, multas, colapsos
- **Impacto em commodities:** safras, embargos, desastres naturais que afetam produção
- **Impacto regulatório:** decisões de Suprema Corte, novas leis, regulações de mercado

**NÃO priorizar:** notícias virais sem impacto real, previsões vagas, opiniões sem fato concreto

### Atualização no system prompt

Adicionar no bloco de NOTÍCIAS:
> "Selecione as 5 notícias de MAIOR IMPACTO REAL no cenário global — priorize eventos que mudaram ou podem mudar o comportamento de mercados, políticas econômicas, relações geopolíticas ou fluxo de capital. Ignore notícias barulhentas sem consequência concreta."

---

## Implementação — Ordem

1. Criar tabela `conversation_history` no Supabase
2. Atualizar system prompt (critério de notícias)
3. Criar Workflow 7h no n8n (Schedule Trigger)
4. Criar Workflow 12h no n8n (Schedule Trigger)
5. Criar Workflow segunda 7h no n8n (Schedule Trigger)
6. Atualizar Workflow de chat (webhook) para carregar/salvar histórico no Supabase
