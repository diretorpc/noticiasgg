---
name: health-check
description: Use when verificando se o noticiasgg está saudável — após deploy, quando alertas ou relatórios pararam de chegar no WhatsApp, quando o usuário pergunta se "tá tudo rodando liso", ou ao suspeitar de falha silenciosa (cron retornando status error, Evolution desconectada, NewsAPI no limite)
---

# Health Check — noticiasgg

## Overview

Verificação completa do pipeline de alertas em produção: collectors → classificador → WhatsApp. O sistema falha em silêncio por design (endpoint retorna HTTP 200 com `{"status": "error"}`), então a única forma de garantir saúde é checar ativamente.

## Checks (executar todos, em paralelo quando possível)

### 1. Deploy atual
```bash
vercel ls --prod   # estado READY? qual commit?
git log --oneline -1 && git status --porcelain   # local == produção?
```
Compare o commit local com o deploy. Divergência OU working tree sujo = mudança não deployada (commit igual com arquivos modificados também conta).

### 2. Collector EIA (sem auth — valida key EIA em prod)
```bash
curl -s "https://noticiasgg.vercel.app/api/collectors/eia"
```
Esperado: 3 séries com `valor` numérico e `data` recente (≤ 14 dias — a EIA publica semanalmente com ~1 semana de lag). `erro` ou `valor: null` = problema na EIA_API_KEY ou na API.

### 3. Instância Evolution (WhatsApp conectado?)
```bash
curl -s "$EVOLUTION_API_URL/instance/connectionState/$EVOLUTION_INSTANCE" -H "apikey: $EVOLUTION_API_KEY"
```
Esperado: `"state": "open"`. Qualquer outro estado = WhatsApp desconectado, **alertas indo para o nada**. Valores no `.env` local.

### 4. Endpoint check-alerts (fluxo completo)
O `CRON_SECRET` de produção não é recuperável (sensitive na Vercel). Testar **localmente**:
```bash
uvicorn backend.api.main:app --port 8000 --env-file .env &
curl -s "http://127.0.0.1:8000/api/check-alerts?test=true" -H "x-cron-secret: test-local-secret"
```
⚠️ **`test=true` ENVIA mensagem real de teste para TODOS os recipients no WhatsApp.** Avisar o usuário antes de rodar; não repetir sem necessidade.

Esperado: `{"status": "ok", "recipients": 3, ...}` sem campo `errors`. Campo `errors` presente = listar e investigar cada um. `recipients: 0` = Supabase fora ou tabela vazia. **Matar o uvicorn depois.**

### 5. Suite de testes
```bash
python -m pytest backend/tests/ -q
```

### 6. Logs de produção
```bash
vercel logs https://noticiasgg.vercel.app 2>&1 | grep -iE "error|warning" | head -20
```
Atenção especial a: `admin notify`, `eia check skipped`, `news collection failed`, `send failed`.

## Formato do relatório

Tom direto, sem suavizar (padrão project-audit aprovado):

| Check | Status | Detalhe |
|-------|--------|---------|
| Deploy | ✅/❌ | commit + estado |
| EIA | ✅/❌ | data mais recente |
| Evolution | ✅/❌ | state |
| check-alerts | ✅/❌ | recipients, errors |
| Testes | ✅/❌ | N/N |
| Logs | ✅/⚠️ | erros encontrados |

**Veredito: SAUDÁVEL / DEGRADADO / QUEBRADO** + problemas priorizados por impacto, cada um com consequência real e fix sugerido.

## Gotchas conhecidos

- NewsAPI free tier: 100 requests/dia — estouro silencioso (news check retorna 0 e auto-alerta avisa o admin)
- `.env` local é sobrescrito por `vercel env pull` e keys sensitive voltam vazias — backup das keys fora do projeto
- Auto-alerta de falha (`notify_admin`) tem cooldown de 2h — ausência de aviso ≠ ausência de erro nas últimas 2h
- n8n: workflows são SOMENTE LEITURA via MCP (regra do CLAUDE.md)
