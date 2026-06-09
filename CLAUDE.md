# CLAUDE.md — Agente Notícias Finanças

## Visão Geral

Agente de IA especialista em finanças que coleta dados de mercado, notícias e indicadores econômicos diariamente e envia um resumo formatado ao usuário via WhatsApp. O usuário pode também conversar com o agente diretamente pelo WhatsApp.

PRD completo: [docs/PRD.md](docs/PRD.md)
Spec de design: [docs/superpowers/specs/2026-05-11-agente-financeiro-whatsapp-design.md](docs/superpowers/specs/2026-05-11-agente-financeiro-whatsapp-design.md)
Plano de implementação: [docs/superpowers/plans/2026-05-11-agente-financeiro-whatsapp.md](docs/superpowers/plans/2026-05-11-agente-financeiro-whatsapp.md)

URL produção: https://noticiasgg.vercel.app
WhatsApp do agente: +55 34 99659-2975

---

## Stack

| Camada | Tecnologia |
|--------|-----------|
| Backend principal | Python 3.12, FastAPI |
| IA | Claude API (`claude-sonnet-4-6`) via `anthropic` SDK |
| Dados de mercado | Yahoo Finance (HTTP direto) |
| Cripto | CoinGecko API (sem chave) |
| Indicadores EUA | FRED API (`FRED_API_KEY`) |
| Indicadores BR | BCB (Banco Central, sem chave) |
| Notícias | NewsAPI (`NEWS_API_KEY`) |
| Mensageria | Evolution API v1.8.2 (WhatsApp, self-hosted na VPS Hostinger) |
| Banco de dados | Supabase (histórico de mensagens) |
| Frontend | Next.js, React, Tailwind CSS, TypeScript (planejado) |
| Automação | n8n (workflows configurados — NÃO MEXER) |
| Deploy | Vercel Serverless Functions |

---

## Estrutura de Pastas

```
c:\noticiasgg\
├── backend/
│   ├── api/
│   │   └── main.py             # FastAPI + endpoint /api/webhook
│   ├── collectors/
│   │   ├── market.py           # Bolsas, câmbio (Yahoo Finance)
│   │   ├── crypto.py           # Criptomoedas (CoinGecko)
│   │   ├── indicators_us.py    # CPI, PPI, desemprego (FRED)
│   │   ├── indicators_br.py    # SELIC, IPCA (BCB)
│   │   ├── news.py             # Notícias (NewsAPI)
│   │   ├── commodities_br.py   # Commodities BR
│   │   ├── politics_br.py      # Política BR
│   │   └── polls_br.py         # Pesquisas eleitorais
│   ├── services/
│   │   ├── reporter.py         # Geração de relatório via Claude
│   │   └── whatsapp.py         # Envio via Evolution API
│   ├── tests/                  # pytest
│   └── requirements.txt
├── docs/
│   ├── PRD.md
│   └── superpowers/
├── vps/                        # Scripts da VPS
├── vercel.json
└── CLAUDE.md
```

---

## Variáveis de Ambiente (Vercel)

| Variável | Descrição |
|----------|-----------|
| `ANTHROPIC_API_KEY` | Chave da API Claude |
| `FRED_API_KEY` | Chave da API FRED |
| `EIA_API_KEY` | Chave da API EIA (estoques semanais petróleo/gasolina/gás EUA) |
| `NEWS_API_KEY` | Chave da NewsAPI |
| `SCRAPER_API_KEY` | Chave do ScraperAPI |
| `EVOLUTION_API_URL` | `http://46.202.179.33:8080` |
| `EVOLUTION_API_KEY` | `noticiasgg2026` |
| `EVOLUTION_INSTANCE` | `noticiasgg` |
| `AUTHORIZED_NUMBER` | Número WhatsApp autorizado (formato Evolution: `553496592975`) |
| `REPLY_TO_NUMBER` | Fallback de destino quando o `remoteJid` é LID (`5534999945010`) |
| `SUPABASE_URL` | URL do projeto Supabase (histórico) |
| `SUPABASE_KEY` | Service role key do Supabase |

---

## Convenções

- **Python:** snake_case para funções e variáveis, PascalCase para classes.
- **TypeScript/Next.js:** camelCase para variáveis/funções, PascalCase para componentes React.
- **Commits:** mensagens em inglês, imperativas.
- **Sem comentários desnecessários** — apenas quando o "porquê" não é óbvio.
- **Sem mock de banco em testes** — testes de integração usam APIs reais onde possível.
- **YAGNI** — sem features fora do escopo.
- **n8n:** PROIBIDO usar qualquer ferramenta MCP do n8n (`mcp__n8n-mcp__update_workflow`, `mcp__n8n-mcp__create_workflow_from_code`, etc.) para modificar workflows existentes. Em mai/2026 um subagente usou `update_workflow` para corrigir um system prompt, não leu o arquivo inteiro, alucionou números de telefone e enviou mensagens para estranhos. Apenas leitura (`search_workflows`, `get_workflow_details`) é permitida.

---

## Fluxo Principal

```
WhatsApp (usuário)
  → Evolution API webhook (POST /webhook/set/noticiasgg)
    → backend/api/main.py:/api/webhook
      → collectors/* (dados via _safe_collect — tolerante a falhas)
      → services/reporter.py (Claude gera resumo)
      → services/whatsapp.py (envia resposta)
  → WhatsApp (usuário recebe relatório)
```

**Nota sobre LID**: Mensagens recebidas vêm com `remoteJid` no formato `<id>@lid` (Linked Identifier do WhatsApp moderno). Para responder, mapeamos LID → número via `/chat/findContacts` da Evolution API (com fallback `REPLY_TO_NUMBER`).

---

## Estado Atual (2026-05-14)

| Task | Status |
|------|--------|
| Estrutura do projeto | ✅ |
| Collectors (market, crypto, FRED, BCB, news, commodities, politics, polls) | ✅ |
| `services/reporter.py` (Claude) | ✅ |
| `services/whatsapp.py` (Evolution) | ✅ |
| `api/main.py` webhook | ✅ |
| Conectar WhatsApp via QR code | ✅ |
| Deploy na Vercel | ✅ |
| Webhook Evolution → Vercel funcionando end-to-end | ✅ |
| Suporte a múltiplos números (LID resolver) | ⏳ |
| Integração Supabase (histórico) | ⏳ |
| Frontend Next.js | ⏳ |

---

## Squad Studio

Squad de IA disponível neste projeto. Invocação por prefixo: `Zeus:`, `Atlas:`, `Hermes:`, `Atena:`, `Apolo:`.

**Notas de contexto para este projeto:**
- **Atlas** — Python 3.12 + FastAPI é a linguagem primária aqui. TypeScript/Next.js apenas para o frontend planejado.
- **Apolo** — testes com `pytest` em `backend/tests/`; foco em collectors e webhook `/api/webhook`.
- **Gaia** — relevante para o módulo `plant_id.py`: identificação de plantas, pragas e doenças via foto. Domínio agro presente mesmo fora do agromouro-base.
- **n8n:** NUNCA modificar workflows via MCP — apenas leitura (`search_workflows`, `get_workflow_details`). Ver regra completa em Convenções.

---

## Como Rodar Localmente

```bash
pip install -r backend/requirements.txt
cp .env.example .env  # preencher variáveis
uvicorn backend.api.main:app --reload
```

## Testes

```bash
pytest backend/tests/ -v
```

## Deploy (Vercel)

```bash
vercel --prod
```

## Configurar Webhook Evolution API

```bash
curl -X POST "http://46.202.179.33:8080/webhook/set/noticiasgg" \
  -H "apikey: noticiasgg2026" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://noticiasgg.vercel.app/api/webhook", "events": ["MESSAGES_UPSERT"]}'
```
